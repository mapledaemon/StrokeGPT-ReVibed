import { el } from './context.js';

const COMPACT_MOTION_QUERY = '(max-width: 760px)';
const APP_VIEWPORT_HEIGHT_VAR = '--app-viewport-height';

function setRootCssVariable(name, value) {
    const style = document.documentElement?.style;
    if (!style) return;
    if (typeof style.setProperty === 'function') {
        style.setProperty(name, value);
    } else {
        style[name] = value;
    }
}

export function syncAppViewportHeight() {
    const height = Number(window.visualViewport?.height || window.innerHeight || document.documentElement?.clientHeight || 0);
    if (!Number.isFinite(height) || height <= 0) return;
    setRootCssVariable(APP_VIEWPORT_HEIGHT_VAR, `${Math.round(height)}px`);
}

export function initAppViewportHeightSync() {
    syncAppViewportHeight();
    window.visualViewport?.addEventListener?.('resize', syncAppViewportHeight);
    window.visualViewport?.addEventListener?.('scroll', syncAppViewportHeight);
    window.addEventListener?.('resize', syncAppViewportHeight);
    window.addEventListener?.('orientationchange', syncAppViewportHeight);
}

function motionPanels() {
    return [
        el.motionHistoryPanel,
        el.motionCurrentStatusPanel,
    ].filter(Boolean);
}

export function keepSingleCompactMotionPanelOpen(openedPanel, matchesCompact) {
    if (!matchesCompact || !openedPanel?.open) return;
    for (const panel of motionPanels()) {
        if (panel !== openedPanel) panel.open = false;
    }
}

export function syncCompactMotionPanels(matchesCompact) {
    for (const panel of motionPanels()) {
        if (matchesCompact) {
            if (panel.dataset.compactInitialized === 'true') continue;
            panel.open = false;
            panel.dataset.compactInitialized = 'true';
        } else {
            panel.open = true;
            delete panel.dataset.compactInitialized;
        }
    }
}

export function initCompactMotionPanels() {
    const panels = motionPanels();
    if (!panels.length) return;
    const query = window.matchMedia?.(COMPACT_MOTION_QUERY);
    if (!query) return;
    const apply = event => syncCompactMotionPanels(Boolean(event?.matches ?? query.matches));
    apply(query);
    for (const panel of panels) {
        if (panel.dataset.compactToggleBound === 'true') continue;
        panel.addEventListener('toggle', () => keepSingleCompactMotionPanelOpen(panel, query.matches));
        panel.dataset.compactToggleBound = 'true';
    }
    if (query.addEventListener) query.addEventListener('change', apply);
    else query.addListener?.(apply);
}
