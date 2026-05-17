import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { setSplashLoadingStatus } from '../../static/js/setup.js';


describe('startup splash status', () => {
    beforeEach(() => {
        resetStubElement('splash-status');
        resetStubElement('splash-progress-bar');
        resetStubElement('splash-progress-text');
    });

    it('updates the splash message and progress bar together', () => {
        setSplashLoadingStatus(42, 'Checking local voice settings...');

        assert.equal(getStubElement('splash-status').textContent, 'Checking local voice settings...');
        assert.equal(getStubElement('splash-progress-bar').style.width, '42%');
        assert.equal(getStubElement('splash-progress-text').textContent, '42%');
    });

    it('clamps invalid splash progress values', () => {
        setSplashLoadingStatus(143.6, 'Opening chat...');

        assert.equal(getStubElement('splash-progress-bar').style.width, '100%');
        assert.equal(getStubElement('splash-progress-text').textContent, '100%');
    });
});
