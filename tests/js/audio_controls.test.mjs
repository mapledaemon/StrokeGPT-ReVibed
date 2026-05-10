import { describe, it, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { initAudioControls, populateAudioSettings } from '../../static/js/audio.js';


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

async function flushAsyncHandlers() {
    await Promise.resolve();
    await Promise.resolve();
    await new Promise(resolve => setTimeout(resolve, 0));
}

describe('audio controls', () => {
    let originalFetch;

    before(() => {
        originalFetch = globalThis.fetch;
        initAudioControls();
    });

    beforeEach(() => {
        [
            'top-bar-voice-toggle-btn',
            'audio-provider-select',
            'enable-audio-checkbox',
            'elevenlabs-voice-select-box',
            'status-text',
            'local-tts-status',
            'local-tts-style-select',
            'local-tts-engine-select',
            'local-tts-prompt-path',
            'local-tts-exaggeration',
            'local-tts-exaggeration-val',
            'local-tts-cfg',
            'local-tts-cfg-val',
            'local-tts-temperature',
            'local-tts-temperature-val',
            'local-tts-top-p',
            'local-tts-top-p-val',
            'local-tts-min-p',
            'local-tts-min-p-val',
            'local-tts-repetition',
            'local-tts-repetition-val',
        ].forEach(resetStubElement);
        getStubElement('audio-provider-select').value = 'elevenlabs';
        getStubElement('elevenlabs-voice-select-box').value = 'voice-a';
        globalThis.fetch = originalFetch;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
    });

    it('mirrors saved audio enabled state into the top-bar voice toggle', () => {
        populateAudioSettings({audio_provider: 'elevenlabs', audio_enabled: true});

        const button = getStubElement('top-bar-voice-toggle-btn');
        assert.strictEqual(getStubElement('enable-audio-checkbox').checked, true);
        assert.strictEqual(button.textContent, 'Voice On');
        assert.strictEqual(button.title, 'Turn voice output off');
        assert.strictEqual(button.getAttribute('aria-label'), 'Voice output on');
        assert.strictEqual(button.getAttribute('aria-pressed'), 'true');
        assert.strictEqual(button.classList.contains('is-on'), true);
    });

    it('top-bar voice toggle persists through the existing ElevenLabs audio route', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push([endpoint, JSON.parse(options.body)]);
            return jsonResponse(200, {status: 'ok', message: 'Settings updated.'});
        };
        populateAudioSettings({audio_provider: 'elevenlabs', audio_enabled: true});
        getStubElement('elevenlabs-voice-select-box').value = 'voice-a';

        getStubElement('top-bar-voice-toggle-btn').click();
        await flushAsyncHandlers();

        assert.deepStrictEqual(calls, [['/set_elevenlabs_voice', {voice_id: 'voice-a', enabled: false}]]);
        assert.strictEqual(getStubElement('enable-audio-checkbox').checked, false);
        assert.strictEqual(getStubElement('top-bar-voice-toggle-btn').textContent, 'Voice Off');
        assert.strictEqual(getStubElement('top-bar-voice-toggle-btn').getAttribute('aria-pressed'), 'false');
    });

    it('top-bar voice toggle reverts when the backend rejects enabling voice output', async () => {
        globalThis.fetch = async () => jsonResponse(200, {
            status: 'error',
            message: 'A voice must be selected to enable ElevenLabs audio.',
        });
        populateAudioSettings({audio_provider: 'elevenlabs', audio_enabled: false});
        getStubElement('elevenlabs-voice-select-box').value = '';

        getStubElement('top-bar-voice-toggle-btn').click();
        await flushAsyncHandlers();

        assert.strictEqual(getStubElement('enable-audio-checkbox').checked, false);
        assert.strictEqual(getStubElement('top-bar-voice-toggle-btn').textContent, 'Voice Off');
        assert.strictEqual(getStubElement('top-bar-voice-toggle-btn').getAttribute('aria-pressed'), 'false');
        assert.strictEqual(getStubElement('status-text').textContent, 'A voice must be selected to enable ElevenLabs audio.');
        assert.strictEqual(getStubElement('status-text').style.color, 'var(--yellow)');
    });
});
