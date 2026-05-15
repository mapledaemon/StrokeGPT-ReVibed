import { D, apiCall, el, formatPercent, reportSaveFailure, setStatusMessage, state } from './context.js';
import { updateAudioProviderUi } from './audio.js';
import { refreshSystemStatus } from './setup-check.js';

export function setSettingsTab(tabName) {
    el.settingsTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.settingsTab === tabName));
    el.settingsPanels.forEach(panel => panel.classList.toggle('active', panel.id === `settings-tab-${tabName}`));
    if (tabName === 'prompts' && !state.systemPromptsLoadedOnce) {
        refreshSystemPrompts();
    }
    if (tabName === 'diagnostics' && !state.systemStatusText) {
        refreshSystemStatus();
    }
}

export async function refreshSystemPrompts() {
    if (el.systemPromptsStatus) el.systemPromptsStatus.textContent = 'Loading...';
    const data = await apiCall('/system_prompts');
    if (!data) {
        if (el.systemPromptsStatus) el.systemPromptsStatus.textContent = 'Could not load system prompts.';
        return;
    }
    populatePromptModeSetting(data.llm_prompt_mode, data.llm_prompt_mode_options);
    if (el.systemPromptChat) el.systemPromptChat.textContent = data.chat || '';
    if (el.systemPromptRepair) el.systemPromptRepair.textContent = data.repair || '';
    if (el.systemPromptNameThisMove) el.systemPromptNameThisMove.textContent = data.name_this_move || '';
    if (el.systemPromptProfileConsolidation) el.systemPromptProfileConsolidation.textContent = data.profile_consolidation || '';
    if (el.systemPromptNameThisMoveSample) {
        const sample = data.name_this_move_sample_inputs || {};
        const speed = sample.speed ?? 0;
        const depth = sample.depth ?? 0;
        const mood = sample.mood || '';
        el.systemPromptNameThisMoveSample.textContent = `(sample inputs: speed ${speed}%, depth ${depth}%, mood '${mood}')`;
    }
    state.systemPromptsLoadedOnce = true;
    if (el.systemPromptsStatus) el.systemPromptsStatus.textContent = `Loaded at ${new Date().toLocaleTimeString()}.`;
}

function promptModeStatusText(mode) {
    return mode === 'legacy'
        ? 'Legacy prompt style selected.'
        : 'ReVibed prompt style selected.';
}

export function populatePromptModeSetting(mode = 'revibed', options = []) {
    const normalizedMode = mode || 'revibed';
    const normalizedOptions = Array.isArray(options) && options.length
        ? options
        : [
            {id: 'revibed', label: 'ReVibed', description: 'Less clinical default voice with the same motion-control contract.'},
            {id: 'legacy', label: 'Legacy', description: 'Previous technical prompt shape for comparison or fallback.'},
        ];
    state.llmPromptMode = normalizedMode;
    state.llmPromptModeOptions = normalizedOptions;
    if (el.llmPromptModeSelect) {
        el.llmPromptModeSelect.innerHTML = '';
        normalizedOptions.forEach(option => {
            const item = D.createElement('option');
            item.value = option.id;
            item.textContent = option.label || option.id;
            if (option.description) item.title = option.description;
            el.llmPromptModeSelect.appendChild(item);
        });
        el.llmPromptModeSelect.value = normalizedMode;
    }
    if (el.llmPromptModeStatus) {
        const current = normalizedOptions.find(option => option.id === normalizedMode) || {};
        el.llmPromptModeStatus.textContent = current.description || promptModeStatusText(normalizedMode);
        el.llmPromptModeStatus.style.color = 'var(--comment)';
    }
}

function setProfileMenuOpen(isOpen) {
    if (!el.profileMenuBtn || !el.profileMenuPopover) return;
    el.profileMenuBtn.setAttribute('aria-expanded', String(isOpen));
    el.profileMenuPopover.hidden = !isOpen;
}

function closeProfileMenu() {
    setProfileMenuOpen(false);
}

function closeAboutDialog() {
    if (el.aboutDialog) el.aboutDialog.classList.remove('open');
}

function openAboutDialog() {
    closeProfileMenu();
    if (el.settingsDialog) el.settingsDialog.classList.remove('open');
    if (el.aboutDialog) el.aboutDialog.classList.add('open');
    el.closeAboutBtn?.focus?.();
}

function profileMenuContains(target) {
    let node = target;
    while (node) {
        if (node === el.profileMenu) return true;
        node = node.parentNode;
    }
    return false;
}

export function openSettings(tabName = 'voice') {
    closeProfileMenu();
    setSettingsTab(tabName);
    updateAudioProviderUi();
    el.settingsDialog.classList.add('open');
}

export function normalizeModelName(model) {
    return (model || '').trim().replace(/\s*\/\s*/g, '/').replace(/\s*:\s*/g, ':');
}

function modelDetailsFromStatus(status = {}) {
    const raw = status.model_details || {};
    const details = {};
    if (Array.isArray(raw)) {
        raw.forEach(item => {
            const name = normalizeModelName(item && item.name);
            if (name) details[name] = item;
        });
        return details;
    }
    Object.entries(raw).forEach(([name, item]) => {
        const normalized = normalizeModelName((item && item.name) || name);
        if (normalized) details[normalized] = item || {};
    });
    return details;
}

function modelDetailFor(model) {
    return state.ollamaModelDetails[normalizeModelName(model)] || {};
}

function modelOptionLabel(model) {
    const detail = modelDetailFor(model);
    return detail.size_label ? `${model} (${detail.size_label})` : model;
}

function modelSizeLabel(detail = {}) {
    return detail.size_label || 'Size unknown';
}

function modelStateLabel(detail = {}) {
    if (detail.unchecked) return 'Checking';
    if (detail.running && detail.size_vram_label) return `${detail.size_vram_label} VRAM`;
    if (detail.running) return 'Running';
    if (detail.installed) return 'Installed';
    return 'Not installed';
}

function modelMetaLabel(detail = {}) {
    return `${modelSizeLabel(detail)} - ${modelStateLabel(detail)}`;
}

function modelNeedsDownload(detail = {}) {
    if (detail.unchecked) return false;
    return !detail.installed;
}

function modelsMatch(left, right) {
    left = normalizeModelName(left);
    right = normalizeModelName(right);
    return left === right || `${left}:latest` === right || left === `${right}:latest`;
}

function installedModelNamesFromStatus(status = {}) {
    const names = [];
    const add = model => {
        const normalized = normalizeModelName(model);
        if (normalized && !names.some(item => modelsMatch(item, normalized))) names.push(normalized);
    };
    (status.installed_model_names || []).forEach(add);
    Object.values(status.model_details || {}).forEach(detail => {
        if (detail && detail.installed) add(detail.name);
    });
    return names;
}

function isInstalledModel(model, installedNames = []) {
    return installedNames.some(installed => modelsMatch(model, installed));
}

function ollamaModelPromptKey(status = {}) {
    const installed = installedModelNamesFromStatus(status).sort().join('|');
    return `${normalizeModelName(status.current_model)}::${installed}`;
}

function shouldPromptForOllamaModel(status = {}) {
    const download = status.download || {};
    if (status.unchecked || status.available !== true) return false;
    if (download.state === 'downloading') return false;
    return status.current_model_installed === false || status.model_selection_required === true;
}

function ollamaModelSelectionOptions(status = {}) {
    const installedNames = installedModelNamesFromStatus(status);
    const options = [];
    const add = (model, installed = false) => {
        const normalized = normalizeModelName(model);
        if (!normalized) return;
        const alreadyAdded = options.some(item => modelsMatch(item.model, normalized));
        if (alreadyAdded) return;
        options.push({
            model: normalized,
            installed: installed || isInstalledModel(normalized, installedNames),
        });
    };
    (status.installed_model_candidates || []).forEach(model => add(model, true));
    installedNames.forEach(model => add(model, true));
    state.ollamaModels.forEach(model => add(model));
    add(status.current_model);
    return options;
}

function closeOllamaModelRequiredDialog({dismiss = true} = {}) {
    if (!el.ollamaModelRequiredDialog) return;
    el.ollamaModelRequiredDialog.classList.remove('open');
    if (dismiss) state.ollamaModelPromptDismissedKey = ollamaModelPromptKey(state.ollamaStatus);
}

function syncOllamaModelRequiredActions() {
    if (!el.ollamaModelRequiredSelect) return;
    const selected = normalizeModelName(el.ollamaModelRequiredSelect.value);
    const selectedOption = Array.from(el.ollamaModelRequiredSelect.children || []).find(option => modelsMatch(option.value, selected));
    const installed = selectedOption?.dataset?.installed === 'true';
    const downloading = state.ollamaDownloadPolling;
    if (el.useAvailableOllamaModelBtn) {
        el.useAvailableOllamaModelBtn.disabled = !selected || !installed || downloading;
    }
    if (el.downloadRequiredOllamaModelBtn) {
        el.downloadRequiredOllamaModelBtn.disabled = !selected || installed || downloading;
    }
    if (el.ollamaModelRequiredStatus) {
        el.ollamaModelRequiredStatus.textContent = installed
            ? `Use ${selected} now, or open Model settings for more options.`
            : `Download ${selected} before chatting, or choose an installed model.`;
        el.ollamaModelRequiredStatus.style.color = installed ? 'var(--cyan)' : 'var(--yellow)';
    }
}

function showOllamaModelRequiredDialog(status = {}) {
    if (!el.ollamaModelRequiredDialog || !el.ollamaModelRequiredSelect) return;
    const current = normalizeModelName(status.current_model);
    const suggested = normalizeModelName(status.suggested_model);
    const options = ollamaModelSelectionOptions(status);
    el.ollamaModelRequiredSelect.replaceChildren();
    options.forEach(({model, installed}) => {
        const option = D.createElement('option');
        option.value = model;
        option.textContent = installed ? `${model} (installed)` : `${model} (download required)`;
        option.dataset.installed = installed ? 'true' : 'false';
        el.ollamaModelRequiredSelect.appendChild(option);
    });
    if (suggested) el.ollamaModelRequiredSelect.value = suggested;
    else if (options.length) el.ollamaModelRequiredSelect.value = options[0].model;
    if (el.ollamaModelRequiredMessage) {
        el.ollamaModelRequiredMessage.textContent = suggested
            ? `The selected model ${current} is not installed. ${suggested} is installed and can be selected now, or download ${current} before chatting.`
            : `The selected model ${current || 'from settings'} is not installed. Select an installed model or download one before chatting.`;
    }
    syncOllamaModelRequiredActions();
    el.ollamaModelRequiredDialog.classList.add('open');
    el.ollamaModelRequiredSelect.focus?.();
}

function maybePromptForOllamaModelSelection(status = {}) {
    if (!el.ollamaModelRequiredDialog) return;
    if (!shouldPromptForOllamaModel(status)) {
        closeOllamaModelRequiredDialog({dismiss: false});
        return;
    }
    const key = ollamaModelPromptKey(status);
    if (el.ollamaModelRequiredDialog.classList.contains('open')) {
        showOllamaModelRequiredDialog(status);
        return;
    }
    if (state.ollamaModelPromptDismissedKey === key) return;
    showOllamaModelRequiredDialog(status);
}

function openModelSettingsFromPrompt() {
    closeOllamaModelRequiredDialog();
    if (el.setupOverlay) el.setupOverlay.style.display = 'none';
    openSettings('model');
    if (el.ollamaModelStatus) {
        el.ollamaModelStatus.textContent = 'Select an installed model or download the selected model before chatting.';
        el.ollamaModelStatus.style.color = 'var(--yellow)';
    }
    el.ollamaModelSelect?.focus?.();
}

export function normalizePersonaPrompt(prompt) {
    return (prompt || '').trim().replace(/\s+/g, ' ');
}

export function fillPersonaPromptSelect(selectEl, prompts = [], currentPrompt = '') {
    const ordered = [];
    [currentPrompt, ...prompts].forEach(prompt => {
        const normalized = normalizePersonaPrompt(prompt);
        if (normalized && !ordered.includes(normalized)) ordered.push(normalized);
    });
    selectEl.innerHTML = '';
    ordered.forEach(prompt => {
        const option = D.createElement('option');
        option.value = prompt;
        option.textContent = prompt;
        selectEl.appendChild(option);
    });
    if (currentPrompt) selectEl.value = normalizePersonaPrompt(currentPrompt);
    return ordered;
}

export function populatePersonaPromptOptions(prompts = [], currentPrompt = '') {
    state.personaPrompts = fillPersonaPromptSelect(el.personaPromptSelect, prompts, currentPrompt);
    el.personaInput.value = normalizePersonaPrompt(currentPrompt || state.personaPrompts[0] || '');
}

export async function setPersonaPrompt(prompt, savePrompt = true) {
    const normalized = normalizePersonaPrompt(prompt);
    if (!normalized) {
        el.statusText.textContent = 'Enter a persona prompt first.';
        return null;
    }
    const data = await apiCall('/set_persona_prompt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({persona_desc: normalized, save_prompt: savePrompt}),
    });
    if (data && data.status === 'success') {
        state.myPersonaDescription = data.persona;
        populatePersonaPromptOptions(data.persona_prompts, data.persona);
    } else {
        reportSaveFailure(el.statusText, data, 'Persona prompt save failed.');
    }
    return data;
}

export function populateModelOptions(models = [], currentModel = '', status = null) {
    const uniqueModels = [];
    [currentModel, ...models].forEach(model => {
        const normalized = normalizeModelName(model);
        if (normalized && !uniqueModels.includes(normalized)) uniqueModels.push(normalized);
    });
    if (status && status.model_details) state.ollamaModelDetails = modelDetailsFromStatus(status);
    state.ollamaModels = uniqueModels;
    state.ollamaCurrentModel = normalizeModelName(currentModel);
    el.ollamaModelSelect.innerHTML = '';
    uniqueModels.forEach(model => {
        const option = D.createElement('option');
        option.value = model;
        option.textContent = modelOptionLabel(model);
        el.ollamaModelSelect.appendChild(option);
    });
    if (currentModel) el.ollamaModelSelect.value = normalizeModelName(currentModel);
    el.ollamaModelInput.value = normalizeModelName(currentModel);
    el.ollamaModelStatus.textContent = currentModel ? `Current: ${normalizeModelName(currentModel)}` : 'No model selected.';
    renderOllamaModelList(uniqueModels, currentModel);
}

function renderOllamaModelList(models = [], currentModel = '') {
    if (!el.ollamaModelList) return;
    const current = normalizeModelName(currentModel);
    el.ollamaModelList.replaceChildren();
    if (!models.length) {
        const empty = D.createElement('div');
        empty.className = 'settings-help';
        empty.textContent = 'No saved model options.';
        el.ollamaModelList.appendChild(empty);
        return;
    }
    models.forEach(model => {
        const detail = modelDetailFor(model);
        const row = D.createElement('div');
        row.className = 'ollama-model-row';
        if (model === current) row.classList.add('current');
        if (detail.warning) row.classList.add('warning');

        const name = D.createElement('div');
        name.className = 'ollama-model-name';
        name.textContent = model;
        row.appendChild(name);

        const meta = D.createElement('div');
        meta.className = 'ollama-model-meta';
        meta.textContent = modelMetaLabel(detail);
        row.appendChild(meta);

        if (detail.warning) {
            const warning = D.createElement('div');
            warning.className = 'ollama-model-warning';
            warning.textContent = detail.warning;
            row.appendChild(warning);
        }

        const actions = D.createElement('div');
        actions.className = 'ollama-model-row-actions';

        if (modelNeedsDownload(detail)) {
            const downloadButton = D.createElement('button');
            downloadButton.type = 'button';
            downloadButton.className = 'my-button ollama-model-action ollama-model-download';
            downloadButton.innerHTML = '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M12 3v10.2l3.6-3.6L17 11l-5 5-5-5 1.4-1.4 3.6 3.6V3h2Zm-7 15h14v2H5v-2Z"></path></svg>';
            downloadButton.setAttribute('data-requires-backend', '');
            downloadButton.title = `Download ${model}`;
            downloadButton.setAttribute('aria-label', `Download ${model}`);
            downloadButton.disabled = state.ollamaDownloadPolling;
            downloadButton.addEventListener('click', () => downloadOllamaModel(model));
            actions.appendChild(downloadButton);
        } else {
            const downloadSlot = D.createElement('span');
            downloadSlot.className = 'ollama-model-action-spacer';
            downloadSlot.setAttribute('aria-hidden', 'true');
            actions.appendChild(downloadSlot);
        }

        const deleteButton = D.createElement('button');
        deleteButton.type = 'button';
        deleteButton.className = 'my-button ollama-model-action ollama-model-delete';
        deleteButton.innerHTML = '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-.7 11H7.7L7 9Zm3 2v7h2v-7h-2Zm3 0v7h2v-7h-2Z"></path></svg>';
        deleteButton.setAttribute('data-requires-backend', '');
        deleteButton.title = model === current
            ? 'Select another model before deleting this option'
            : `Delete ${model}`;
        deleteButton.setAttribute('aria-label', `Delete ${model}`);
        deleteButton.disabled = model === current;
        deleteButton.addEventListener('click', () => deleteOllamaModel(model));
        actions.appendChild(deleteButton);
        row.appendChild(actions);

        el.ollamaModelList.appendChild(row);
    });
}

function selectedOllamaModelForAction() {
    return normalizeModelName(el.ollamaModelInput.value || el.ollamaModelSelect.value);
}

function ollamaThinkingStatusText(enabled) {
    return enabled
        ? 'Thinking is on. Supported models may be slower.'
        : 'Thinking is off for faster chat.';
}

export function populateOllamaThinkingSetting(enabled = false) {
    state.ollamaThinkingEnabled = Boolean(enabled);
    if (el.ollamaThinkingEnabledCheckbox) {
        el.ollamaThinkingEnabledCheckbox.checked = state.ollamaThinkingEnabled;
    }
    if (el.ollamaThinkingStatus) {
        el.ollamaThinkingStatus.textContent = ollamaThinkingStatusText(state.ollamaThinkingEnabled);
        el.ollamaThinkingStatus.style.color = state.ollamaThinkingEnabled ? 'var(--yellow)' : 'var(--cyan)';
    }
}

export function updateOllamaStatus(status) {
    if (!status) return;
    const download = status.download || {};
    const gpuStatus = status.gpu_status || {};
    const downloadPercent = formatPercent(download.percent);
    state.ollamaStatus = status;
    if (Object.prototype.hasOwnProperty.call(status, 'thinking_enabled')) {
        populateOllamaThinkingSetting(status.thinking_enabled);
    }
    state.ollamaDownloadPolling = download.state === 'downloading';
    state.ollamaModelDetails = modelDetailsFromStatus(status);
    if (state.ollamaModels.length) {
        renderOllamaModelList(state.ollamaModels, state.ollamaCurrentModel || status.current_model);
        for (const option of Array.from(el.ollamaModelSelect?.children || [])) {
            option.textContent = modelOptionLabel(option.value);
        }
    }
    const installedCount = (status.installed_model_names || []).length;
    let message = status.message || 'Ollama model status unavailable.';
    if (installedCount) message += ` Installed locally: ${installedCount}.`;
    if (gpuStatus.warning) {
        message += ` ${gpuStatus.warning}`;
    } else if (gpuStatus.message && status.available && status.current_model_installed) {
        message += ` ${gpuStatus.message}`;
    }
    if (download.state === 'downloading') {
        const progress = downloadPercent ? ` Progress: ${downloadPercent}.` : '';
        message = `Download in progress for ${download.model}:${progress} ${download.message || 'working...'}`;
    } else if (download.state === 'error') {
        message += ` Last download error: ${download.message}`;
    } else if (download.state === 'ready' && download.model) {
        message += ` ${download.message}`;
    }
    el.ollamaModelStatus.textContent = message;
    el.ollamaModelStatus.style.color = status.unchecked
        ? 'var(--comment)'
        : status.available && status.current_model_installed && !gpuStatus.warning && download.state !== 'downloading'
            ? 'var(--cyan)'
            : 'var(--yellow)';
    if (el.downloadOllamaModelBtn) {
        el.downloadOllamaModelBtn.disabled = state.ollamaDownloadPolling;
        el.downloadOllamaModelBtn.textContent = state.ollamaDownloadPolling
            ? `Downloading${downloadPercent ? ` ${downloadPercent}` : ''}...`
            : 'Download Model';
    }
    updateChatModelAvailability(status);
    updateOllamaDiagnostics(status);
    maybePromptForOllamaModelSelection(status);
}

function chatModelBlockedMessage(status = {}) {
    const download = status.download || {};
    if (status.unchecked) {
        return '';
    }
    if (download.state === 'downloading') {
        const progress = formatPercent(download.percent);
        return `Ollama is downloading ${download.model || 'the selected model'}${progress ? ` (${progress})` : ''} - chat is paused until it finishes.`;
    }
    if (!status.available) {
        return 'Ollama offline - start Ollama before chatting.';
    }
    if (!status.current_model_installed) {
        const suggested = normalizeModelName(status.suggested_model);
        if (suggested) {
            return `Model not installed - select ${suggested} or download ${status.current_model || 'the selected model'} in Settings > Model before chatting.`;
        }
        return `Model not installed - download ${status.current_model || 'the selected model'} in Settings > Model before chatting.`;
    }
    return '';
}

export function updateChatModelAvailability(status = {}) {
    const previousMessage = state.chatModelBlockedMessage;
    const message = chatModelBlockedMessage(status);
    const blocked = Boolean(message);
    state.chatModelBlockedMessage = message;
    D.body.classList.toggle('chat-model-unavailable', blocked);
    if (el.userChatInput) {
        el.userChatInput.disabled = blocked;
        if (blocked) el.userChatInput.setAttribute('aria-disabled', 'true');
        else el.userChatInput.removeAttribute('aria-disabled');
        el.userChatInput.placeholder = blocked ? message : 'Type a message or command...';
        el.userChatInput.title = message;
    }
    if (el.sendChatBtn) {
        el.sendChatBtn.disabled = blocked;
        if (blocked) el.sendChatBtn.setAttribute('aria-disabled', 'true');
        else el.sendChatBtn.removeAttribute('aria-disabled');
        el.sendChatBtn.title = blocked ? message : 'Send message';
    }
    if (blocked) {
        setStatusMessage(el.statusText, message, 'warning');
    } else if (el.statusText.textContent === previousMessage) {
        setStatusMessage(el.statusText, 'Ready to chat.', 'success');
    }
}

export async function refreshOllamaStatus() {
    const data = await apiCall('/ollama_status');
    if (data) updateOllamaStatus(data);
    return data;
}

function populateDiagnosticsLevelSelect(selectEl, levels = [], currentLevel = 'compact') {
    if (!selectEl) return;
    const options = levels.length ? levels : [
        {id: 'compact', label: 'Compact'},
        {id: 'status', label: 'Status'},
        {id: 'debug', label: 'Debug'},
    ];
    selectEl.innerHTML = '';
    options.forEach(level => {
        const option = D.createElement('option');
        option.value = level.id;
        option.textContent = level.label;
        selectEl.appendChild(option);
    });
    selectEl.value = currentLevel || 'compact';
}

export function updateOllamaDiagnostics(status = {}) {
    if (!el.ollamaDiagnosticsOutput) return;
    const level = status.diagnostics_level || state.ollamaDiagnosticsLevel || 'compact';
    state.ollamaDiagnosticsLevel = level;
    if (el.ollamaDiagnosticsLevelSelect) el.ollamaDiagnosticsLevelSelect.value = level;
    if (level === 'compact') {
        el.ollamaDiagnosticsOutput.hidden = true;
        el.ollamaDiagnosticsOutput.textContent = '';
        return;
    }

    const diagnostics = status.llm_diagnostics || {};
    const gpuStatus = status.gpu_status || {};
    const lines = [
        `Provider: ${status.available ? 'Ollama reachable' : 'Ollama unavailable'}`,
        `Model: ${status.current_model || diagnostics.model || 'unknown'}`,
        `Thinking: ${(status.thinking_enabled ?? diagnostics.thinking_enabled) ? 'enabled' : 'disabled'}`,
        `GPU: ${gpuStatus.message || 'not checked'}`,
    ];
    if (gpuStatus.current_model_size_vram_label || gpuStatus.current_model_size_label) {
        const vram = gpuStatus.current_model_size_vram_label || '0 B';
        const total = gpuStatus.current_model_size_label || 'unknown total';
        lines.push(`Model memory: ${vram} VRAM / ${total}`);
    }
    if (gpuStatus.warning) lines.push(`GPU warning: ${gpuStatus.warning}`);
    if (diagnostics.last_updated_at) {
        const elapsed = diagnostics.last_elapsed_ms ?? 'unknown';
        const code = diagnostics.last_status_code ?? 'n/a';
        lines.push(`Last request: ${elapsed}ms, HTTP ${code}`);
    } else {
        lines.push('Last request: none recorded');
    }
    if (diagnostics.last_error) lines.push(`Last error: ${diagnostics.last_error}`);
    if (level === 'debug') {
        const raw = diagnostics.last_response_preview || '';
        lines.push(`Thinking text detected: ${diagnostics.last_response_has_thinking ? 'yes' : 'no'}`);
        lines.push('Raw response:');
        lines.push(raw || '(none recorded)');
        if (diagnostics.last_response_truncated) lines.push('(truncated)');
    }
    el.ollamaDiagnosticsOutput.hidden = false;
    el.ollamaDiagnosticsOutput.textContent = lines.join('\n');
}

export function populateDiagnosticsSettings(data = {}) {
    state.diagnosticsLevels = data.diagnostics_levels || state.diagnosticsLevels || [];
    state.motionDiagnosticsLevel = data.motion_diagnostics_level || state.motionDiagnosticsLevel || 'compact';
    state.ollamaDiagnosticsLevel = data.ollama_diagnostics_level || state.ollamaDiagnosticsLevel || 'compact';
    populateDiagnosticsLevelSelect(el.motionDiagnosticsLevelSelect, state.diagnosticsLevels, state.motionDiagnosticsLevel);
    populateDiagnosticsLevelSelect(el.ollamaDiagnosticsLevelSelect, state.diagnosticsLevels, state.ollamaDiagnosticsLevel);
    updateOllamaDiagnostics(data.ollama_status || {diagnostics_level: state.ollamaDiagnosticsLevel});
}

async function saveDiagnosticsLevels() {
    const data = await apiCall('/set_diagnostics_levels', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            motion_diagnostics_level: el.motionDiagnosticsLevelSelect?.value || state.motionDiagnosticsLevel,
            ollama_diagnostics_level: el.ollamaDiagnosticsLevelSelect?.value || state.ollamaDiagnosticsLevel,
        }),
    });
    if (data && data.status === 'success') {
        populateDiagnosticsSettings(data);
        updateOllamaStatus(data.ollama_status);
        el.statusText.textContent = 'Diagnostics settings saved.';
    } else {
        reportSaveFailure(el.statusText, data, 'Diagnostics settings save failed.');
    }
}

async function savePromptModeSetting() {
    const mode = el.llmPromptModeSelect?.value || state.llmPromptMode || 'revibed';
    if (el.llmPromptModeStatus) {
        el.llmPromptModeStatus.textContent = 'Saving prompt style...';
        el.llmPromptModeStatus.style.color = 'var(--comment)';
    }
    const data = await apiCall('/set_llm_prompt_mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({llm_prompt_mode: mode}),
    });
    if (data && data.status === 'success') {
        populatePromptModeSetting(data.llm_prompt_mode, data.llm_prompt_mode_options);
        state.systemPromptsLoadedOnce = false;
        await refreshSystemPrompts();
        if (el.statusText) el.statusText.textContent = 'Prompt style saved.';
    } else {
        reportSaveFailure(el.llmPromptModeStatus || el.statusText, data, 'Prompt style save failed.');
    }
    return data;
}

async function setOllamaModel(model) {
    const normalized = normalizeModelName(model);
    if (!normalized) {
        el.ollamaModelStatus.textContent = 'Enter an Ollama model name first.';
        el.ollamaModelStatus.style.color = 'var(--yellow)';
        return null;
    }
    const data = await apiCall('/set_ollama_model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model: normalized}),
    });
    if (data && data.status === 'success') {
        populateModelOptions(data.ollama_models, data.ollama_model, data.ollama_status);
        updateOllamaStatus(data.ollama_status);
    } else {
        reportSaveFailure(el.ollamaModelStatus, data, `Could not set model to ${normalized}.`);
    }
    return data;
}

async function saveOllamaThinkingSetting() {
    const enabled = Boolean(el.ollamaThinkingEnabledCheckbox?.checked);
    if (el.ollamaThinkingStatus) {
        el.ollamaThinkingStatus.textContent = 'Saving thinking preference...';
        el.ollamaThinkingStatus.style.color = 'var(--comment)';
    }
    const data = await apiCall('/set_ollama_thinking', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled}),
    });
    if (data && data.status === 'success') {
        populateOllamaThinkingSetting(data.ollama_thinking_enabled);
        updateOllamaStatus(data.ollama_status);
        if (el.ollamaThinkingStatus) {
            el.ollamaThinkingStatus.textContent = `Saved. ${ollamaThinkingStatusText(data.ollama_thinking_enabled)}`;
        }
    } else {
        reportSaveFailure(el.ollamaThinkingStatus || el.ollamaModelStatus, data, 'Could not save Ollama thinking preference.');
    }
    return data;
}

function markOllamaThinkingUnsaved() {
    if (!el.ollamaThinkingStatus) return;
    const enabled = Boolean(el.ollamaThinkingEnabledCheckbox?.checked);
    if (enabled === state.ollamaThinkingEnabled) {
        populateOllamaThinkingSetting(state.ollamaThinkingEnabled);
        return;
    }
    el.ollamaThinkingStatus.textContent = `Unsaved. ${ollamaThinkingStatusText(enabled)}`;
    el.ollamaThinkingStatus.style.color = 'var(--comment)';
}

async function deleteOllamaModel(model) {
    const normalized = normalizeModelName(model);
    if (!normalized) return;
    const ok = window.confirm(`Delete ${normalized} from the model options list?`);
    if (!ok) return;
    const data = await apiCall('/delete_ollama_model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model: normalized}),
    });
    if (data && data.status === 'success') {
        populateModelOptions(data.ollama_models, data.ollama_model, data.ollama_status);
        updateOllamaStatus(data.ollama_status);
    } else {
        reportSaveFailure(el.ollamaModelStatus, data, `Could not delete ${normalized}.`);
    }
}

async function downloadOllamaModel(modelOverride = '') {
    const model = normalizeModelName(typeof modelOverride === 'string' ? modelOverride : '') || selectedOllamaModelForAction();
    if (!model) {
        el.ollamaModelStatus.textContent = 'Enter or select an Ollama model first.';
        el.ollamaModelStatus.style.color = 'var(--yellow)';
        return null;
    }
    const ok = window.confirm(`Download ${model} with Ollama now? This may download several GB.`);
    if (!ok) return null;
    el.ollamaModelStatus.textContent = `Starting download for ${model}... Progress: 0%.`;
    el.ollamaModelStatus.style.color = 'var(--comment)';
    const data = await apiCall('/pull_ollama_model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model}),
    });
    if (data) {
        populateModelOptions(data.ollama_models, data.ollama_model, data.ollama_status);
        updateOllamaStatus(data.ollama_status);
    }
    return data;
}

async function resetAllSettings() {
    const ok = window.confirm('Reset all saved settings and restart setup?');
    if (!ok) return;
    el.resetSettingsStatus.textContent = 'Resetting settings...';
    el.resetSettingsStatus.style.color = 'var(--comment)';
    const data = await apiCall('/reset_settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({confirm: 'RESET'}),
    });
    if (data && data.status === 'success') {
        localStorage.removeItem('sidebar_collapsed');
        el.resetSettingsStatus.textContent = 'Settings reset.';
        el.resetSettingsStatus.style.color = 'var(--cyan)';
        window.location.reload();
    }
}

function updateProfilePicture(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onloadend = () => {
        const base64String = reader.result;
        el.pfpPreview.src = base64String;
        el.typingIndicatorPfp.src = base64String;
        if (el.profileMenuPfp) el.profileMenuPfp.src = base64String;
        apiCall('/set_profile_picture', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pfp_b64: base64String}),
        });
    };
    reader.readAsDataURL(file);
}

async function setAiName(addChatMessage) {
    const newName = el.aiNameInput.value.trim();
    if (!newName) return;
    const data = await apiCall('/set_ai_name', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: newName}),
    });
    if (data && data.status === 'special_persona_activated') {
        el.easterEggOverlay.innerHTML = `// WARNING: Personality Core Override Detected...<br>// Subject: ${data.persona}<br><br>Good luck.`;
        el.easterEggOverlay.style.display = 'flex';
        setTimeout(() => { el.easterEggOverlay.style.opacity = '1'; }, 10);
        setTimeout(() => {
            el.easterEggOverlay.style.opacity = '0';
            setTimeout(() => {
                el.easterEggOverlay.style.display = 'none';
                state.aiName = data.persona;
                el.aiNameInput.value = state.aiName;
                D.querySelectorAll('.bot-bubble .speaker-name').forEach(item => { item.textContent = state.aiName; });
                addChatMessage('BOT', data.message);
            }, 1000);
        }, 3000);
    } else if (data && data.status === 'success') {
        state.aiName = data.name;
        el.statusText.textContent = `AI name updated to ${state.aiName}!`;
        D.querySelectorAll('.bot-bubble .speaker-name').forEach(item => { item.textContent = state.aiName; });
    }
}

export function initSettingsControls({addChatMessage}) {
    el.personaPromptSelect.addEventListener('change', () => {
        el.personaInput.value = el.personaPromptSelect.value;
    });
    el.setPersonaBtn.addEventListener('click', async () => {
        const data = await setPersonaPrompt(el.personaInput.value, false);
        if (data) el.statusText.textContent = 'Persona prompt selected.';
    });
    el.savePersonaPromptBtn.addEventListener('click', async () => {
        const data = await setPersonaPrompt(el.personaInput.value, true);
        if (data) el.statusText.textContent = 'Persona prompt saved.';
    });
    el.setAiNameBtn.addEventListener('click', () => setAiName(addChatMessage));
    if (el.profileMenuBtn) {
        el.profileMenuBtn.addEventListener('click', event => {
            event.stopPropagation?.();
            const isOpen = el.profileMenuBtn.getAttribute('aria-expanded') === 'true';
            setProfileMenuOpen(!isOpen);
        });
    }
    if (el.profileMenuSettingsBtns.length) {
        el.profileMenuSettingsBtns.forEach(button => {
            button.addEventListener('click', () => openSettings(button.dataset.settingsTarget || 'persona'));
        });
    } else if (el.openSettingsBtn) {
        el.openSettingsBtn.addEventListener('click', () => openSettings('persona'));
    }
    if (el.profileAboutMenuBtn) {
        el.profileAboutMenuBtn.addEventListener('click', openAboutDialog);
    }
    D.addEventListener('click', event => {
        if (!el.profileMenuPopover || el.profileMenuPopover.hidden) return;
        if (!profileMenuContains(event.target)) closeProfileMenu();
    });
    D.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            closeProfileMenu();
            closeAboutDialog();
            closeOllamaModelRequiredDialog();
        }
    });
    el.toggleSidebarBtn.addEventListener('click', () => {
        const isCollapsed = D.body.classList.toggle('sidebar-collapsed');
        localStorage.setItem('sidebar_collapsed', isCollapsed);
        setTimeout(() => window.dispatchEvent(new Event('resize')), 350);
    });
    el.closeSettingsBtn.addEventListener('click', () => el.settingsDialog.classList.remove('open'));
    el.settingsDialog.addEventListener('click', event => {
        if (event.target === el.settingsDialog) el.settingsDialog.classList.remove('open');
    });
    if (el.closeAboutBtn) {
        el.closeAboutBtn.addEventListener('click', closeAboutDialog);
    }
    if (el.aboutDialog) {
        el.aboutDialog.addEventListener('click', event => {
            if (event.target === el.aboutDialog) closeAboutDialog();
        });
    }
    if (el.closeOllamaModelRequiredBtn) {
        el.closeOllamaModelRequiredBtn.addEventListener('click', () => closeOllamaModelRequiredDialog());
    }
    if (el.ollamaModelRequiredDialog) {
        el.ollamaModelRequiredDialog.addEventListener('click', event => {
            if (event.target === el.ollamaModelRequiredDialog) closeOllamaModelRequiredDialog();
        });
    }
    el.settingsTabs.forEach(tab => {
        tab.addEventListener('click', () => setSettingsTab(tab.dataset.settingsTab));
    });
    if (el.refreshSystemPromptsBtn) {
        el.refreshSystemPromptsBtn.addEventListener('click', refreshSystemPrompts);
    }
    if (el.llmPromptModeSelect) {
        el.llmPromptModeSelect.addEventListener('change', () => {
            if (!el.llmPromptModeStatus) return;
            const mode = el.llmPromptModeSelect.value || 'revibed';
            if (mode === state.llmPromptMode) {
                populatePromptModeSetting(state.llmPromptMode, state.llmPromptModeOptions);
                return;
            }
            el.llmPromptModeStatus.textContent = `Unsaved. ${promptModeStatusText(mode)}`;
            el.llmPromptModeStatus.style.color = 'var(--comment)';
        });
    }
    if (el.saveLlmPromptModeBtn) {
        el.saveLlmPromptModeBtn.addEventListener('click', savePromptModeSetting);
    }
    D.getElementById('use-selected-model-btn').addEventListener('click', () => setOllamaModel(el.ollamaModelSelect.value));
    D.getElementById('refresh-model-field-btn').addEventListener('click', () => {
        el.ollamaModelInput.value = el.ollamaModelSelect.value;
        el.ollamaModelInput.focus();
    });
    D.getElementById('save-ollama-model-btn').addEventListener('click', () => setOllamaModel(el.ollamaModelInput.value));
    el.ollamaThinkingEnabledCheckbox?.addEventListener('change', markOllamaThinkingUnsaved);
    el.saveOllamaThinkingBtn?.addEventListener('click', saveOllamaThinkingSetting);
    el.downloadOllamaModelBtn.addEventListener('click', downloadOllamaModel);
    el.refreshOllamaStatusBtn.addEventListener('click', refreshOllamaStatus);
    if (el.ollamaModelRequiredSelect) {
        el.ollamaModelRequiredSelect.addEventListener('change', syncOllamaModelRequiredActions);
    }
    if (el.useAvailableOllamaModelBtn) {
        el.useAvailableOllamaModelBtn.addEventListener('click', async () => {
            const data = await setOllamaModel(el.ollamaModelRequiredSelect?.value);
            if (data?.status === 'success' && data.ollama_status?.current_model_installed !== false) {
                closeOllamaModelRequiredDialog({dismiss: false});
            }
        });
    }
    if (el.downloadRequiredOllamaModelBtn) {
        el.downloadRequiredOllamaModelBtn.addEventListener('click', async () => {
            const data = await downloadOllamaModel(el.ollamaModelRequiredSelect?.value);
            if (data) closeOllamaModelRequiredDialog({dismiss: false});
        });
    }
    if (el.openModelSettingsBtn) {
        el.openModelSettingsBtn.addEventListener('click', openModelSettingsFromPrompt);
    }
    el.saveMotionDiagnosticsLevelBtn.addEventListener('click', saveDiagnosticsLevels);
    el.saveOllamaDiagnosticsLevelBtn.addEventListener('click', saveDiagnosticsLevels);
    el.ollamaModelSelect.addEventListener('change', () => {
        el.ollamaModelInput.value = el.ollamaModelSelect.value;
        refreshOllamaStatus();
    });
    el.pfpUploadInput.addEventListener('change', event => updateProfilePicture(event.target.files[0]));
    el.resetSettingsBtn.addEventListener('click', resetAllSettings);
}
