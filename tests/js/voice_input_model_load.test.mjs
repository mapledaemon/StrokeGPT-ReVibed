import { describe, it, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import { initVoiceInputControls } from '../../static/js/voice-input.js';


const PARAKEET_MODEL = 'nvidia/parakeet-tdt-0.6b-v3';
const LARGE_PARAKEET_MODEL = 'nvidia/parakeet-tdt-1.1b';

function jsonResponse(httpStatus, body) {
    const factory = () => ({
        ok: httpStatus >= 200 && httpStatus < 300,
        status: httpStatus,
        headers: {
            get(name) {
                return name && name.toLowerCase() === 'content-type'
                    ? 'application/json'
                    : null;
            },
        },
        async json() { return body; },
        async blob() { return null; },
        clone() { return factory(); },
    });
    return factory();
}

function voiceStatus(overrides = {}) {
    return {
        status_code: 'model_not_loaded',
        provider: 'local_nvidia_parakeet',
        enabled: true,
        model: PARAKEET_MODEL,
        model_cache_dir: 'user_data/voice_input_hf_cache',
        language: 'auto',
        mode: 'push_to_talk',
        submit_mode: 'preview',
        dependency_available: true,
        model_loaded: false,
        model_cached: false,
        can_load_model: true,
        load_requires_download: true,
        can_transcribe: false,
        message: `Voice input model is not downloaded. Use Download / Load Voice Input Model once to cache and load ${PARAKEET_MODEL}.`,
        last_error: '',
        last_transcript: '',
        last_timings: {},
        model_options: [
            {id: PARAKEET_MODEL, label: 'NVIDIA Parakeet TDT 0.6B v3'},
            {id: LARGE_PARAKEET_MODEL, label: 'NVIDIA Parakeet TDT 1.1B'},
        ],
        ...overrides,
    };
}

async function flushAsyncHandlers() {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
}

describe('voice input model load feedback', () => {
    let originalFetch;
    let originalConfirm;

    before(() => {
        originalFetch = globalThis.fetch;
        originalConfirm = globalThis.window.confirm;
        initVoiceInputControls({sendUserMessage: async () => ({})});
    });

    beforeEach(() => {
        [
            'status-text',
            'voice-input-status',
            'voice-input-diagnostics',
            'voice-input-provider-select',
            'voice-input-model-select',
            'voice-input-model-input',
            'voice-input-language-input',
            'voice-input-sensitivity-slider',
            'voice-input-sensitivity-val',
            'voice-input-silence-ms-input',
            'voice-input-min-recording-ms-input',
            'voice-input-max-recording-ms-input',
            'voice-input-noise-suppression-checkbox',
            'voice-input-echo-cancellation-checkbox',
            'voice-input-auto-gain-checkbox',
            'voice-input-noise-floor-input',
            'voice-input-noise-floor-val',
            'voice-input-audio-preprocessing-checkbox',
            'voice-input-silence-trim-checkbox',
            'voice-input-hands-free-mode-actions-checkbox',
            'voice-input-beam-size-input',
            'voice-input-condition-previous-checkbox',
            'voice-input-vad-threshold-input',
            'voice-input-vad-min-silence-ms-input',
            'voice-input-vad-speech-pad-ms-input',
            'download-voice-input-model-btn',
            'voice-input-menu-btn',
        ].forEach(resetStubElement);

        getStubElement('voice-input-provider-select').value = 'local_nvidia_parakeet';
        getStubElement('voice-input-model-select').value = PARAKEET_MODEL;
        getStubElement('voice-input-model-input').value = PARAKEET_MODEL;
        getStubElement('voice-input-language-input').value = 'auto';
        state.connectionLost = false;
        state.voiceInputStatusSnapshot = {};
        state.voiceInputLastIssue = '';
        globalThis.window.confirm = () => true;
        globalThis.fetch = originalFetch;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        globalThis.window.confirm = originalConfirm;
    });

    it('shows live percentage progress and then the provider load error', async () => {
        const calls = [];
        let finishPreload;
        const loadError = 'NVIDIA Parakeet worker stopped: operator torchvision::nms does not exist';
        const failedStatus = voiceStatus({
            status_code: 'error',
            model_cached: true,
            load_requires_download: false,
            preload_status: 'error',
            message: `Voice input model is cached but not loaded. Last error: ${loadError}`,
            last_error: loadError,
        });
        const preloadResponse = new Promise(resolve => {
            finishPreload = () => resolve(jsonResponse(409, {
                status: 'unavailable',
                message: loadError,
                voice_input_status: failedStatus,
            }));
        });

        globalThis.fetch = async (endpoint) => {
            calls.push(String(endpoint));
            if (endpoint === '/set_voice_input') {
                return jsonResponse(200, {
                    status: 'success',
                    message: 'Voice input settings saved.',
                    ...voiceStatus(),
                });
            }
            if (endpoint === '/preload_voice_input_model') return preloadResponse;
            throw new Error(`unexpected endpoint ${endpoint}`);
        };

        getStubElement('download-voice-input-model-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, ['/set_voice_input', '/preload_voice_input_model']);
        assert.match(getStubElement('status-text').textContent, /Downloading voice input model\.\.\. Progress: \d+%\. Elapsed: 0s\./);
        assert.match(getStubElement('download-voice-input-model-btn').textContent, /Downloading \/ Loading \d+%\.\.\./);

        finishPreload();
        await flushAsyncHandlers();

        assert.match(getStubElement('status-text').textContent, /NVIDIA Parakeet worker stopped/);
        assert.doesNotMatch(getStubElement('status-text').textContent, /cached but not loaded/i);
        assert.match(getStubElement('voice-input-status').textContent, /NVIDIA Parakeet worker stopped/);
        assert.equal(getStubElement('download-voice-input-model-btn').textContent, 'Load Voice Input Model');
    });
});
