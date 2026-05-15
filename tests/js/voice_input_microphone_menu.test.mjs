import { describe, it, before, beforeEach, afterEach, after } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import { initVoiceInputControls } from '../../static/js/voice-input.js';

const DEVICES = [
    {kind: 'audioinput', deviceId: 'mic-one', label: 'Desk microphone'},
    {kind: 'videoinput', deviceId: 'camera-one', label: 'Camera'},
    {kind: 'audioinput', deviceId: 'mic-two', label: 'Headset microphone'},
];

function jsonResponse(body) {
    return {
        ok: true,
        status: 200,
        headers: {get: () => 'application/json'},
        async json() { return body; },
        clone() { return jsonResponse(body); },
    };
}

function readyVoiceInputStatus() {
    return {
        status_code: 'ready',
        provider: 'local_faster_whisper',
        enabled: true,
        model: 'tiny.en',
        language: 'auto',
        mode: 'push_to_talk',
        submit_mode: 'preview',
        dependency_available: true,
        model_loaded: true,
        model_cached: true,
        can_load_model: true,
        load_requires_download: false,
        can_transcribe: true,
        message: 'Voice input ready.',
        last_error: '',
        last_transcript: '',
        last_timings: {},
        model_options: [{id: 'tiny.en', label: 'Fast - tiny.en'}],
    };
}

function flushAsyncHandlers() {
    return new Promise(resolve => setTimeout(resolve, 0));
}

describe('voice input microphone menu', () => {
    let originalFetch;
    let originalMediaDevices;
    let originalMediaRecorder;
    let originalWindowMediaRecorder;
    let originalLocalStorage;
    let getUserMediaCalls;

    before(() => {
        originalFetch = globalThis.fetch;
        originalMediaDevices = globalThis.navigator.mediaDevices;
        originalMediaRecorder = globalThis.MediaRecorder;
        originalWindowMediaRecorder = globalThis.window.MediaRecorder;
        originalLocalStorage = globalThis.window.localStorage;

        Object.defineProperty(globalThis.navigator, 'mediaDevices', {
            configurable: true,
            writable: true,
            value: {
                enumerateDevices: async () => DEVICES,
                getUserMedia: async constraints => {
                    getUserMediaCalls.push(constraints);
                    const stream = {
                        active: true,
                        getTracks: () => [{
                            stop() { stream.active = false; },
                        }],
                    };
                    return stream;
                },
            },
        });
        globalThis.window.localStorage = {
            getItem: () => '',
            setItem: () => {},
            removeItem: () => {},
        };
        class TestMediaRecorder {
            static isTypeSupported() { return false; }
            constructor(stream) {
                this.stream = stream;
                this.mimeType = 'audio/webm';
                this.state = 'inactive';
                this.listeners = {};
            }
            addEventListener(name, fn) {
                (this.listeners[name] ||= []).push(fn);
            }
            start() {
                this.state = 'recording';
            }
            stop() {
                this.state = 'inactive';
                for (const fn of this.listeners.stop || []) fn();
            }
        }
        globalThis.MediaRecorder = TestMediaRecorder;
        globalThis.window.MediaRecorder = TestMediaRecorder;
        globalThis.fetch = async endpoint => {
            if (endpoint === '/voice_input_status') return jsonResponse(readyVoiceInputStatus());
            throw new Error(`unexpected endpoint ${endpoint}`);
        };

        initVoiceInputControls({sendUserMessage: async () => ({})});
    });

    beforeEach(async () => {
        [
            'status-text',
            'voice-input-menu-btn',
            'voice-input-options-btn',
            'voice-input-popover',
            'voice-input-device-select',
            'refresh-microphone-devices-btn',
            'voice-input-device-status',
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
        ].forEach(resetStubElement);
        getUserMediaCalls = [];
        state.voiceInputDevices = [];
        state.voiceInputDeviceId = '';
        state.voiceInputDeviceMenuOpen = false;
        state.voiceInputRecording = false;
        state.voiceInputHandsFreeArmed = false;
        state.voiceInputStream = null;
        state.voiceInputProvider = 'local_faster_whisper';
        state.voiceInputEnabled = true;
        state.voiceInputCanTranscribe = true;
        state.voiceInputMode = 'push_to_talk';
        await flushAsyncHandlers();
    });

    afterEach(() => {
        if (state.voiceInputRecorder?.state === 'recording') state.voiceInputRecorder.stop();
        if (state.voiceInputStream) {
            state.voiceInputStream.getTracks().forEach(track => track.stop());
            state.voiceInputStream = null;
        }
        state.voiceInputRecorder = null;
        state.voiceInputRecording = false;
    });

    after(() => {
        globalThis.fetch = originalFetch;
        Object.defineProperty(globalThis.navigator, 'mediaDevices', {
            configurable: true,
            writable: true,
            value: originalMediaDevices,
        });
        globalThis.MediaRecorder = originalMediaRecorder;
        globalThis.window.MediaRecorder = originalWindowMediaRecorder;
        globalThis.window.localStorage = originalLocalStorage;
    });

    it('opens a caret menu with refreshable microphone choices', async () => {
        getStubElement('voice-input-options-btn').click();
        await flushAsyncHandlers();

        const select = getStubElement('voice-input-device-select');
        assert.equal(getStubElement('voice-input-popover').hidden, false);
        assert.equal(getStubElement('voice-input-options-btn').getAttribute('aria-expanded'), 'true');
        assert.deepEqual(
            select.options.map(option => option.textContent),
            ['System default microphone', 'Desk microphone', 'Headset microphone'],
        );
        assert.match(getStubElement('voice-input-device-status').textContent, /system default microphone/i);
    });

    it('uses the selected microphone device for the next recording stream', async () => {
        getStubElement('voice-input-options-btn').click();
        await flushAsyncHandlers();

        const select = getStubElement('voice-input-device-select');
        select.value = 'mic-two';
        select.dispatchEvent('change', {target: select});

        getStubElement('voice-input-menu-btn').click();
        await flushAsyncHandlers();

        assert.equal(state.voiceInputDeviceId, 'mic-two');
        assert.equal(getUserMediaCalls.length, 1);
        assert.deepEqual(getUserMediaCalls[0].audio.deviceId, {exact: 'mic-two'});
    });

    it('explains mobile LAN microphone blocking before requesting a stream', async () => {
        const previousSecureContext = globalThis.window.isSecureContext;
        const previousWindowHost = globalThis.window.location.hostname;
        const previousGlobalHost = globalThis.location?.hostname;
        Object.defineProperty(globalThis.window, 'isSecureContext', {
            configurable: true,
            writable: true,
            value: false,
        });
        globalThis.window.location.hostname = '192.168.1.55';
        if (globalThis.location) globalThis.location.hostname = '192.168.1.55';

        try {
            getStubElement('voice-input-menu-btn').click();
            await flushAsyncHandlers();

            assert.equal(getUserMediaCalls.length, 0);
            assert.match(getStubElement('voice-input-status').textContent, /HTTPS or localhost/i);
            assert.match(getStubElement('voice-input-options-btn').title, /HTTPS or localhost/i);
        } finally {
            Object.defineProperty(globalThis.window, 'isSecureContext', {
                configurable: true,
                writable: true,
                value: previousSecureContext,
            });
            globalThis.window.location.hostname = previousWindowHost;
            if (globalThis.location) globalThis.location.hostname = previousGlobalHost;
        }
    });
});
