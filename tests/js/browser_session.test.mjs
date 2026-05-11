import { describe, it, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import {
    ACTIVE_TAB_STORAGE_KEY,
    activeTabCount,
    initSingleActiveTabWarning,
    nextActiveTabRegistry,
    parseActiveTabRegistry,
    removeActiveTabFromRegistry,
    updateMultiTabWarning,
} from '../../static/js/browser-session.js';

function memoryStorage(initial = '') {
    return {
        value: initial,
        getItem(key) {
            return key === ACTIVE_TAB_STORAGE_KEY ? this.value : null;
        },
        setItem(key, value) {
            if (key === ACTIVE_TAB_STORAGE_KEY) this.value = String(value);
        },
        removeItem(key) {
            if (key === ACTIVE_TAB_STORAGE_KEY) this.value = '';
        },
    };
}

describe('single active tab warning', () => {
    afterEach(() => {
        state.singleActiveTabWarningInitialized = false;
        resetStubElement('multi-tab-warning-banner').hidden = true;
    });

    it('counts only recent tab heartbeats', () => {
        const registry = nextActiveTabRegistry(
            JSON.stringify({stale: 0, peer: 900}),
            'current',
            1000,
            250,
        );

        assert.deepStrictEqual(registry, {peer: 900, current: 1000});
        assert.equal(activeTabCount(registry, 1000, 250), 2);
        assert.equal(activeTabCount(registry, 1200, 250), 1);
        assert.deepStrictEqual(removeActiveTabFromRegistry(JSON.stringify(registry), 'current', 1000, 250), {peer: 900});
        assert.deepStrictEqual(parseActiveTabRegistry('not-json'), {});
    });

    it('shows the banner only when more than one tab is active', () => {
        const banner = getStubElement('multi-tab-warning-banner');

        updateMultiTabWarning(banner, 1);
        assert.equal(banner.hidden, true);

        updateMultiTabWarning(banner, 2);
        assert.equal(banner.hidden, false);
    });

    it('initializes a heartbeat and reacts to peer tabs without backend state', () => {
        const storage = memoryStorage();
        const banner = getStubElement('multi-tab-warning-banner');
        let now = 1000;
        const coordinator = initSingleActiveTabWarning({
            storage,
            banner,
            tabId: 'current',
            now: () => now,
            staleMs: 500,
            heartbeatMs: 60000,
            window: {addEventListener() {}},
            BroadcastChannel: null,
        });

        assert.ok(coordinator);
        assert.equal(banner.hidden, true);

        storage.setItem(ACTIVE_TAB_STORAGE_KEY, JSON.stringify({current: now, peer: now}));
        coordinator.refresh();
        assert.equal(banner.hidden, false);

        now = 2000;
        coordinator.refresh();
        assert.equal(banner.hidden, true);

        coordinator.cleanup();
    });
});
