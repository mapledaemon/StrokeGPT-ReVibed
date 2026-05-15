import { el } from './context.js';

const COMPACT_MOTION_QUERY = '(max-width: 760px)';
const APP_VIEWPORT_HEIGHT_VAR = '--app-viewport-height';
const VISUAL_VIEWPORT_BOTTOM_INSET_VAR = '--visual-viewport-bottom-inset';
const KEYBOARD_OPEN_CLASS = 'visual-keyboard-open';
const KEYBOARD_HEIGHT_DELTA_PX = 120;

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
    syncViewportInsetAndKeyboardState(height);
}

function isTextEntryElement(element) {
    if (!element) return false;
    const tagName = String(element.tagName || '').toLowerCase();
    if (tagName === 'textarea') return true;
    if (tagName === 'input') {
        const type = String(element.type || 'text').toLowerCase();
        return !['button', 'checkbox', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit'].includes(type);
    }
    return Boolean(element.isContentEditable);
}

export function syncKeyboardOpenState() {
    syncViewportInsetAndKeyboardState();
}

export function syncViewportInsetAndKeyboardState(viewportHeight = null) {
    const height = Number(viewportHeight ?? window.visualViewport?.height ?? window.innerHeight ?? document.documentElement?.clientHeight ?? 0);
    const layoutHeight = Number(window.innerHeight || document.documentElement?.clientHeight || 0);
    const viewportOffsetTop = Number(window.visualViewport?.offsetTop ?? 0);
    const hasFocusedTextEntry = isTextEntryElement(document.activeElement);
    const keyboardOpen = hasFocusedTextEntry
        && Number.isFinite(height)
        && Number.isFinite(layoutHeight)
        && layoutHeight - height > KEYBOARD_HEIGHT_DELTA_PX;
    const rawBottomInset = layoutHeight - viewportOffsetTop - height;
    const bottomInset = !keyboardOpen && Number.isFinite(rawBottomInset)
        ? Math.max(0, Math.round(rawBottomInset))
        : 0;
    if (keyboardOpen) document.body?.classList?.add(KEYBOARD_OPEN_CLASS);
    else document.body?.classList?.remove(KEYBOARD_OPEN_CLASS);
    setRootCssVariable(VISUAL_VIEWPORT_BOTTOM_INSET_VAR, `${bottomInset}px`);
}

export function initAppViewportHeightSync() {
    syncAppViewportHeight();
    window.visualViewport?.addEventListener?.('resize', syncAppViewportHeight);
    window.visualViewport?.addEventListener?.('scroll', syncAppViewportHeight);
    window.addEventListener?.('resize', syncAppViewportHeight);
    window.addEventListener?.('orientationchange', syncAppViewportHeight);
    document.addEventListener?.('focusin', syncKeyboardOpenState);
    document.addEventListener?.('focusout', () => window.setTimeout?.(syncKeyboardOpenState, 0));
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
