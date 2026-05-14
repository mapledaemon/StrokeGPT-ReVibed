import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { initCompactMotionPanels, syncCompactMotionPanels } from '../../static/js/responsive-layout.js';

function makeMediaQuery(matches) {
    const listeners = [];
    return {
        matches,
        addEventListener(type, listener) {
            if (type === 'change') listeners.push(listener);
        },
        setMatches(nextMatches) {
            this.matches = nextMatches;
            for (const listener of listeners) listener({matches: nextMatches});
        },
    };
}

describe('compact motion panels', () => {
    beforeEach(() => {
        resetStubElement('motion-history-panel');
        resetStubElement('motion-current-status-panel');
        getStubElement('motion-history-panel').open = true;
        getStubElement('motion-current-status-panel').open = true;
    });

    it('collapses motion history and status by default in compact layouts', () => {
        syncCompactMotionPanels(true);

        assert.equal(getStubElement('motion-history-panel').open, false);
        assert.equal(getStubElement('motion-current-status-panel').open, false);
        assert.equal(getStubElement('motion-history-panel').dataset.compactInitialized, 'true');
        assert.equal(getStubElement('motion-current-status-panel').dataset.compactInitialized, 'true');
    });

    it('opens both motion panels outside compact layouts', () => {
        getStubElement('motion-history-panel').open = false;
        getStubElement('motion-current-status-panel').open = false;

        syncCompactMotionPanels(false);

        assert.equal(getStubElement('motion-history-panel').open, true);
        assert.equal(getStubElement('motion-current-status-panel').open, true);
        assert.equal(getStubElement('motion-history-panel').dataset.compactInitialized, undefined);
        assert.equal(getStubElement('motion-current-status-panel').dataset.compactInitialized, undefined);
    });

    it('responds to compact breakpoint changes without repeatedly closing user-opened panels', () => {
        const originalMatchMedia = globalThis.window.matchMedia;
        const query = makeMediaQuery(false);
        globalThis.window.matchMedia = () => query;
        try {
            initCompactMotionPanels();
            assert.equal(getStubElement('motion-history-panel').open, true);
            assert.equal(getStubElement('motion-current-status-panel').open, true);

            query.setMatches(true);
            assert.equal(getStubElement('motion-history-panel').open, false);
            assert.equal(getStubElement('motion-current-status-panel').open, false);

            getStubElement('motion-history-panel').open = true;
            syncCompactMotionPanels(true);
            assert.equal(getStubElement('motion-history-panel').open, true);
            assert.equal(getStubElement('motion-current-status-panel').open, false);

            query.setMatches(false);
            assert.equal(getStubElement('motion-history-panel').open, true);
            assert.equal(getStubElement('motion-current-status-panel').open, true);
        } finally {
            globalThis.window.matchMedia = originalMatchMedia;
        }
    });
});
