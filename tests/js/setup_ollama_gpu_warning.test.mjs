import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { renderSetup } from '../../static/js/setup.js';


describe('setup Ollama GPU warning', () => {
    beforeEach(() => {
        resetStubElement('setup-overlay');
        resetStubElement('setup-box');
        resetStubElement('setup-persona-select');
        resetStubElement('setup-persona');
        resetStubElement('setup-save-persona');
        resetStubElement('setup-next');
    });

    it('renders the backend CPU-only Ollama warning in setup without inventing copy', () => {
        renderSetup(true, {
            persona: 'An energetic and passionate teammate',
            persona_prompts: ['An energetic and passionate teammate'],
            ollama_status: {
                gpu_status: {
                    setup_warning: 'Ollama reports the selected model is running in system memory only.',
                },
            },
        });

        const setupBox = getStubElement('setup-box');
        assert.equal(setupBox.children[0].className, 'setup-warning');
        assert.equal(
            setupBox.children[0].textContent,
            'Ollama reports the selected model is running in system memory only.',
        );
        assert.equal(setupBox.children[0].getAttribute('role'), 'alert');
    });
});
