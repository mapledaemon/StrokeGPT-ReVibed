import { D, apiCall, el, reportSaveFailure, setStatusMessage, state } from './context.js';
import { updateAudioProviderUi } from './audio.js';

export function setSettingsTab(tabName) {
    el.settingsTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.settingsTab === tabName));
    el.settingsPanels.forEach(panel => panel.classList.toggle('active', panel.id === `settings-tab-${tabName}`));
    if (tabName === 'prompts' && !state.systemPromptsLoadedOnce) {
        refreshSystemPrompts();
    }
}

export async function refreshSystemPrompts() {
    if (el.systemPromptsStatus) el.systemPromptsStatus.textContent = 'Loading...';
    const data = await apiCall('/system_prompts');
    if (!data) {
        if (el.systemPromptsStatus) el.systemPromptsStatus.textContent = 'Could not load system prompts.';
        return;
    }
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

export function populateModelOptions(models = [], currentModel = '') {
    const uniqueModels = [];
    [currentModel, ...models].forEach(model => {
        const normalized = normalizeModelName(model);
        if (normalized && !uniqueModels.includes(normalized)) uniqueModels.push(normalized);
    });
    el.ollamaModelSelect.innerHTML = '';
    uniqueModels.forEach(model => {
        const option = D.createElement('option');
        option.value = model;
        option.textContent = model;
        el.ollamaModelSelect.appendChild(option);
    });
    if (currentModel) el.ollamaModelSelect.value = normalizeModelName(currentModel);
    el.ollamaModelInput.value = normalizeModelName(currentModel);
    el.ollamaModelStatus.textContent = currentModel ? `Current: ${normalizeModelName(currentModel)}` : 'No model selected.';
}

function selectedOllamaModelForAction() {
    return normalizeModelName(el.ollamaModelInput.value || el.ollamaModelSelect.value);
}

export function updateOllamaStatus(status) {
    if (!status) return;
    const download = status.download || {};
    const installedCount = (status.installed_model_names || []).length;
    let message = status.message || 'Ollama model status unavailable.';
    if (installedCount) message += ` Installed locally: ${installedCount}.`;
    if (download.state === 'downloading') {
        message = `Download in progress for ${download.model}: ${download.message || 'working...'}`;
    } else if (download.state === 'error') {
        message += ` Last download error: ${download.message}`;
    } else if (download.state === 'ready' && download.model) {
        message += ` ${download.message}`;
    }
    el.ollamaModelStatus.textContent = message;
    el.ollamaModelStatus.style.color = status.available && status.current_model_installed && download.state !== 'downloading'
        ? 'var(--cyan)'
        : 'var(--yellow)';
    state.ollamaDownloadPolling = download.state === 'downloading';
    if (el.downloadOllamaModelBtn) {
        el.downloadOllamaModelBtn.disabled = state.ollamaDownloadPolling;
        el.downloadOllamaModelBtn.textContent = state.ollamaDownloadPolling ? 'Downloading...' : 'Download Model';
    }
    updateChatModelAvailability(status);
    updateOllamaDiagnostics(status);
}

function chatModelBlockedMessage(status = {}) {
    const download = status.download || {};
    if (download.state === 'downloading') {
        return `Ollama is downloading ${download.model || 'the selected model'} - chat is paused until it finishes.`;
    }
    if (!status.available) {
        return 'Ollama offline - start Ollama before chatting.';
    }
    if (!status.current_model_installed) {
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
    const lines = [
        `Provider: ${status.available ? 'Ollama reachable' : 'Ollama unavailable'}`,
        `Model: ${status.current_model || diagnostics.model || 'unknown'}`,
    ];
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

async function setOllamaModel(model) {
    const normalized = normalizeModelName(model);
    if (!normalized) {
        el.ollamaModelStatus.textContent = 'Enter an Ollama model name first.';
        el.ollamaModelStatus.style.color = 'var(--yellow)';
        return;
    }
    const data = await apiCall('/set_ollama_model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model: normalized}),
    });
    if (data && data.status === 'success') {
        populateModelOptions(data.ollama_models, data.ollama_model);
        updateOllamaStatus(data.ollama_status);
    } else {
        reportSaveFailure(el.ollamaModelStatus, data, `Could not set model to ${normalized}.`);
    }
}

async function downloadOllamaModel() {
    const model = selectedOllamaModelForAction();
    if (!model) {
        el.ollamaModelStatus.textContent = 'Enter or select an Ollama model first.';
        el.ollamaModelStatus.style.color = 'var(--yellow)';
        return;
    }
    const ok = window.confirm(`Download ${model} with Ollama now? This may download several GB.`);
    if (!ok) return;
    el.ollamaModelStatus.textContent = `Starting download for ${model}...`;
    el.ollamaModelStatus.style.color = 'var(--comment)';
    const data = await apiCall('/pull_ollama_model', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model}),
    });
    if (data) {
        populateModelOptions(data.ollama_models, data.ollama_model);
        updateOllamaStatus(data.ollama_status);
    }
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
    el.settingsTabs.forEach(tab => {
        tab.addEventListener('click', () => setSettingsTab(tab.dataset.settingsTab));
    });
    if (el.refreshSystemPromptsBtn) {
        el.refreshSystemPromptsBtn.addEventListener('click', refreshSystemPrompts);
    }
    D.getElementById('use-selected-model-btn').addEventListener('click', () => setOllamaModel(el.ollamaModelSelect.value));
    D.getElementById('refresh-model-field-btn').addEventListener('click', () => {
        el.ollamaModelInput.value = el.ollamaModelSelect.value;
        el.ollamaModelInput.focus();
    });
    D.getElementById('save-ollama-model-btn').addEventListener('click', () => setOllamaModel(el.ollamaModelInput.value));
    el.downloadOllamaModelBtn.addEventListener('click', downloadOllamaModel);
    el.refreshOllamaStatusBtn.addEventListener('click', refreshOllamaStatus);
    el.saveMotionDiagnosticsLevelBtn.addEventListener('click', saveDiagnosticsLevels);
    el.saveOllamaDiagnosticsLevelBtn.addEventListener('click', saveDiagnosticsLevels);
    el.ollamaModelSelect.addEventListener('change', () => {
        el.ollamaModelInput.value = el.ollamaModelSelect.value;
        refreshOllamaStatus();
    });
    el.pfpUploadInput.addEventListener('change', event => updateProfilePicture(event.target.files[0]));
    el.resetSettingsBtn.addEventListener('click', resetAllSettings);
}
