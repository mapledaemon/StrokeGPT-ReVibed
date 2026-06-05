// Behavioral coverage for the motion/audio save-feedback wiring that used to
// be pinned by tests/test_motion_save_feedback_wiring.py. These tests keep the
// contract user-visible: a reachable backend rejection writes the server's
// message to the same status element the real control uses.

import { describe, it, before, beforeEach, after, afterEach } from 'node:test';
import assert from 'node:assert';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { initAudioControls, updateLocalTtsStatus } from '../../static/js/audio.js';
import { initMotionControls, populateMotionSettings } from '../../static/js/motion-control.js';
import {
    createPatternTagsButton,
    resetMotionPatternFeedback,
    setMotionPatternEnabled,
    setMotionPatternTags,
    setMotionPatternWeight,
} from '../../static/js/motion/pattern-list.js';
import { resetMotionPreferences, saveMotionFeedbackOptions } from '../../static/js/motion/feedback-controls.js';
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

describe('motion/audio save feedback', () => {
    let originalFetch;
    let originalRequestAnimationFrame;

    before(async () => {
        originalFetch = globalThis.fetch;
        originalRequestAnimationFrame = globalThis.window.requestAnimationFrame;

        globalThis.window.requestAnimationFrame = () => 0;
        globalThis.window.confirm = () => true;
        globalThis.fetch = async () => jsonResponse(200, {
            status: 'success',
            patterns: [{
                id: 'seed',
                name: 'Seed',
                source: 'fixed',
                enabled: true,
                duration_ms: 1000,
                action_count: 2,
                actions: [{ at: 0, pos: 30 }, { at: 1000, pos: 70 }],
            }],
            feedback_history: [],
        });
        initMotionControls({ sendUserMessage: () => {} });
        initAudioControls();
        await flushAsyncHandlers();
    });

    after(() => {
        globalThis.fetch = originalFetch;
        globalThis.window.requestAnimationFrame = originalRequestAnimationFrame;
    });

    beforeEach(() => {
        resetStubElement('status-text');
        resetStubElement('motion-backend-status');
        resetStubElement('motion-pattern-status');
        resetStubElement('motion-style-select');
        resetStubElement('motion-style-status');
        resetStubElement('reset-motion-preferences-btn');
        resetStubElement('motion-feedback-history');
        resetStubElement('local-tts-status');
        resetStubElement('download-local-tts-model-button');
        resetStubElement('llm-edge-permissions-status');
        resetStubElement('motion-pattern-library-freestyle-checkbox');
        resetStubElement('motion-pattern-library-chat-checkbox');
        resetStubElement('motion-feedback-auto-disable-checkbox');
        resetStubElement('top-bar-autospeak-toggle-btn');
        resetStubElement('autospeak-min-seconds');
        resetStubElement('autospeak-max-seconds');
        resetStubElement('autospeak-motion-autonomy-select');
        resetStubElement('autospeak-motion-autonomy-status');
        resetStubElement('save-motion-tab-btn');
        resetStubElement('active-mode-status');
        resetStubElement('active-mode-label');
        resetStubElement('edging-timer');
        resetStubElement('im-close-btn');
        resetStubElement('pause-resume-btn');
        getStubElement('status-text').textContent = 'baseline';
        getStubElement('motion-backend-status').textContent = 'baseline';
        getStubElement('motion-pattern-status').textContent = 'baseline';
        getStubElement('local-tts-status').textContent = 'baseline';
        getStubElement('llm-edge-permissions-status').textContent = 'baseline';
        state.connectionLost = false;
        state.activeModeName = '';
        state.autospeakEnabled = false;
        state.autospeakMinSeconds = 12;
        state.autospeakMaxSeconds = 45;
        state.autospeakMotionAutonomy = 'full';
        state.autospeakMotionAutonomyOptions = [];
        state.motionPatternLibraryEnabledInFreestyle = false;
        state.motionPatternLibraryEnabledInChat = false;
        state.motionFeedbackAutoDisable = false;
        state.motionStyle = 'balanced';
        state.motionStyleOptions = [
            {id: 'balanced', label: 'Balanced', description: 'Let the model choose a sensible mix.'},
            {id: 'high_variation', label: 'High variation', description: 'Use more motion contrast.'},
        ];
        state.motionTraining = {state: 'idle', pattern_id: 'seed', pattern_name: 'Seed', preview: false};
        state.motionTrainingOriginalPattern = null;
        state.motionTrainingEditedPattern = null;
        state.motionTrainingDirty = false;
        state.motionStudioSourcePattern = null;
        state.motionStudioCropStartMs = 0;
        state.motionStudioCropEndMs = 0;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
    });

    function installBackendError(message) {
        globalThis.fetch = async () => jsonResponse(200, {
            status: 'error',
            message,
        });
    }

    function installFetchQueue(responses) {
        const queue = [...responses];
        globalThis.fetch = async () => {
            const response = queue.shift();
            if (!response) throw new Error('fetch queue exhausted');
            return response;
        };
    }

    async function flushAsyncHandlers() {
        await Promise.resolve();
        await Promise.resolve();
        await new Promise(resolve => setTimeout(resolve, 0));
    }

    it('saveMotionBackend surfaces the backend message on the backend status span', async () => {
        installBackendError('Motion backend rejected.');

        getStubElement('motion-backend-select').value = 'position';
        getStubElement('save-motion-backend-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('motion-backend-status');
        assert.strictEqual(status.textContent, 'Motion backend rejected.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('saveMotionSpeedLimits surfaces the backend message on global status', async () => {
        installBackendError('Speed limit range is invalid.');

        getStubElement('motion-speed-min-slider').value = '20';
        getStubElement('motion-speed-max-slider').value = '80';
        getStubElement('save-motion-speed-limits').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Speed limit range is invalid.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('toggleLongTermMemory surfaces the backend message on global status', async () => {
        installBackendError('Memory toggle failed.');

        getStubElement('toggle-memory-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Memory toggle failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('saveModeTimings surfaces the backend message on global status', async () => {
        installBackendError('Mode timing range is invalid.');

        getStubElement('auto-min-time').value = '4';
        getStubElement('auto-max-time').value = '7';
        getStubElement('edging-min-time').value = '5';
        getStubElement('edging-max-time').value = '8';
        getStubElement('milking-min-time').value = '2.5';
        getStubElement('milking-max-time').value = '4.5';
        getStubElement('save-timings-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Mode timing range is invalid.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('saveMotionTabSettings saves each Motion section through existing routes', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, body: JSON.parse(options.body || '{}')});
            if (endpoint === '/set_motion_backend') {
                return jsonResponse(200, {status: 'success', motion_backend: 'continuous'});
            }
            if (endpoint === '/set_motion_style') {
                return jsonResponse(200, {
                    status: 'success',
                    motion_style: 'balanced',
                    motion_style_options: state.motionStyleOptions,
                });
            }
            if (endpoint === '/set_motion_reverse_direction') {
                return jsonResponse(200, {status: 'success', motion_reverse_direction: false});
            }
            if (endpoint === '/set_speed_limits') {
                return jsonResponse(200, {status: 'success', min_speed: 20, max_speed: 80});
            }
            if (endpoint === '/set_mode_timings') {
                return jsonResponse(200, {
                    status: 'success',
                    timings: {
                        auto_min: 4,
                        auto_max: 7,
                        edging_min: 5,
                        edging_max: 8,
                        milking_min: 2,
                        milking_max: 5,
                    },
                });
            }
            if (endpoint === '/set_llm_edge_permissions') {
                return jsonResponse(200, {
                    status: 'success',
                    allow_llm_edge_in_freestyle: true,
                    allow_llm_edge_in_chat: true,
                    allow_llm_mode_actions_in_chat: true,
                    autospeak_min_seconds: 12,
                    autospeak_max_seconds: 45,
                    autospeak_motion_autonomy: 'full',
                });
            }
            if (endpoint === '/motion_feedback_options') {
                return jsonResponse(200, {
                    status: 'success',
                    motion_feedback_auto_disable: false,
                    motion_pattern_library_enabled_in_freestyle: true,
                    motion_pattern_library_enabled_in_chat: true,
                    motion_patterns: [],
                });
            }
            throw new Error(`unexpected endpoint ${endpoint}`);
        };

        getStubElement('motion-backend-select').value = 'continuous';
        getStubElement('motion-style-select').value = 'balanced';
        getStubElement('motion-direction-normal').checked = true;
        getStubElement('motion-direction-reverse').checked = false;
        getStubElement('motion-speed-min-slider').value = '20';
        getStubElement('motion-speed-max-slider').value = '80';
        getStubElement('auto-min-time').value = '4';
        getStubElement('auto-max-time').value = '7';
        getStubElement('edging-min-time').value = '5';
        getStubElement('edging-max-time').value = '8';
        getStubElement('milking-min-time').value = '2';
        getStubElement('milking-max-time').value = '5';
        getStubElement('allow-llm-edge-freestyle-checkbox').checked = true;
        getStubElement('allow-llm-edge-chat-checkbox').checked = true;
        getStubElement('allow-llm-mode-actions-chat-checkbox').checked = true;
        getStubElement('motion-pattern-library-freestyle-checkbox').checked = true;
        getStubElement('motion-pattern-library-chat-checkbox').checked = true;

        getStubElement('save-motion-tab-btn').click();
        await flushAsyncHandlers();

        assert.deepStrictEqual(calls.map(call => call.endpoint), [
            '/set_motion_backend',
            '/set_motion_style',
            '/set_motion_reverse_direction',
            '/set_speed_limits',
            '/set_mode_timings',
            '/set_llm_edge_permissions',
            '/motion_feedback_options',
        ]);
        assert.strictEqual(getStubElement('status-text').textContent, 'Motion settings saved.');
    });

    it('setMotionPatternEnabled surfaces the backend message on pattern status', async () => {
        installBackendError('Pattern enablement failed.');

        await setMotionPatternEnabled('pulse', false);

        const status = getStubElement('motion-pattern-status');
        assert.strictEqual(status.textContent, 'Pattern enablement failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('setMotionPatternWeight surfaces the backend message on pattern status', async () => {
        installBackendError('Pattern weight failed.');

        await setMotionPatternWeight('pulse', 72);

        const status = getStubElement('motion-pattern-status');
        assert.strictEqual(status.textContent, 'Pattern weight failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('resetMotionPatternFeedback surfaces the backend message on pattern status', async () => {
        installBackendError('Pattern feedback reset failed.');

        await resetMotionPatternFeedback('pulse');

        const status = getStubElement('motion-pattern-status');
        assert.strictEqual(status.textContent, 'Pattern feedback reset failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('setMotionPatternTags sends tag lists and updates the global status', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                message: 'Updated tags for Pulse.',
                pattern: {id: 'pulse', name: 'Pulse', tags: ['tip', 'teasing']},
                motion_patterns: {
                    patterns: [{
                        id: 'pulse',
                        name: 'Pulse',
                        source: 'imported',
                        enabled: true,
                        duration_ms: 500,
                        action_count: 2,
                        tags: ['tip', 'teasing'],
                    }],
                    errors: [],
                },
            });
        };

        await setMotionPatternTags('pulse', 'tip, teasing');

        assert.deepStrictEqual(requests, [[
            '/motion_patterns/pulse/tags',
            {tags: ['tip', 'teasing']},
        ]]);
        assert.strictEqual(getStubElement('status-text').textContent, 'Updated tags for Pulse.');
    });

    it('pattern tag prompts show the suggested tag list', () => {
        const originalPrompt = globalThis.window.prompt;
        let promptMessage = '';
        let promptDefault = '';
        state.motionTagSuggestions = ['tip', 'full shaft', 'teasing'];
        globalThis.window.prompt = (message, current) => {
            promptMessage = message;
            promptDefault = current;
            return null;
        };

        try {
            const button = createPatternTagsButton({
                id: 'pulse',
                name: 'Pulse',
                source: 'imported',
                readonly: false,
                tags: ['teasing'],
            });
            button.click();
        } finally {
            globalThis.window.prompt = originalPrompt;
        }
        assert.match(promptMessage, /Suggestions: tip, full shaft, teasing/);
        assert.strictEqual(promptDefault, 'teasing');
    });

    it('saveMotionFeedbackOptions surfaces the backend message on pattern status', async () => {
        installBackendError('Feedback options failed.');

        getStubElement('motion-feedback-auto-disable-checkbox').checked = true;
        await saveMotionFeedbackOptions();

        const status = getStubElement('motion-pattern-status');
        assert.strictEqual(status.textContent, 'Feedback options failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('saveMotionFeedbackOptions sends pattern library toggles and mirrors saved state', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                motion_feedback_auto_disable: true,
                motion_pattern_library_enabled_in_freestyle: true,
                motion_pattern_library_enabled_in_chat: false,
                motion_preferences: {prompt: '', summary: ''},
            });
        };
        getStubElement('motion-feedback-auto-disable-checkbox').checked = true;
        getStubElement('motion-pattern-library-freestyle-checkbox').checked = true;
        getStubElement('motion-pattern-library-chat-checkbox').checked = false;

        await saveMotionFeedbackOptions();

        assert.deepStrictEqual(requests, [[
            '/motion_feedback_options',
            {
                auto_disable: true,
                motion_pattern_library_enabled_in_freestyle: true,
                motion_pattern_library_enabled_in_chat: false,
            },
        ]]);
        assert.strictEqual(state.motionFeedbackAutoDisable, true);
        assert.strictEqual(state.motionPatternLibraryEnabledInFreestyle, true);
        assert.strictEqual(state.motionPatternLibraryEnabledInChat, false);
        assert.strictEqual(getStubElement('motion-pattern-library-freestyle-checkbox').checked, true);
        assert.strictEqual(getStubElement('motion-pattern-library-chat-checkbox').checked, false);
        assert.strictEqual(getStubElement('status-text').textContent, 'Pattern library saved. Freestyle: on. Chat: off.');
    });

    it('resetMotionPreferences resets style controls and learned pattern feedback', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                message: 'Motion preferences reset.',
                motion_style: 'balanced',
                motion_style_options: [
                    {id: 'balanced', label: 'Balanced', description: 'Let the model choose a sensible mix.'},
                    {id: 'high_variation', label: 'High variation', description: 'Use more motion contrast.'},
                ],
                motion_patterns: {
                    patterns: [{
                        id: 'seed',
                        name: 'Seed',
                        source: 'fixed',
                        enabled: true,
                        duration_ms: 1000,
                        action_count: 2,
                        actions: [{ at: 0, pos: 30 }, { at: 1000, pos: 70 }],
                    }],
                    feedback_history: [],
                },
                motion_preferences: {weights: {}},
            });
        };
        state.motionStyle = 'high_variation';
        getStubElement('motion-style-select').value = 'high_variation';

        await resetMotionPreferences();

        assert.deepStrictEqual(requests, [['/motion_preferences/reset', {}]]);
        assert.strictEqual(state.motionStyle, 'balanced');
        assert.strictEqual(getStubElement('motion-style-select').value, 'balanced');
        assert.strictEqual(getStubElement('motion-style-status').textContent, 'Current style: Balanced. Let the model choose a sensible mix.');
        assert.strictEqual(getStubElement('motion-feedback-history').children.at(-1).textContent, 'No recent pattern feedback.');
        assert.strictEqual(getStubElement('status-text').textContent, 'Motion preferences reset.');
    });

    it('stopMotionTraining surfaces the backend message on global status', async () => {
        installBackendError('Training stop failed.');

        getStubElement('stop-motion-training-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Training stop failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('saveEditedMotionPattern surfaces the backend message on global status', async () => {
        installBackendError('Generated pattern was rejected.');
        state.motionTrainingOriginalPattern = {
            id: 'seed',
            name: 'Seed',
            duration_ms: 1000,
            actions: [{at: 0, pos: 20}, {at: 1000, pos: 80}],
        };
        state.motionTrainingEditedPattern = {
            id: 'seed',
            name: 'Seed',
            duration_ms: 1000,
            actions: [{at: 0, pos: 30}, {at: 1000, pos: 70}],
        };
        state.motionTrainingDirty = true;

        getStubElement('save-motion-training-pattern-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Generated pattern was rejected.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('play crop previews the current import crop without saving it first', async () => {
        let requestBody = null;
        globalThis.fetch = async (_url, options = {}) => {
            requestBody = JSON.parse(options.body);
            return jsonResponse(200, {
                status: 'started',
                motion_training: {
                    state: 'starting',
                    pattern_id: 'imported-wave 0.5-1.5s crop-preview',
                    pattern_name: 'Imported Wave 0.5-1.5s crop',
                    message: 'Crop preview started.',
                    preview: true,
                },
            });
        };
        state.motionStudioSourcePattern = {
            id: 'imported-wave',
            name: 'Imported Wave',
            actions: [
                { at: 0, pos: 0 },
                { at: 1000, pos: 100 },
                { at: 2000, pos: 0 },
            ],
        };
        state.motionStudioCropStartMs = 500;
        state.motionStudioCropEndMs = 1500;

        getStubElement('motion-studio-play-crop-btn').click();
        await flushAsyncHandlers();

        assert.strictEqual(requestBody.pattern.name, 'Imported Wave 0.5-1.5s crop');
        assert.deepStrictEqual(requestBody.pattern.actions.map(action => action.at), [0, 500, 1000]);
        assert.strictEqual(state.motionTraining.preview, true);
        assert.strictEqual(getStubElement('status-text').textContent, 'Crop preview started.');
        state.motionStudioSourcePattern = null;
        state.motionStudioCropStartMs = 0;
        state.motionStudioCropEndMs = 0;
    });

    it('likeLastMove surfaces the backend message on global status', async () => {
        installBackendError('Nothing active to like.');

        getStubElement('like-this-move-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Nothing active to like.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('mode start failures replace optimistic starting text', async () => {
        installBackendError('Edging is blocked until the device connects.');

        getStubElement('edging-mode-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Edging is blocked until the device connects.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('start auto uses the explicit mode route and updates active mode UI', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push([endpoint, options.method || 'GET']);
            if (endpoint === '/start_auto_mode') return jsonResponse(200, { status: 'auto_started' });
            return jsonResponse(404, { status: 'error', message: `Unexpected endpoint ${endpoint}` });
        };
        getStubElement('im-close-btn').style.display = 'block';

        getStubElement('start-auto-btn').click();
        await flushAsyncHandlers();

        assert.deepStrictEqual(calls, [['/start_auto_mode', 'POST']]);
        assert.strictEqual(getStubElement('status-text').textContent, 'Legacy Auto started.');
        assert.strictEqual(getStubElement('active-mode-status').hidden, false);
        assert.strictEqual(getStubElement('active-mode-label').textContent, 'Legacy Auto');
        assert.strictEqual(getStubElement('edging-timer').textContent, '00:00');
        assert.strictEqual(getStubElement('im-close-btn').style.display, 'none');
        assert.strictEqual(state.activeModeName, 'auto');
    });

    it('saveLlmEdgePermissions surfaces the backend message on the local status span', async () => {
        installBackendError('LLM edge permission write failed.');

        getStubElement('save-llm-edge-permissions-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('llm-edge-permissions-status');
        assert.strictEqual(status.textContent, 'LLM edge permission write failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
        assert.strictEqual(getStubElement('status-text').textContent, 'baseline');
    });

    it('saveLlmEdgePermissions includes typed-chat mode action permission', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                allow_llm_edge_in_freestyle: true,
                allow_llm_edge_in_chat: false,
                allow_llm_mode_actions_in_chat: true,
                autospeak_enabled: true,
                autospeak_min_seconds: 2,
                autospeak_max_seconds: 12,
                autospeak_motion_autonomy: 'full',
                autospeak_motion_autonomy_options: [
                    {id: 'chat_only', label: 'Talk only', description: 'Only speak.'},
                    {id: 'style', label: 'Style only', description: 'May change style.'},
                    {id: 'full', label: 'Full motion', description: 'May change motion.'},
                ],
                motion_preferences: {prompt: '', summary: ''},
            });
        };
        populateMotionSettings({
            autospeak_enabled: true,
            autospeak_min_seconds: 2,
            autospeak_max_seconds: 12,
            autospeak_motion_autonomy: 'style',
            autospeak_motion_autonomy_options: [
                {id: 'chat_only', label: 'Talk only', description: 'Only speak.'},
                {id: 'style', label: 'Style only', description: 'May change style.'},
                {id: 'full', label: 'Full motion', description: 'May change motion.'},
            ],
        });
        getStubElement('allow-llm-edge-freestyle-checkbox').checked = true;
        getStubElement('allow-llm-edge-chat-checkbox').checked = false;
        getStubElement('allow-llm-mode-actions-chat-checkbox').checked = true;
        getStubElement('autospeak-min-seconds').value = '12';
        getStubElement('autospeak-max-seconds').value = '2';
        getStubElement('autospeak-motion-autonomy-select').value = 'full';

        getStubElement('save-llm-edge-permissions-btn').click();
        await flushAsyncHandlers();

        assert.deepStrictEqual(requests, [[
            '/set_llm_edge_permissions',
            {
                allow_llm_edge_in_freestyle: true,
                allow_llm_edge_in_chat: false,
                allow_llm_mode_actions_in_chat: true,
                autospeak_enabled: true,
                autospeak_min_seconds: 2,
                autospeak_max_seconds: 12,
                autospeak_motion_autonomy: 'full',
            },
        ]]);
        assert.strictEqual(state.allowLlmModeActionsInChat, true);
        assert.strictEqual(state.autospeakEnabled, true);
        assert.strictEqual(state.autospeakMinSeconds, 2);
        assert.strictEqual(state.autospeakMaxSeconds, 12);
        assert.strictEqual(state.autospeakMotionAutonomy, 'full');
        assert.strictEqual(Number(getStubElement('autospeak-min-seconds').value), 2);
        assert.strictEqual(Number(getStubElement('autospeak-max-seconds').value), 12);
        assert.strictEqual(getStubElement('autospeak-motion-autonomy-select').value, 'full');
        assert.strictEqual(getStubElement('llm-edge-permissions-status').textContent, 'LLM permissions saved.');
    });

    it('top-bar Autospeak toggle saves only Autospeak and mirrors the pressed state', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                allow_llm_edge_in_freestyle: true,
                allow_llm_edge_in_chat: true,
                allow_llm_mode_actions_in_chat: false,
                autospeak_enabled: true,
                autospeak_min_seconds: 3,
                autospeak_max_seconds: 30,
                motion_preferences: {prompt: '', summary: ''},
            });
        };
        populateMotionSettings({autospeak_enabled: false, autospeak_min_seconds: 3, autospeak_max_seconds: 30});

        getStubElement('top-bar-autospeak-toggle-btn').click();
        await flushAsyncHandlers();

        assert.deepStrictEqual(requests, [['/set_llm_edge_permissions', {autospeak_enabled: true}]]);
        assert.strictEqual(state.autospeakEnabled, true);
        assert.strictEqual(getStubElement('top-bar-autospeak-toggle-btn').textContent, 'Auto On');
        assert.strictEqual(getStubElement('top-bar-autospeak-toggle-btn').getAttribute('aria-pressed'), 'true');
        assert.strictEqual(getStubElement('top-bar-autospeak-toggle-btn').classList.contains('is-on'), true);
        assert.strictEqual(getStubElement('status-text').textContent, 'Autospeak enabled.');
    });

    it('toggleMotionPause surfaces the backend message on global status', async () => {
        installBackendError('Pause request failed.');

        getStubElement('pause-resume-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Pause request failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('signalImClose surfaces the backend message on global status', async () => {
        installBackendError('Close signal failed.');
        state.activeModeName = 'edging';

        getStubElement('im-close-btn').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'Close signal failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('downloadLocalTtsModel surfaces the preload backend message on local status', async () => {
        installFetchQueue([
            jsonResponse(200, {status: 'ok', local_tts_status: {message: 'Local voice settings saved.'}}),
            jsonResponse(200, {status: 'error', message: 'Model preload failed.', local_tts_status: {message: 'Idle.'}}),
        ]);

        getStubElement('download-local-tts-model-button').click();
        await flushAsyncHandlers();

        const status = getStubElement('local-tts-status');
        assert.strictEqual(status.textContent, 'Model preload failed.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });

    it('updateLocalTtsStatus shows live preload percentage while loading', () => {
        updateLocalTtsStatus({
            status: 'success',
            available: true,
            message: 'Local voice model download/load is running.',
            preload_status: 'loading',
            preload_progress_percent: 42,
            preload_elapsed_seconds: 8,
            generation_status: 'idle',
        });

        const status = getStubElement('local-tts-status');
        const button = getStubElement('download-local-tts-model-button');
        assert.match(status.textContent, /Progress: 42%\./);
        assert.match(status.textContent, /Elapsed: 8s\./);
        assert.strictEqual(button.textContent, 'Downloading / Loading 42%...');
    });

    it('setupElevenLabsKey surfaces the backend message on global status', async () => {
        installBackendError('ElevenLabs key is invalid.');

        getStubElement('elevenlabs-key-input').value = 'sk-test';
        getStubElement('set-elevenlabs-key-button').click();
        await flushAsyncHandlers();

        const status = getStubElement('status-text');
        assert.strictEqual(status.textContent, 'ElevenLabs key is invalid.');
        assert.strictEqual(status.style.color, 'var(--yellow)');
    });
});
