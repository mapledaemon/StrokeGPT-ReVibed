import { el, state } from './context.js';

export const ACTIVE_TAB_STORAGE_KEY = 'strokegpt.activeTabs.v1';
export const ACTIVE_TAB_CHANNEL_NAME = 'strokegpt.active-tabs';
export const ACTIVE_TAB_HEARTBEAT_MS = 2000;
export const ACTIVE_TAB_STALE_MS = 6500;

function createTabId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export function parseActiveTabRegistry(raw) {
    if (!raw) return {};
    try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch {
        return {};
    }
}

export function pruneActiveTabRegistry(registry, now = Date.now(), staleMs = ACTIVE_TAB_STALE_MS) {
    const result = {};
    for (const [tabId, timestamp] of Object.entries(registry || {})) {
        const seenAt = Number(timestamp);
        if (!tabId || !Number.isFinite(seenAt)) continue;
        if (now - seenAt <= staleMs) result[tabId] = seenAt;
    }
    return result;
}

export function nextActiveTabRegistry(raw, tabId, now = Date.now(), staleMs = ACTIVE_TAB_STALE_MS) {
    const registry = pruneActiveTabRegistry(parseActiveTabRegistry(raw), now, staleMs);
    registry[tabId] = now;
    return registry;
}

export function removeActiveTabFromRegistry(raw, tabId, now = Date.now(), staleMs = ACTIVE_TAB_STALE_MS) {
    const registry = pruneActiveTabRegistry(parseActiveTabRegistry(raw), now, staleMs);
    delete registry[tabId];
    return registry;
}

export function activeTabCount(registry, now = Date.now(), staleMs = ACTIVE_TAB_STALE_MS) {
    return Object.keys(pruneActiveTabRegistry(registry, now, staleMs)).length;
}

export function updateMultiTabWarning(banner, count) {
    if (!banner) return;
    banner.hidden = count <= 1;
}

function safeRead(storage) {
    try {
        return storage?.getItem?.(ACTIVE_TAB_STORAGE_KEY) || '';
    } catch {
        return '';
    }
}

function safeWrite(storage, registry) {
    try {
        storage?.setItem?.(ACTIVE_TAB_STORAGE_KEY, JSON.stringify(registry));
    } catch {
        // Private browsing or locked-down storage should not block the app.
    }
}

function safeRemove(storage, tabId, now) {
    const registry = removeActiveTabFromRegistry(safeRead(storage), tabId, now);
    if (Object.keys(registry).length) safeWrite(storage, registry);
    else {
        try {
            storage?.removeItem?.(ACTIVE_TAB_STORAGE_KEY);
        } catch {
            // Ignore storage cleanup failures.
        }
    }
    return registry;
}

export function initSingleActiveTabWarning(options = {}) {
    if (state.singleActiveTabWarningInitialized) return null;
    let storage = options.storage;
    if (!storage) {
        try {
            storage = globalThis.localStorage;
        } catch {
            storage = null;
        }
    }
    if (!storage) return null;

    state.singleActiveTabWarningInitialized = true;
    const nowFn = options.now || (() => Date.now());
    const tabId = options.tabId || createTabId();
    const heartbeatMs = options.heartbeatMs || ACTIVE_TAB_HEARTBEAT_MS;
    const staleMs = options.staleMs || ACTIVE_TAB_STALE_MS;
    const banner = options.banner || el.multiTabWarningBanner;
    const win = options.window || globalThis.window;
    const Channel = Object.prototype.hasOwnProperty.call(options, 'BroadcastChannel')
        ? options.BroadcastChannel
        : globalThis.BroadcastChannel;
    const channel = Channel ? new Channel(ACTIVE_TAB_CHANNEL_NAME) : null;

    const refresh = () => {
        const registry = nextActiveTabRegistry(safeRead(storage), tabId, nowFn(), staleMs);
        safeWrite(storage, registry);
        updateMultiTabWarning(banner, activeTabCount(registry, nowFn(), staleMs));
        channel?.postMessage?.({type: 'heartbeat', tabId});
        return registry;
    };

    const syncFromStorage = () => {
        updateMultiTabWarning(
            banner,
            activeTabCount(parseActiveTabRegistry(safeRead(storage)), nowFn(), staleMs),
        );
    };

    refresh();
    const timer = setInterval(refresh, heartbeatMs);
    const onStorage = event => {
        if (!event || event.key === ACTIVE_TAB_STORAGE_KEY) syncFromStorage();
    };
    const onMessage = () => syncFromStorage();
    const cleanup = () => {
        clearInterval(timer);
        channel?.close?.();
        safeRemove(storage, tabId, nowFn());
        syncFromStorage();
        state.singleActiveTabWarningInitialized = false;
    };

    win?.addEventListener?.('storage', onStorage);
    win?.addEventListener?.('pagehide', cleanup, {once: true});
    win?.addEventListener?.('beforeunload', cleanup, {once: true});
    channel?.addEventListener?.('message', onMessage);
    return {tabId, refresh, cleanup};
}
