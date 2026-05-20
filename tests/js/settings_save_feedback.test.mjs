// Behavioral test for the settings-write feedback contract.
//
// Spec: KNOWN_PROBLEMS "Web UI Stays Functional After Backend Shutdown"
// (Partial). The connection-lost banner closed the network-failure half;
// this test pins the backend-reachable-but-rejected half. Two surfaces:
//
// 1. ``apiCall`` on HTTP 4xx/5xx: the route handlers in this app return
//    a JSON body with a useful ``message`` field even on 400. ``apiCall``
//    must surface that message in the global statusText instead of the
//    generic "Error: server returned 400." -- otherwise the user sees a
//    save fail with no detail about WHY. HTTP failures use the global
//    error tone because the backend was reachable but the request failed
//    at the transport/status layer.
//
// 2. ``reportSaveFailure`` for the 200-with-error case: some routes
//    (audio enable/disable, ``/pull_ollama_model``) return HTTP 200 with
//    ``{"status": "error" | "started", "message": "..."}``. The success
//    branch in the caller does not fire; the save handler must surface
//    the server message inline on a per-write status element with a
//    warning tone.

import { describe, it, before, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { initSettingsControls, populateLongTermMemorySetting, populateModelOptions, setPersonaPrompt, updateOllamaStatus } from '../../static/js/settings.js';
import { state, reportSaveFailure, apiCall, setStatusMessage } from '../../static/js/context.js';


// Build a fetch-shaped mock that supports the small surface apiCall uses
// (`ok`, `status`, `headers.get`, `.json()`, `.clone().json()`, `.blob()`).
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


describe('settings-write feedback (KNOWN_PROBLEMS Web UI Partial)', () => {
    let originalFetch;
    let originalConfirm;

    before(() => {
        initSettingsControls({ addChatMessage: () => {} });
    });

    beforeEach(() => {
        // Reset state and the status element each test sees.
        resetStubElement('status-text');
        resetStubElement('ollama-model-list');
        resetStubElement('ollama-model-select');
        resetStubElement('ollama-model-input');
        resetStubElement('ollama-model-status');
        resetStubElement('ollama-thinking-enabled-checkbox');
        resetStubElement('save-ollama-thinking-btn');
        resetStubElement('ollama-thinking-status');
        resetStubElement('toggle-memory-btn');
        resetStubElement('long-term-memory-checkbox');
        resetStubElement('clear-long-term-memory-btn');
        resetStubElement('long-term-memory-status');
        resetStubElement('long-term-memory-preview');
        resetStubElement('ollama-model-required-dialog');
        resetStubElement('close-ollama-model-required-btn');
        resetStubElement('ollama-model-required-message');
        resetStubElement('ollama-model-required-select');
        resetStubElement('use-available-ollama-model-btn');
        resetStubElement('download-required-ollama-model-btn');
        resetStubElement('open-model-settings-btn');
        resetStubElement('ollama-model-required-status');
        resetStubElement('settings-dialog');
        resetStubElement('setup-overlay');
        const statusText = getStubElement('status-text');
        statusText.textContent = 'baseline';
        state.connectionLost = false;
        state.myPersonaDescription = '';
        state.ollamaModels = [];
        state.ollamaCurrentModel = '';
        state.ollamaThinkingEnabled = false;
        state.useLongTermMemory = true;
        state.longTermMemoryStatus = {};
        state.ollamaModelDetails = {};
        state.ollamaModelPromptDismissedKey = '';

        originalFetch = globalThis.fetch;
        originalConfirm = globalThis.window.confirm;
        globalThis.window.confirm = () => true;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        globalThis.window.confirm = originalConfirm;
    });

    function installFetchResult(response) {
        globalThis.fetch = async () => {
            if (response instanceof Error) throw response;
            return response;
        };
    }

    async function flushAsyncClickHandlers() {
        await Promise.resolve();
        await Promise.resolve();
        await new Promise(resolve => setTimeout(resolve, 0));
    }

    // ---- reportSaveFailure unit tests ----

    it('setStatusMessage applies explicit tones without inventing copy', () => {
        const target = getStubElement('status-text');
        setStatusMessage(target, 'Server is offline.', 'error');
        assert.strictEqual(target.textContent, 'Server is offline.');
        assert.strictEqual(target.dataset.statusTone, 'error');
        assert.strictEqual(target.style.color, 'var(--red)');

        setStatusMessage(target, 'Saved.', 'success');
        assert.strictEqual(target.dataset.statusTone, 'success');
        assert.strictEqual(target.style.color, 'var(--cyan)');
    });

    it('reportSaveFailure stays silent on success', () => {
        const target = getStubElement('status-text');
        target.textContent = 'baseline';
        target.style.color = 'unset';
        reportSaveFailure(target, { status: 'success' }, 'fallback');
        assert.strictEqual(target.textContent, 'baseline');
        assert.strictEqual(target.style.color, 'unset');
    });

    it('reportSaveFailure stays silent when data is undefined (apiCall already handled it)', () => {
        const target = getStubElement('status-text');
        target.textContent = 'baseline';
        target.style.color = 'unset';
        reportSaveFailure(target, undefined, 'fallback');
        // apiCall already wrote a useful message to the global statusText
        // for the network/HTTP-error case. The helper must not overwrite a
        // local status with a duplicate or generic line; it leaves the
        // local element alone unless the caller has a server-side body to
        // surface (the 200-with-status:'error' case).
        assert.strictEqual(target.textContent, 'baseline');
        assert.strictEqual(target.style.color, 'unset');
    });

    it('reportSaveFailure surfaces the server message when backend rejects with 200-status:error', () => {
        const target = getStubElement('status-text');
        target.textContent = 'baseline';
        reportSaveFailure(
            target,
            { status: 'error', message: 'persona name is too long' },
            'fallback should not be used when server provided one',
        );
        assert.strictEqual(target.textContent, 'persona name is too long');
        assert.strictEqual(target.dataset.statusTone, 'warning');
        assert.strictEqual(target.style.color, 'var(--yellow)');
    });

    it('reportSaveFailure falls back when server omits a message', () => {
        const target = getStubElement('status-text');
        target.textContent = 'baseline';
        reportSaveFailure(target, { status: 'error' }, 'Persona save failed.');
        assert.strictEqual(target.textContent, 'Persona save failed.');
        assert.strictEqual(target.style.color, 'var(--yellow)');
    });

    it('reportSaveFailure tolerates a missing status element', () => {
        // Helper must not throw when the status target is absent (defensive).
        reportSaveFailure(null, { status: 'error', message: 'oops' }, 'fallback');
        reportSaveFailure(undefined, { status: 'error', message: 'oops' }, 'fallback');
    });

    // ---- apiCall HTTP-error message surfacing ----

    it('apiCall surfaces the server message on HTTP 400 instead of the generic line', async () => {
        installFetchResult(jsonResponse(400, {
            status: 'error',
            message: 'Persona prompt is required.',
        }));

        const result = await apiCall('/set_persona_prompt', { method: 'POST' });
        const statusText = getStubElement('status-text');

        assert.strictEqual(result, undefined, 'apiCall returns undefined on HTTP error');
        assert.strictEqual(
            statusText.textContent,
            'Persona prompt is required.',
            'apiCall must surface the server message instead of "Error: server returned 400."',
        );
        assert.strictEqual(statusText.dataset.statusTone, 'error');
        assert.strictEqual(statusText.style.color, 'var(--red)');
    });

    it('apiCall falls back to the generic line when the body has no message', async () => {
        installFetchResult(jsonResponse(500, { status: 'error' }));

        await apiCall('/set_persona_prompt', { method: 'POST' });
        const statusText = getStubElement('status-text');

        assert.strictEqual(statusText.textContent, 'Error: server returned 500.');
        assert.strictEqual(statusText.dataset.statusTone, 'error');
        assert.strictEqual(statusText.style.color, 'var(--red)');
    });

    it('apiCall falls back to the generic line when the body is not JSON', async () => {
        // A response that throws on .json() simulates an HTML error page.
        installFetchResult({
            ok: false,
            status: 502,
            headers: { get: () => 'text/html' },
            async json() { throw new Error('Unexpected token <'); },
            clone() { return this; },
        });

        await apiCall('/set_persona_prompt', { method: 'POST' });
        const statusText = getStubElement('status-text');

        assert.strictEqual(statusText.textContent, 'Error: server returned 502.');
        assert.strictEqual(statusText.dataset.statusTone, 'error');
        assert.strictEqual(statusText.style.color, 'var(--red)');
    });

    // ---- end-to-end via setPersonaPrompt ----

    it('setPersonaPrompt: backend success seeds persona state and leaves color unset', async () => {
        installFetchResult(jsonResponse(200, {
            status: 'success',
            persona: 'Friendly co-pilot',
            persona_prompts: ['Friendly co-pilot'],
        }));

        const result = await setPersonaPrompt('Friendly co-pilot', false);
        const statusText = getStubElement('status-text');

        assert.ok(result, 'setPersonaPrompt returned a payload');
        assert.strictEqual(result.status, 'success');
        assert.strictEqual(state.myPersonaDescription, 'Friendly co-pilot');
        assert.notStrictEqual(
            statusText.style.color,
            'var(--yellow)',
            'a successful save must not paint statusText with the failure color',
        );
    });

    it('setPersonaPrompt: HTTP 400 surfaces the server message via apiCall', async () => {
        installFetchResult(jsonResponse(400, {
            status: 'error',
            message: 'Persona prompt is required.',
        }));

        await setPersonaPrompt('after normalize this becomes empty', false);
        const statusText = getStubElement('status-text');

        // apiCall already wrote the server message; the helper saw
        // data === undefined and stayed silent so the statusText kept the
        // useful detail.
        assert.strictEqual(statusText.textContent, 'Persona prompt is required.');
    });

    it('setPersonaPrompt: empty input never reaches fetch', async () => {
        let fetchCalled = false;
        globalThis.fetch = async () => {
            fetchCalled = true;
            return jsonResponse(200, { status: 'success' });
        };
        const result = await setPersonaPrompt('   ', false);
        assert.strictEqual(result, null, 'empty input short-circuits before the fetch');
        assert.strictEqual(fetchCalled, false, 'fetch was not called');
    });

    it('saveDiagnosticsLevels: backend 200-status:error surfaces the failure message', async () => {
        installFetchResult(jsonResponse(200, {
            status: 'error',
            message: 'Diagnostics level is invalid.',
        }));

        getStubElement('motion-diagnostics-level-select').value = 'debug';
        getStubElement('ollama-diagnostics-level-select').value = 'status';
        getStubElement('save-motion-diagnostics-level-btn').click();
        await flushAsyncClickHandlers();

        const statusText = getStubElement('status-text');
        assert.strictEqual(statusText.textContent, 'Diagnostics level is invalid.');
        assert.strictEqual(statusText.style.color, 'var(--yellow)');
    });

    it('setOllamaModel: backend 200-status:error surfaces the model-specific failure message', async () => {
        installFetchResult(jsonResponse(200, {
            status: 'error',
            message: 'Model name is not available.',
        }));

        const modelStatus = resetStubElement('ollama-model-status');
        getStubElement('ollama-model-input').value = 'local/test-model:latest';
        getStubElement('save-ollama-model-btn').click();
        await flushAsyncClickHandlers();

        assert.strictEqual(modelStatus.textContent, 'Model name is not available.');
        assert.strictEqual(modelStatus.style.color, 'var(--yellow)');
    });

    it('setOllamaThinking: saves the selected thinking preference', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                ollama_thinking_enabled: true,
                ollama_status: {
                    available: true,
                    current_model: 'current/model:latest',
                    current_model_installed: true,
                    thinking_enabled: true,
                    download: {},
                    gpu_status: {},
                    message: 'Current model is installed: current/model:latest',
                },
            });
        };

        const checkbox = getStubElement('ollama-thinking-enabled-checkbox');
        const status = getStubElement('ollama-thinking-status');
        checkbox.checked = true;
        getStubElement('save-ollama-thinking-btn').click();
        await flushAsyncClickHandlers();

        assert.deepStrictEqual(requests[0], ['/set_ollama_thinking', { enabled: true }]);
        assert.strictEqual(state.ollamaThinkingEnabled, true);
        assert.match(status.textContent, /Saved\. Thinking is on/);
    });

    it('populateLongTermMemorySetting renders persistent memory status and preview', () => {
        const sidebarToggle = getStubElement('toggle-memory-btn');
        const checkbox = getStubElement('long-term-memory-checkbox');
        const status = getStubElement('long-term-memory-status');
        const preview = getStubElement('long-term-memory-preview');

        populateLongTermMemorySetting({
            enabled: false,
            persistent: true,
            has_memory: true,
            profile: {
                name: 'Tester',
                likes: ['smooth motion'],
                dislikes: [],
                key_memories: ['prefers quiet narration'],
            },
            summary: 'name: Tester, 1 like(s), 1 key memory item(s)',
        }, true);

        assert.strictEqual(state.useLongTermMemory, false);
        assert.strictEqual(sidebarToggle.textContent, 'Memories: OFF');
        assert.strictEqual(sidebarToggle.getAttribute('aria-pressed'), 'false');
        assert.strictEqual(checkbox.checked, false);
        assert.match(status.textContent, /Disabled; name: Tester/);
        assert.strictEqual(status.style.color, 'var(--yellow)');
        assert.match(preview.textContent, /"name": "Tester"/);
        assert.match(preview.textContent, /"smooth motion"/);
    });

    it('long-term memory checkbox saves an explicit enabled value', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                use_long_term_memory: false,
                memory_status: {
                    enabled: false,
                    persistent: true,
                    has_memory: false,
                    profile: {},
                    summary: 'No saved long-term memories yet.',
                },
            });
        };

        const checkbox = getStubElement('long-term-memory-checkbox');
        checkbox.checked = false;
        checkbox.dispatchEvent('change', {target: checkbox});
        await flushAsyncClickHandlers();

        assert.deepStrictEqual(requests[0], ['/toggle_memory', {enabled: false}]);
        assert.strictEqual(state.useLongTermMemory, false);
        assert.match(getStubElement('long-term-memory-status').textContent, /Disabled; No saved/);
        assert.strictEqual(getStubElement('long-term-memory-preview').textContent, 'No saved long-term memories.');
    });

    it('clear memories button confirms and clears saved memory context', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, options.method || 'GET']);
            return jsonResponse(200, {
                status: 'success',
                use_long_term_memory: true,
                chat_history_cleared: true,
                memory_status: {
                    enabled: true,
                    persistent: true,
                    has_memory: false,
                    profile: {},
                    summary: 'No saved long-term memories yet.',
                },
            });
        };

        getStubElement('clear-long-term-memory-btn').click();
        await flushAsyncClickHandlers();

        assert.deepStrictEqual(requests[0], ['/clear_memory', 'POST']);
        assert.strictEqual(state.useLongTermMemory, true);
        assert.match(getStubElement('long-term-memory-status').textContent, /Enabled; No saved/);
        assert.strictEqual(getStubElement('long-term-memory-preview').textContent, 'No saved long-term memories.');
        assert.strictEqual(getStubElement('status-text').textContent, 'Long-term memories cleared.');
    });

    it('populateModelOptions renders model row actions and posts delete/download requests', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                ollama_model: 'current/model:latest',
                ollama_models: ['current/model:latest', 'custom/model:tag'],
                ollama_status: {
                    available: true,
                    current_model: 'current/model:latest',
                    current_model_installed: true,
                    installed_model_names: ['current/model:latest'],
                    download: {},
                    model_details: {
                        'current/model:latest': {
                            name: 'current/model:latest',
                            size_label: '4.0 GB',
                            installed: true,
                        },
                        'custom/model:tag': {
                            name: 'custom/model:tag',
                            size_label: '2.0 GB',
                            installed: false,
                        },
                    },
                    gpu_status: {},
                    message: 'Current model is installed: current/model:latest',
                },
            });
        };

        populateModelOptions(
            ['current/model:latest', 'custom/model:tag'],
            'current/model:latest',
            {
                model_details: {
                    'current/model:latest': {
                        name: 'current/model:latest',
                        size_label: '4.0 GB',
                        installed: true,
                        warning: 'The selected model is too large for the current hardware.',
                    },
                    'custom/model:tag': {
                        name: 'custom/model:tag',
                        size_label: '2.0 GB',
                        installed: false,
                    },
                },
            },
        );

        const list = getStubElement('ollama-model-list');
        const select = getStubElement('ollama-model-select');
        assert.strictEqual(list.children.length, 2);
        assert.strictEqual(select.children[1].textContent, 'custom/model:tag (2.0 GB)');
        assert.match(list.children[0].children[2].textContent, /too large/);
        assert.strictEqual(list.children[1].children[1].textContent, '2.0 GB - Not installed');
        const currentActions = list.children[0].children[3];
        const customActions = list.children[1].children[2];
        assert.strictEqual(currentActions.children.length, 2);
        assert.strictEqual(currentActions.children[0].className, 'ollama-model-action-spacer');
        assert.strictEqual(currentActions.children[1].disabled, true);
        assert.strictEqual(customActions.children.length, 2);
        assert.strictEqual(customActions.children[0].disabled, false);
        assert.match(customActions.children[0].innerHTML, /<svg/);
        assert.match(customActions.children[1].innerHTML, /<svg/);

        customActions.children[0].click();
        await flushAsyncClickHandlers();

        customActions.children[1].click();
        await flushAsyncClickHandlers();

        assert.deepStrictEqual(requests, [[
            '/pull_ollama_model',
            { model: 'custom/model:tag' },
        ], [
            '/delete_ollama_model',
            { model: 'custom/model:tag' },
        ]]);
    });

    it('updateOllamaStatus surfaces confirmed CPU-only model load as a warning', () => {
        const modelStatus = resetStubElement('ollama-model-status');
        const diagnostics = resetStubElement('ollama-diagnostics-output');
        getStubElement('ollama-diagnostics-level-select').value = 'status';

        updateOllamaStatus({
            available: true,
            current_model: 'local/test-model:latest',
            current_model_installed: true,
            installed_model_names: ['local/test-model:latest'],
            download: {},
            diagnostics_level: 'status',
            llm_diagnostics: {},
            message: 'Current model is installed: local/test-model:latest',
            gpu_status: {
                state: 'cpu',
                accelerated: false,
                message: 'Ollama reports the selected model is CPU-only right now.',
                warning: 'Ollama reports the selected model is running in system memory only.',
                current_model_size_label: '4.0 GB',
                current_model_size_vram_label: '',
            },
        });

        assert.match(modelStatus.textContent, /system memory only/);
        assert.strictEqual(modelStatus.style.color, 'var(--yellow)');
        assert.match(diagnostics.textContent, /GPU: Ollama reports the selected model is CPU-only/);
        assert.match(diagnostics.textContent, /GPU warning: Ollama reports the selected model is running in system memory only/);
    });

    it('updateOllamaStatus shows model download percentage while pulling', () => {
        const modelStatus = resetStubElement('ollama-model-status');
        const downloadButton = resetStubElement('download-ollama-model-btn');

        updateOllamaStatus({
            available: true,
            current_model: 'local/test-model:latest',
            current_model_installed: false,
            installed_model_names: [],
            download: {
                state: 'downloading',
                model: 'local/test-model:latest',
                message: 'pulling layer (1.0 GB / 2.0 GB, 50%)',
                percent: 50,
            },
            diagnostics_level: 'compact',
            llm_diagnostics: {},
            model_details: {},
            message: 'Current model is not installed.',
            gpu_status: {},
        });

        assert.match(modelStatus.textContent, /Progress: 50%\./);
        assert.match(modelStatus.textContent, /pulling layer/);
        assert.strictEqual(downloadButton.textContent, 'Downloading 50%...');
        assert.strictEqual(downloadButton.disabled, true);
        assert.match(state.chatModelBlockedMessage, /50%/);
    });

    it('updateOllamaStatus opens a model chooser when an installed alternate exists', async () => {
        const requests = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            requests.push([endpoint, JSON.parse(options.body || '{}')]);
            return jsonResponse(200, {
                status: 'success',
                ollama_model: 'installed/model:tag',
                ollama_models: ['preferred/model:tag', 'installed/model:tag'],
                ollama_status: {
                    available: true,
                    current_model: 'installed/model:tag',
                    current_model_installed: true,
                    installed_model_names: ['installed/model:tag'],
                    installed_model_candidates: ['installed/model:tag'],
                    model_selection_required: false,
                    suggested_model: '',
                    download: {},
                    diagnostics_level: 'compact',
                    llm_diagnostics: {},
                    model_details: {
                        'installed/model:tag': {
                            name: 'installed/model:tag',
                            installed: true,
                            size_label: '3.0 GB',
                        },
                        'preferred/model:tag': {
                            name: 'preferred/model:tag',
                            installed: false,
                            size_label: '5.0 GB',
                        },
                    },
                    gpu_status: {},
                    message: 'Current model is installed: installed/model:tag',
                },
            });
        };

        populateModelOptions(
            ['preferred/model:tag', 'installed/model:tag'],
            'preferred/model:tag',
            {
                model_details: {
                    'preferred/model:tag': {
                        name: 'preferred/model:tag',
                        installed: false,
                        size_label: '5.0 GB',
                    },
                    'installed/model:tag': {
                        name: 'installed/model:tag',
                        installed: true,
                        size_label: '3.0 GB',
                    },
                },
            },
        );

        updateOllamaStatus({
            available: true,
            current_model: 'preferred/model:tag',
            current_model_installed: false,
            model_selection_required: true,
            installed_model_names: ['installed/model:tag'],
            installed_model_candidates: ['installed/model:tag'],
            suggested_model: 'installed/model:tag',
            download: {},
            diagnostics_level: 'compact',
            llm_diagnostics: {},
            model_details: {
                'preferred/model:tag': {
                    name: 'preferred/model:tag',
                    installed: false,
                    size_label: '5.0 GB',
                },
                'installed/model:tag': {
                    name: 'installed/model:tag',
                    installed: true,
                    size_label: '3.0 GB',
                },
            },
            gpu_status: {},
            message: 'Selected model is not installed: preferred/model:tag. Installed model available: installed/model:tag.',
        });

        const dialog = getStubElement('ollama-model-required-dialog');
        const message = getStubElement('ollama-model-required-message');
        const select = getStubElement('ollama-model-required-select');
        const useButton = getStubElement('use-available-ollama-model-btn');
        const downloadButton = getStubElement('download-required-ollama-model-btn');

        assert.strictEqual(dialog.classList.contains('open'), true);
        assert.match(message.textContent, /preferred\/model:tag/);
        assert.match(message.textContent, /installed\/model:tag/);
        assert.strictEqual(select.value, 'installed/model:tag');
        assert.strictEqual(select.children[0].textContent, 'installed/model:tag (installed)');
        assert.strictEqual(useButton.disabled, false);
        assert.strictEqual(downloadButton.disabled, true);
        assert.match(state.chatModelBlockedMessage, /Settings > Model/);

        select.value = 'preferred/model:tag';
        select.dispatchEvent('change');
        assert.strictEqual(useButton.disabled, true);
        assert.strictEqual(downloadButton.disabled, false);

        select.value = 'installed/model:tag';
        select.dispatchEvent('change');
        useButton.click();
        await flushAsyncClickHandlers();

        assert.deepStrictEqual(requests, [[
            '/set_ollama_model',
            { model: 'installed/model:tag' },
        ]]);
        assert.strictEqual(dialog.classList.contains('open'), false);
        assert.strictEqual(state.chatModelBlockedMessage, '');
    });

    it('updateOllamaStatus treats startup unchecked status as non-blocking', () => {
        const modelStatus = resetStubElement('ollama-model-status');
        const input = resetStubElement('user-chat-input');
        const send = resetStubElement('send-chat-btn');
        const modelList = resetStubElement('ollama-model-list');
        state.chatModelBlockedMessage = 'previous block';
        state.ollamaModels = ['local/test-model:latest'];
        state.ollamaCurrentModel = 'local/test-model:latest';

        updateOllamaStatus({
            unchecked: true,
            available: null,
            current_model: 'local/test-model:latest',
            current_model_installed: null,
            installed_model_names: [],
            download: {},
            diagnostics_level: 'compact',
            llm_diagnostics: {},
            model_details: {
                'local/test-model:latest': {
                    name: 'local/test-model:latest',
                    size_label: '4.0 GB',
                    unchecked: true,
                },
            },
            message: 'Checking Ollama model status...',
            gpu_status: {
                state: 'unchecked',
                message: 'Ollama GPU status will refresh after startup.',
            },
        });

        assert.strictEqual(state.chatModelBlockedMessage, '');
        assert.strictEqual(input.disabled, false);
        assert.strictEqual(send.disabled, false);
        assert.strictEqual(modelStatus.textContent, 'Checking Ollama model status...');
        assert.strictEqual(modelStatus.style.color, 'var(--comment)');
        assert.strictEqual(modelList.children[0].children[1].textContent, '4.0 GB - Checking');
        assert.match(modelList.children[0].children[2].children[0].className, /ollama-model-action-spacer/);
    });
});
