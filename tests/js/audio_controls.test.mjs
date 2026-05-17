import { describe, it, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { URL as NodeURL } from 'node:url';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { initAudioControls, playQueuedAudio, populateAudioSettings } from '../../static/js/audio.js';
import { state } from '../../static/js/context.js';


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

function endpointUrl(endpoint) {
    return new NodeURL(String(endpoint), 'http://strokegpt.test');
}

function endpointSummary(endpoint) {
    const url = endpointUrl(endpoint);
    return {
        path: url.pathname,
        client_id: url.searchParams.get('client_id'),
        wait_ms: url.searchParams.get('wait_ms'),
    };
}

function makeMemoryStorage(initial = {}) {
    const values = new Map(Object.entries(initial));
    return {
        getItem(key) { return values.has(key) ? values.get(key) : null; },
        setItem(key, value) { values.set(key, String(value)); },
        removeItem(key) { values.delete(key); },
        clear() { values.clear(); },
    };
}

function installLocalStorage(storage) {
    Object.defineProperty(globalThis, 'localStorage', {
        value: storage,
        configurable: true,
        writable: true,
    });
    globalThis.window.localStorage = storage;
}

describe('audio controls', () => {
    let originalFetch;
    let originalAudio;
    let originalUrl;
    let originalLocalStorageDescriptor;
    let originalWindowLocalStorage;

    before(() => {
        originalFetch = globalThis.fetch;
        originalAudio = globalThis.Audio;
        originalUrl = globalThis.URL;
        originalLocalStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
        originalWindowLocalStorage = globalThis.window.localStorage;
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
        state.uiClientId = 'audio-test-client';
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        globalThis.Audio = originalAudio;
        globalThis.URL = originalUrl;
        globalThis.window.localStorage = originalWindowLocalStorage;
        if (originalLocalStorageDescriptor) {
            Object.defineProperty(globalThis, 'localStorage', originalLocalStorageDescriptor);
        } else {
            delete globalThis.localStorage;
        }
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

    it('drains queued audio chunks after the first waited fetch', async () => {
        const endpoints = [];
        const responses = [200, 200, 204];
        globalThis.fetch = async endpoint => {
            endpoints.push(endpoint);
            const status = responses.shift();
            return jsonResponse(status, status === 204 ? null : {audio: true});
        };
        let plays = 0;
        globalThis.URL = {
            createObjectURL() { return `blob:audio-${plays}`; },
            revokeObjectURL() {},
        };
        globalThis.Audio = class StubAudio {
            play() {
                plays += 1;
                queueMicrotask(() => this.onended?.());
                return Promise.resolve();
            }
        };

        const played = await playQueuedAudio({waitMs: 1200, followupWaitMs: 400});

        assert.strictEqual(played, true);
        assert.strictEqual(plays, 2);
        assert.deepStrictEqual(endpoints.map(endpointSummary), [
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: '1200'},
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: '400'},
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: '400'},
        ]);
    });

    it('serializes overlapping audio playback drain requests', async () => {
        const endpoints = [];
        const responses = [200, 204, 200, 204];
        globalThis.fetch = async endpoint => {
            endpoints.push(endpoint);
            const status = responses.shift();
            return jsonResponse(status, null);
        };
        let activePlays = 0;
        let maxActivePlays = 0;
        const finishers = [];
        globalThis.URL = {
            createObjectURL() { return `blob:serial-${finishers.length}`; },
            revokeObjectURL() {},
        };
        globalThis.Audio = class StubAudio {
            play() {
                activePlays += 1;
                maxActivePlays = Math.max(maxActivePlays, activePlays);
                return new Promise(resolve => {
                    finishers.push(() => {
                        activePlays -= 1;
                        this.onended?.();
                        resolve();
                    });
                });
            }
        };

        const first = playQueuedAudio();
        await flushAsyncHandlers();
        assert.strictEqual(finishers.length, 1);

        const second = playQueuedAudio();
        await flushAsyncHandlers();
        assert.strictEqual(finishers.length, 1);

        finishers[0]();
        assert.strictEqual(await first, true);
        await flushAsyncHandlers();
        assert.strictEqual(finishers.length, 2);

        finishers[1]();
        assert.strictEqual(await second, true);
        assert.strictEqual(maxActivePlays, 1);
        assert.deepStrictEqual(endpoints.map(endpointSummary), [
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: null},
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: '350'},
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: null},
            {path: '/get_audio', client_id: 'audio-test-client', wait_ms: '350'},
        ]);
    });

    it('does not consume audio while another browser tab owns playback', async () => {
        const storage = makeMemoryStorage({
            'strokegpt.audioPlaybackLock.v1': JSON.stringify({
                owner: 'other-tab',
                expiresAt: Date.now() + 60000,
            }),
        });
        installLocalStorage(storage);
        let fetchCalled = false;
        globalThis.fetch = async endpoint => {
            fetchCalled = true;
            return jsonResponse(200, null);
        };

        const played = await playQueuedAudio();

        assert.strictEqual(played, false);
        assert.strictEqual(fetchCalled, false);
    });
});
