import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { renderSetupCheckWizard } from '../../static/js/setup-check.js';


describe('setup check wizard', () => {
    beforeEach(() => {
        resetStubElement('setup-overlay');
        resetStubElement('setup-box');
        resetStubElement('setup-check-status');
    });

    it('renders grouped status rows without losing backend detail', () => {
        renderSetupCheckWizard({
            summary: {
                status: 'warning',
                message: 'Setup check completed with performance warnings.',
            },
            sections: [
                {
                    id: 'ollama',
                    title: 'Ollama',
                    items: [
                        {
                            id: 'ollama-gpu',
                            label: 'Ollama GPU acceleration',
                            status: 'warning',
                            detail: 'Ollama reports the selected model is running in system memory only.',
                        },
                    ],
                },
            ],
        });

        const setupOverlay = getStubElement('setup-overlay');
        const setupBox = getStubElement('setup-box');
        assert.equal(setupOverlay.style.display, 'flex');
        assert.match(setupBox.className, /setup-check-box/);
        assert.equal(setupBox.children[0].textContent, 'Setup Check Wizard');
        assert.match(setupBox.children[1].className, /setup-check-summary warning/);

        const list = setupBox.children[2];
        const section = list.children[0];
        const row = section.children[1];
        assert.match(row.className, /setup-check-row warning/);
        assert.equal(row.children[0].textContent, 'Warning');
        assert.equal(row.children[1].children[0].textContent, 'Ollama GPU acceleration');
        assert.equal(
            row.children[1].children[1].textContent,
            'Ollama reports the selected model is running in system memory only.',
        );
    });
});
