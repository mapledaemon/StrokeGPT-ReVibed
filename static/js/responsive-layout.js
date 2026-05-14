import { el } from './context.js';

const COMPACT_MOTION_QUERY = '(max-width: 760px)';

function motionPanels() {
    return [
        el.motionHistoryPanel,
        el.motionCurrentStatusPanel,
    ].filter(Boolean);
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
    if (query.addEventListener) query.addEventListener('change', apply);
    else query.addListener?.(apply);
}
