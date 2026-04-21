const D = document;
const userChatInput = D.getElementById('user-chat-input');
const personaInput = D.getElementById('persona-input');
const personaPromptSelect = D.getElementById('persona-prompt-select');
const setPersonaBtn = D.getElementById('set-persona-btn');
const savePersonaPromptBtn = D.getElementById('save-persona-prompt-btn');
const aiNameInput = D.getElementById('ai-name-input');
const setAiNameBtn = D.getElementById('set-ai-name-btn');
const openSettingsBtn = D.getElementById('open-settings-btn');
const settingsDialog = D.getElementById('settings-dialog');
const closeSettingsBtn = D.getElementById('close-settings-btn');
const settingsTabs = D.querySelectorAll('.settings-tab');
const settingsPanels = D.querySelectorAll('.settings-panel');
const ollamaModelSelect = D.getElementById('ollama-model-select');
const ollamaModelInput = D.getElementById('ollama-model-input');
const ollamaModelStatus = D.getElementById('ollama-model-status');
const downloadOllamaModelBtn = D.getElementById('download-ollama-model-btn');
const refreshOllamaStatusBtn = D.getElementById('refresh-ollama-status-btn');
const audioProviderSelect = D.getElementById('audio-provider-select');
const enableAudioCheckbox = D.getElementById('enable-audio-checkbox');
const elevenLabsPanel = D.getElementById('elevenlabs-settings-panel');
const localTtsPanel = D.getElementById('local-tts-settings-panel');
const elevenLabsKeyInput = D.getElementById('elevenlabs-key-input');
const setElevenLabsKeyButton = D.getElementById('set-elevenlabs-key-button');
const elevenLabsVoiceSelect = D.getElementById('elevenlabs-voice-select-box');
const localTtsEngineSelect = D.getElementById('local-tts-engine-select');
const localTtsStyleSelect = D.getElementById('local-tts-style-select');
const localTtsPromptPath = D.getElementById('local-tts-prompt-path');
const localTtsSampleUpload = D.getElementById('local-tts-sample-upload');
const browseLocalTtsSampleBtn = D.getElementById('browse-local-tts-sample-btn');
const downloadLocalTtsModelBtn = D.getElementById('download-local-tts-model-button');
const localTtsExaggeration = D.getElementById('local-tts-exaggeration');
const localTtsExaggerationVal = D.getElementById('local-tts-exaggeration-val');
const localTtsCfg = D.getElementById('local-tts-cfg');
const localTtsCfgVal = D.getElementById('local-tts-cfg-val');
const localTtsTemperature = D.getElementById('local-tts-temperature');
const localTtsTemperatureVal = D.getElementById('local-tts-temperature-val');
const localTtsTopP = D.getElementById('local-tts-top-p');
const localTtsTopPVal = D.getElementById('local-tts-top-p-val');
const localTtsMinP = D.getElementById('local-tts-min-p');
const localTtsMinPVal = D.getElementById('local-tts-min-p-val');
const localTtsRepetition = D.getElementById('local-tts-repetition');
const localTtsRepetitionVal = D.getElementById('local-tts-repetition-val');
const localTtsStatus = D.getElementById('local-tts-status');
const handyKeyInput = D.getElementById('handy-key-input');
const saveHandyKeyBtn = D.getElementById('save-handy-key-btn');
const handyKeyStatus = D.getElementById('handy-key-status');
const motionDepthMinSlider = D.getElementById('motion-depth-min-slider');
const motionDepthMaxSlider = D.getElementById('motion-depth-max-slider');
const motionDepthMinVal = D.getElementById('motion-depth-min-val');
const motionDepthMaxVal = D.getElementById('motion-depth-max-val');
const motionSpeedMinSlider = D.getElementById('motion-speed-min-slider');
const motionSpeedMaxSlider = D.getElementById('motion-speed-max-slider');
const motionSpeedMinVal = D.getElementById('motion-speed-min-val');
const motionSpeedMaxVal = D.getElementById('motion-speed-max-val');
const autoMinTimeInput = D.getElementById('auto-min-time');
const autoMaxTimeInput = D.getElementById('auto-max-time');
const edgingMinTimeInput = D.getElementById('edging-min-time');
const edgingMaxTimeInput = D.getElementById('edging-max-time');
const milkingMinTimeInput = D.getElementById('milking-min-time');
const milkingMaxTimeInput = D.getElementById('milking-max-time');
const setupOverlay = D.getElementById('setup-overlay');
const setupBox = D.getElementById('setup-box');
const statusText = D.getElementById('status-text');
const resetSettingsBtn = D.getElementById('reset-settings-btn');
const resetSettingsStatus = D.getElementById('reset-settings-status');
const moodDisplay = D.getElementById('mood-display');
const rhythmCanvas = D.getElementById('rhythm-canvas');
const typingIndicator = D.getElementById('typing-indicator');
const chatView = D.getElementById('chat-view');
const chatMessagesContainer = D.getElementById('chat-messages-container');
const pfpUploadInput = D.getElementById('pfp-upload');
const pfpPreview = D.getElementById('ai-pfp-preview');
const typingIndicatorPfp = D.getElementById('typing-indicator-pfp');
const toggleSidebarBtn = D.getElementById('toggle-sidebar-btn');
const imCloseBtn = D.getElementById('im-close-btn');
const edgingModeBtn = D.getElementById('edging-mode-btn');
const edgingTimer = D.getElementById('edging-timer');
const easterEggOverlay = D.getElementById('easter-egg-overlay');
const ctx = rhythmCanvas.getContext('2d');
let myHandyKey = '', myPersonaDescription = '', aiName = 'BOT', edgingTimerInterval = null;
let personaPrompts = [];
let localTtsStylePresets = {};
let audioFetchInProgress = false;
let motionMinDepth = 5, motionMaxDepth = 100;
let motionMinSpeed = 10, motionMaxSpeed = 80;
let ollamaDownloadPolling = false;

async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, options);
        if (!response.ok) { throw new Error(`HTTP error! status: ${response.status}`); }
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("audio/")) { return response.blob(); }
        return response.json();
    } catch (error) {
        console.error(`API call to ${endpoint} failed:`, error);
        statusText.textContent = `Error: Cannot connect to server.`;
    }
}

function updateAudioProviderUi() {
    const provider = audioProviderSelect.value;
    elevenLabsPanel.style.display = provider === 'elevenlabs' ? 'flex' : 'none';
    localTtsPanel.style.display = provider === 'local' ? 'flex' : 'none';
}

function setSettingsTab(tabName) {
    settingsTabs.forEach(tab => tab.classList.toggle('active', tab.dataset.settingsTab === tabName));
    settingsPanels.forEach(panel => panel.classList.toggle('active', panel.id === `settings-tab-${tabName}`));
}

function openSettings(tabName = 'voice') {
    setSettingsTab(tabName);
    updateAudioProviderUi();
    settingsDialog.classList.add('open');
}

function normalizeModelName(model) {
    return (model || '').trim().replace(/\s*\/\s*/g, '/').replace(/\s*:\s*/g, ':');
}

function normalizePersonaPrompt(prompt) {
    return (prompt || '').trim().replace(/\s+/g, ' ');
}

function fillPersonaPromptSelect(selectEl, prompts = [], currentPrompt = '') {
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

function populatePersonaPromptOptions(prompts = [], currentPrompt = '') {
    personaPrompts = fillPersonaPromptSelect(personaPromptSelect, prompts, currentPrompt);
    personaInput.value = normalizePersonaPrompt(currentPrompt || personaPrompts[0] || '');
}

async function setPersonaPrompt(prompt, savePrompt = true) {
    const normalized = normalizePersonaPrompt(prompt);
    if (!normalized) {
        statusText.textContent = 'Enter a persona prompt first.';
        return null;
    }
    const data = await apiCall('/set_persona_prompt', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({persona_desc: normalized, save_prompt: savePrompt})});
    if (data && data.status === 'success') {
        myPersonaDescription = data.persona;
        populatePersonaPromptOptions(data.persona_prompts, data.persona);
    }
    return data;
}

function populateModelOptions(models = [], currentModel = '') {
    const uniqueModels = [];
    [currentModel, ...models].forEach(model => {
        const normalized = normalizeModelName(model);
        if (normalized && !uniqueModels.includes(normalized)) uniqueModels.push(normalized);
    });
    ollamaModelSelect.innerHTML = '';
    uniqueModels.forEach(model => {
        const option = D.createElement('option');
        option.value = model;
        option.textContent = model;
        ollamaModelSelect.appendChild(option);
    });
    if (currentModel) ollamaModelSelect.value = normalizeModelName(currentModel);
    ollamaModelInput.value = normalizeModelName(currentModel);
    ollamaModelStatus.textContent = currentModel ? `Current: ${normalizeModelName(currentModel)}` : 'No model selected.';
}

function selectedOllamaModelForAction() {
    return normalizeModelName(ollamaModelInput.value || ollamaModelSelect.value);
}

function updateOllamaStatus(status) {
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
    ollamaModelStatus.textContent = message;
    ollamaModelStatus.style.color = status.available && status.current_model_installed && download.state !== 'downloading'
        ? 'var(--cyan)'
        : 'var(--yellow)';
    ollamaDownloadPolling = download.state === 'downloading';
    if (downloadOllamaModelBtn) {
        downloadOllamaModelBtn.disabled = ollamaDownloadPolling;
        downloadOllamaModelBtn.textContent = ollamaDownloadPolling ? 'Downloading...' : 'Download Model';
    }
}

async function refreshOllamaStatus() {
    const data = await apiCall('/ollama_status');
    if (data) updateOllamaStatus(data);
    return data;
}

async function setOllamaModel(model) {
    const normalized = normalizeModelName(model);
    if (!normalized) {
        ollamaModelStatus.textContent = 'Enter an Ollama model name first.';
        ollamaModelStatus.style.color = 'var(--yellow)';
        return;
    }
    const data = await apiCall('/set_ollama_model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model: normalized})});
    if (data && data.status === 'success') {
        populateModelOptions(data.ollama_models, data.ollama_model);
        updateOllamaStatus(data.ollama_status);
    }
}

async function downloadOllamaModel() {
    const model = selectedOllamaModelForAction();
    if (!model) {
        ollamaModelStatus.textContent = 'Enter or select an Ollama model first.';
        ollamaModelStatus.style.color = 'var(--yellow)';
        return;
    }
    const ok = window.confirm(`Download ${model} with Ollama now? This may download several GB.`);
    if (!ok) return;
    ollamaModelStatus.textContent = `Starting download for ${model}...`;
    ollamaModelStatus.style.color = 'var(--comment)';
    const data = await apiCall('/pull_ollama_model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model})});
    if (data) {
        populateModelOptions(data.ollama_models, data.ollama_model);
        updateOllamaStatus(data.ollama_status);
    }
}

function setSliderValue(slider, valueEl, value) {
    slider.value = value;
    valueEl.textContent = slider.value;
}

function clampNumber(value, min, max, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, parsed));
}

function normalizeMotionDepthRange() {
    const a = parseInt(motionDepthMinSlider.value, 10);
    const b = parseInt(motionDepthMaxSlider.value, 10);
    motionMinDepth = Math.min(a, b);
    motionMaxDepth = Math.max(a, b);
    motionDepthMinVal.textContent = `${motionMinDepth}%`;
    motionDepthMaxVal.textContent = `${motionMaxDepth}%`;
}

function normalizeMotionSpeedLimits() {
    const a = parseInt(motionSpeedMinSlider.value, 10);
    const b = parseInt(motionSpeedMaxSlider.value, 10);
    motionMinSpeed = Math.min(a, b);
    motionMaxSpeed = Math.max(a, b);
    motionSpeedMinVal.textContent = `${motionMinSpeed}%`;
    motionSpeedMaxVal.textContent = `${motionMaxSpeed}%`;
}

function populateDeviceSettings(data = {}) {
    handyKeyInput.value = data.handy_key || myHandyKey || '';
    setSliderValue(motionDepthMinSlider, motionDepthMinVal, data.min_depth ?? 5);
    setSliderValue(motionDepthMaxSlider, motionDepthMaxVal, data.max_depth ?? 100);
    normalizeMotionDepthRange();
}

function populateMotionSettings(data = {}) {
    const timings = data.timings || {};
    setSliderValue(motionSpeedMinSlider, motionSpeedMinVal, data.min_speed ?? motionMinSpeed);
    setSliderValue(motionSpeedMaxSlider, motionSpeedMaxVal, data.max_speed ?? motionMaxSpeed);
    normalizeMotionSpeedLimits();
    autoMinTimeInput.value = timings.auto_min ?? autoMinTimeInput.value ?? 4;
    autoMaxTimeInput.value = timings.auto_max ?? autoMaxTimeInput.value ?? 7;
    edgingMinTimeInput.value = timings.edging_min ?? edgingMinTimeInput.value ?? 5;
    edgingMaxTimeInput.value = timings.edging_max ?? edgingMaxTimeInput.value ?? 8;
    milkingMinTimeInput.value = timings.milking_min ?? milkingMinTimeInput.value ?? 2.5;
    milkingMaxTimeInput.value = timings.milking_max ?? milkingMaxTimeInput.value ?? 4.5;
}

async function testMotionDepthRange() {
    normalizeMotionDepthRange();
    const res = await apiCall('/test_depth_range', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_depth:motionMinDepth, max_depth:motionMaxDepth})});
    if (res && res.status === 'busy') statusText.textContent = 'Depth test already running.';
}

async function saveMotionDepthRange() {
    normalizeMotionDepthRange();
    const res = await apiCall('/set_depth_limits', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_depth:motionMinDepth, max_depth:motionMaxDepth})});
    if (res && res.status === 'success') statusText.textContent = `Stroke range saved: ${motionMinDepth}-${motionMaxDepth}%.`;
}

async function saveHandyConnectionKey() {
    const key = handyKeyInput.value.trim();
    if (!key) {
        handyKeyStatus.textContent = 'Enter a Handy connection key first.';
        handyKeyStatus.style.color = 'var(--yellow)';
        return;
    }
    const res = await apiCall('/set_handy_key', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({key})});
    if (res && res.status === 'success') {
        myHandyKey = key;
        handyKeyStatus.textContent = 'Connection key saved.';
        handyKeyStatus.style.color = 'var(--cyan)';
        statusText.textContent = 'Handy connection key saved.';
    }
}

async function saveMotionSpeedLimits() {
    normalizeMotionSpeedLimits();
    const res = await apiCall('/set_speed_limits', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_speed:motionMinSpeed, max_speed:motionMaxSpeed})});
    if (res && res.status === 'success') {
        populateMotionSettings({min_speed: res.min_speed, max_speed: res.max_speed});
        statusText.textContent = `Speed limits saved: ${motionMinSpeed}-${motionMaxSpeed}%.`;
    }
}

async function resetAllSettings() {
    const ok = window.confirm('Reset all saved settings and restart setup?');
    if (!ok) return;
    resetSettingsStatus.textContent = 'Resetting settings...';
    resetSettingsStatus.style.color = 'var(--comment)';
    const data = await apiCall('/reset_settings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({confirm:'RESET'})});
    if (data && data.status === 'success') {
        localStorage.removeItem('sidebar_collapsed');
        resetSettingsStatus.textContent = 'Settings reset.';
        resetSettingsStatus.style.color = 'var(--cyan)';
        window.location.reload();
    }
}

function readTimingPair(minInput, maxInput) {
    const a = clampNumber(minInput.value, 1, 60, 1);
    const b = clampNumber(maxInput.value, 1, 60, a);
    minInput.value = Math.min(a, b);
    maxInput.value = Math.max(a, b);
    return [Number(minInput.value), Number(maxInput.value)];
}

async function saveModeTimings() {
    const [autoMin, autoMax] = readTimingPair(autoMinTimeInput, autoMaxTimeInput);
    const [edgingMin, edgingMax] = readTimingPair(edgingMinTimeInput, edgingMaxTimeInput);
    const [milkingMin, milkingMax] = readTimingPair(milkingMinTimeInput, milkingMaxTimeInput);
    const data = await apiCall('/set_mode_timings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        auto_min: autoMin,
        auto_max: autoMax,
        edging_min: edgingMin,
        edging_max: edgingMax,
        milking_min: milkingMin,
        milking_max: milkingMax
    })});
    if (data && data.status === 'success') {
        populateMotionSettings({timings: data.timings});
        statusText.textContent = 'Mode timings saved.';
    }
}

function populateLocalStyleOptions(presets) {
    localTtsStylePresets = presets || {};
    localTtsStyleSelect.innerHTML = '';
    for (const [id, preset] of Object.entries(localTtsStylePresets)) {
        const option = D.createElement('option');
        option.value = id;
        option.textContent = preset.label || id;
        localTtsStyleSelect.appendChild(option);
    }
}

function populateLocalEngineOptions(engines = [], currentEngine = '') {
    const options = engines.length ? engines : [
        {id: 'chatterbox_turbo', label: 'Chatterbox Turbo', available: true},
        {id: 'chatterbox', label: 'Chatterbox Standard', available: true}
    ];
    localTtsEngineSelect.innerHTML = '';
    options.forEach(engine => {
        const option = D.createElement('option');
        option.value = engine.id;
        option.textContent = engine.available ? engine.label : `${engine.label} (not installed)`;
        option.disabled = engine.available === false;
        localTtsEngineSelect.appendChild(option);
    });
    localTtsEngineSelect.value = currentEngine || options.find(engine => engine.available !== false)?.id || 'chatterbox_turbo';
}

function applyLocalStylePreset(styleId) {
    const preset = localTtsStylePresets[styleId];
    if (!preset) return;
    setSliderValue(localTtsExaggeration, localTtsExaggerationVal, preset.exaggeration);
    setSliderValue(localTtsCfg, localTtsCfgVal, preset.cfg_weight);
    setSliderValue(localTtsTemperature, localTtsTemperatureVal, preset.temperature);
    setSliderValue(localTtsTopP, localTtsTopPVal, preset.top_p);
    setSliderValue(localTtsMinP, localTtsMinPVal, preset.min_p);
    setSliderValue(localTtsRepetition, localTtsRepetitionVal, preset.repetition_penalty);
}

async function saveAudioProvider() {
    const data = await apiCall('/set_audio_provider', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({provider:audioProviderSelect.value, enabled:enableAudioCheckbox.checked})});
    if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
}

function updateLocalTtsStatus(status) {
    if (!status) return;
    localTtsStatus.textContent = status.message || 'Local voice status unavailable.';
    localTtsStatus.style.color = status.status === 'cpu_only' ? 'var(--yellow)' : (status.available ? 'var(--cyan)' : 'var(--yellow)');
    if (status.engines) populateLocalEngineOptions(status.engines, status.engine);
    if (downloadLocalTtsModelBtn) {
        const loading = status.preload_status === 'loading';
        downloadLocalTtsModelBtn.disabled = loading;
        downloadLocalTtsModelBtn.textContent = loading
            ? 'Downloading / Loading...'
            : (status.model_loaded ? 'Local Voice Model Loaded' : 'Download / Load Local Voice Model');
    }
}

async function saveLocalTtsSettings() {
    const data = await apiCall('/set_local_tts_voice', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
        enabled: enableAudioCheckbox.checked,
        engine: localTtsEngineSelect.value,
        style: localTtsStyleSelect.value,
        prompt_path: localTtsPromptPath.value.trim(),
        exaggeration: localTtsExaggeration.value,
        cfg_weight: localTtsCfg.value,
        temperature: localTtsTemperature.value,
        top_p: localTtsTopP.value,
        min_p: localTtsMinP.value,
        repetition_penalty: localTtsRepetition.value
    })});
    if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
}

async function downloadLocalTtsModel() {
    await saveLocalTtsSettings();
    const ok = window.confirm('Download/load the local Chatterbox voice model now? If it is not cached, this may download several GB.');
    if (!ok) return;
    localTtsStatus.textContent = 'Starting local voice model download/load...';
    localTtsStatus.style.color = 'var(--comment)';
    const data = await apiCall('/preload_local_tts_model', {method:'POST'});
    if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
}

async function uploadLocalTtsSample(file) {
    if (!file) return;
    const formData = new FormData();
    formData.append('sample', file);
    try {
        localTtsStatus.textContent = 'Uploading sample audio...';
        localTtsStatus.style.color = 'var(--comment)';
        const response = await fetch('/upload_local_tts_sample', {method: 'POST', body: formData});
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || `HTTP error! status: ${response.status}`);
        localTtsPromptPath.value = data.prompt_path;
        if (data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
        localTtsStatus.textContent = data.message || 'Sample audio saved.';
        localTtsStatus.style.color = 'var(--cyan)';
    } catch (error) {
        console.error('Sample audio upload failed:', error);
        localTtsStatus.textContent = `Sample upload failed: ${error.message}`;
        localTtsStatus.style.color = 'var(--yellow)';
    } finally {
        localTtsSampleUpload.value = '';
    }
}

async function playQueuedAudio() {
    if (audioFetchInProgress) return;
    audioFetchInProgress = true;
    try {
        const response = await fetch('/get_audio');
        if (response.status === 204) return;
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const audioUrl = URL.createObjectURL(await response.blob());
        const audio = new Audio(audioUrl);
        audio.onended = () => URL.revokeObjectURL(audioUrl);
        audio.onerror = () => {
            URL.revokeObjectURL(audioUrl);
            localTtsStatus.textContent = 'Browser could not play the generated audio.';
            localTtsStatus.style.color = 'var(--yellow)';
        };
        await audio.play();
    } catch (error) {
        console.error('Audio playback failed:', error);
        localTtsStatus.textContent = `Audio playback failed: ${error.message}`;
        localTtsStatus.style.color = 'var(--yellow)';
    } finally {
        audioFetchInProgress = false;
    }
}

function appendPlainMessageText(parent, text) {
    const parts = String(text || '').split('\n');
    parts.forEach((part, index) => {
        if (index > 0) parent.appendChild(D.createElement('br'));
        if (part) parent.appendChild(D.createTextNode(part));
    });
}

function appendMessageText(parent, text) {
    const raw = String(text || '');
    const prePattern = /<pre>([\s\S]*?)<\/pre>/gi;
    let cursor = 0;
    let match;
    while ((match = prePattern.exec(raw)) !== null) {
        appendPlainMessageText(parent, raw.slice(cursor, match.index));
        const pre = D.createElement('pre');
        pre.textContent = match[1];
        parent.appendChild(pre);
        cursor = prePattern.lastIndex;
    }
    appendPlainMessageText(parent, raw.slice(cursor));
}

function addChatMessage(sender, text) {
    const speaker = sender === 'BOT' ? aiName : 'YOU';
    const el = D.createElement('div');
    el.className = `chat-message-container ${sender === 'BOT' ? 'bot-bubble' : 'user-bubble'}`;

    if (sender === 'BOT') {
        const pfp = D.createElement('img');
        pfp.className = 'chat-pfp';
        pfp.src = pfpPreview.src;
        pfp.alt = 'pfp';
        el.appendChild(pfp);
    }

    const content = D.createElement('div');
    content.className = 'message-content';
    const speakerName = D.createElement('p');
    speakerName.className = 'speaker-name';
    speakerName.textContent = speaker;
    const bubble = D.createElement('div');
    bubble.className = 'message-bubble';
    appendMessageText(bubble, text);
    content.appendChild(speakerName);
    content.appendChild(bubble);
    el.appendChild(content);

    chatMessagesContainer.insertBefore(el, typingIndicator);
    chatView.scrollTop = chatView.scrollHeight;
}

async function sendUserMessage(message) {
    const persona = personaInput.value.trim();
    if (message.trim() || persona !== myPersonaDescription) {
        if(message.trim()) addChatMessage('YOU', message);
        myPersonaDescription = persona;
        userChatInput.value = '';
        D.querySelector('#typing-indicator .speaker-name').textContent = aiName;
        typingIndicator.style.display = 'flex';
        chatView.scrollTop = chatView.scrollHeight;
        await apiCall('/send_message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: message, key: myHandyKey, persona_desc: myPersonaDescription }) });
    }
}

function resizeCanvas() {
    const bounds = rhythmCanvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    rhythmCanvas.width = Math.round(bounds.width);
    rhythmCanvas.height = Math.round(bounds.height);
}

function drawHandyVisualizer(speed, depth) {
    const width = rhythmCanvas.width, height = rhythmCanvas.height;
    if (width === 0 || height === 0) return;
    const barHeight = (height / 2) - 4;
    ctx.clearRect(0, 0, width, height);
    ctx.font = "12px sans-serif";
    ctx.fillStyle = 'rgba(193, 18, 31, 0.28)';
    ctx.fillRect(0, 0, width, barHeight);
    ctx.fillStyle = '#e01b2f';
    ctx.fillRect(0, 0, (speed / 100) * width, barHeight);
    ctx.fillStyle = 'white';
    ctx.fillText(`Speed: ${speed}%`, 5, barHeight / 2 + 5);
    ctx.fillStyle = 'rgba(127, 183, 163, 0.25)';
    ctx.fillRect(0, height / 2 + 4, width, barHeight);
    ctx.fillStyle = '#7fb7a3';
    ctx.fillRect(0, height / 2 + 4, (depth / 100) * width, barHeight);
    ctx.fillStyle = 'white';
    ctx.fillText(`Depth: ${depth}%`, 5, height - (barHeight/2) + 5);
}

function startEdgingTimer() {
    if (edgingTimerInterval) clearInterval(edgingTimerInterval);
    edgingTimer.style.display = 'block';
    let seconds = 0;
    edgingTimerInterval = setInterval(() => {
        seconds++;
        const min = Math.floor(seconds / 60).toString().padStart(2, '0');
        const sec = (seconds % 60).toString().padStart(2, '0');
        edgingTimer.textContent = `${min}:${sec}`;
    }, 1000);
}

function stopEdgingTimer() {
    clearInterval(edgingTimerInterval);
    edgingTimerInterval = null;
    edgingTimer.style.display = 'none';
}

function renderSetup(isReturningUser = false, data = {}) {
    setupOverlay.style.display = 'flex';
    let step = isReturningUser ? 2 : 1;

    function displayStep() {
        if (step === 1) {
            setupBox.innerHTML = `<h2>Step 1: Handy Key</h2><p>Please enter your connection key from handyfeeling.com</p><input type="password" id="setup-key" class="input-text" placeholder="Handy Key"><br><button id="setup-next" class="my-button">Next</button>`;
            D.getElementById('setup-next').onclick = async () => {
                const key = D.getElementById('setup-key').value.trim();
                if (!key) return;
                myHandyKey = key;
                await apiCall('/set_handy_key', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ key: myHandyKey }) });
                handyKeyInput.value = myHandyKey;
                handyKeyStatus.textContent = 'Connection key saved.';
                handyKeyStatus.style.color = 'var(--cyan)';
                step = 2; displayStep();
            };
        } else if (step === 2) {
            setupBox.innerHTML = `<h2>Step 2: Persona</h2><p>Choose or edit the AI prompt for this session.</p><select id="setup-persona-select" class="select-box"></select><input type="text" id="setup-persona" class="input-text" placeholder="Describe persona"><div class="voice-actions"><button id="setup-save-persona" class="my-button">Save Prompt</button><button id="setup-next" class="my-button">Continue</button></div>`;
            const setupPersonaSelect = D.getElementById('setup-persona-select');
            const setupPersonaInput = D.getElementById('setup-persona');
            const currentPrompt = data.persona || personaInput.value || personaPrompts[0] || 'An energetic and passionate girlfriend';
            fillPersonaPromptSelect(setupPersonaSelect, personaPrompts, currentPrompt);
            setupPersonaInput.value = normalizePersonaPrompt(currentPrompt);
            setupPersonaSelect.onchange = () => {
                setupPersonaInput.value = setupPersonaSelect.value;
            };
            D.getElementById('setup-save-persona').onclick = async () => {
                const saved = await setPersonaPrompt(setupPersonaInput.value, true);
                if (!saved) return;
                fillPersonaPromptSelect(setupPersonaSelect, saved.persona_prompts, saved.persona);
                setupPersonaInput.value = saved.persona;
                statusText.textContent = 'Persona prompt saved.';
            };
            D.getElementById('setup-next').onclick = async () => {
                const saved = await setPersonaPrompt(setupPersonaInput.value, true);
                if (!saved) return;
                personaInput.value = saved.persona;
                if (isReturningUser) {
                    setupOverlay.style.display = 'none';
                    statusText.textContent = 'Ready to chat.';
                } else {
                    step = 3;
                    displayStep();
                }
            };
        } else if (step === 3) {
            const defaultMinDepth = data.min_depth ?? 5;
            const defaultMaxDepth = data.max_depth ?? 100;
            setupBox.innerHTML = `<h2>Step 3: Stroke Range</h2><p>Choose the safe travel range. Release either slider or press Test to run one pass.</p><div class="slider-container"><label for="depth-min-slider">Tip / Out</label><input type="range" min="0" max="100" value="${defaultMinDepth}" id="depth-min-slider"><span id="depth-min-val">${defaultMinDepth}%</span></div><div class="slider-container"><label for="depth-max-slider">Base / In</label><input type="range" min="0" max="100" value="${defaultMaxDepth}" id="depth-max-slider"><span id="depth-max-val">${defaultMaxDepth}%</span></div><div class="setup-actions"><button id="test-depth-range" class="my-button">Test</button><button id="set-depth-range" class="my-button">Next</button></div>`;
            const minSlider = D.getElementById('depth-min-slider');
            const maxSlider = D.getElementById('depth-max-slider');
            const minVal = D.getElementById('depth-min-val');
            const maxVal = D.getElementById('depth-max-val');
            const normalizeDepthRange = () => {
                const a = parseInt(minSlider.value, 10);
                const b = parseInt(maxSlider.value, 10);
                D.minDepth = Math.min(a, b);
                D.maxDepth = Math.max(a, b);
                minVal.textContent = `${D.minDepth}%`;
                maxVal.textContent = `${D.maxDepth}%`;
            };
            const testDepthRange = async () => {
                normalizeDepthRange();
                const res = await apiCall('/test_depth_range', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_depth:D.minDepth, max_depth:D.maxDepth})});
                if (res && res.status === 'busy') statusText.textContent = 'Depth test already running.';
            };
            minSlider.oninput = normalizeDepthRange;
            maxSlider.oninput = normalizeDepthRange;
            minSlider.onchange = testDepthRange;
            maxSlider.onchange = testDepthRange;
            D.getElementById('test-depth-range').onclick = testDepthRange;
            D.getElementById('set-depth-range').onclick = async () => {
                normalizeDepthRange();
                await apiCall('/set_depth_limits', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_depth:D.minDepth, max_depth:D.maxDepth})});
                populateDeviceSettings({handy_key: myHandyKey, min_depth: D.minDepth, max_depth: D.maxDepth});
                step = 4; displayStep();
            };
            normalizeDepthRange();
        } else if (step === 4 || step === 5) {
            const title = step === 4 ? "Minimum Speed" : "Maximum Speed";
            const defaultVal = step === 4 ? (data.min_speed ?? 10) : (data.max_speed ?? 80);
            setupBox.innerHTML = `<h2>Step ${step}: Set ${title}</h2><p>Choose your preferred ${title.toLowerCase()}.</p><div class="slider-container setup-slider"><input type="range" min="0" max="100" value="${defaultVal}" id="speed-slider"><span id="speed-val">${defaultVal}%</span></div><button id="set-speed" class="my-button">Next</button>`;
            const slider = D.getElementById('speed-slider');
            slider.oninput = () => D.getElementById('speed-val').textContent = `${slider.value}%`;
            D.getElementById('set-speed').onclick = async () => {
                if (step === 4) { D.minSpeed = slider.value; step = 5; displayStep(); }
                else {
                    D.maxSpeed = slider.value;
                    await apiCall('/set_speed_limits', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({min_speed:D.minSpeed, max_speed:D.maxSpeed})});
                    populateMotionSettings({min_speed: D.minSpeed, max_speed: D.maxSpeed});
                    setupOverlay.style.display = 'none';
                    statusText.textContent = `Setup complete. Ready to chat.`;
                }
            };
        }
    }
    displayStep();
}

async function startupCheck() {
    const data = await apiCall('/check_settings');
    if (data && data.configured) {
        statusText.textContent = 'Welcome back! Settings loaded.';
        myHandyKey = data.handy_key;
        myPersonaDescription = data.persona || '';
        populatePersonaPromptOptions(data.persona_prompts, data.persona);
        if(data.ai_name) {
            aiName = data.ai_name;
            aiNameInput.value = aiName;
            D.querySelector('#typing-indicator .speaker-name').textContent = aiName;
        }
        if (data.pfp) {
            pfpPreview.src = data.pfp;
            typingIndicatorPfp.src = data.pfp;
        }
        populateModelOptions(data.ollama_models, data.ollama_model);
        updateOllamaStatus(data.ollama_status);
        populateDeviceSettings(data);
        populateMotionSettings(data);
        audioProviderSelect.value = data.audio_provider || 'elevenlabs';
        enableAudioCheckbox.checked = Boolean(data.audio_enabled);
        populateLocalStyleOptions(data.local_tts_style_presets || (data.local_tts_status && data.local_tts_status.style_presets));
        populateLocalEngineOptions(data.local_tts_engines || (data.local_tts_status && data.local_tts_status.engines), data.local_tts_engine || (data.local_tts_status && data.local_tts_status.engine));
        localTtsStyleSelect.value = data.local_tts_style || 'expressive';
        localTtsPromptPath.value = data.local_tts_prompt_path || '';
        localTtsExaggeration.value = data.local_tts_exaggeration ?? 0.65;
        localTtsExaggerationVal.textContent = localTtsExaggeration.value;
        localTtsCfg.value = data.local_tts_cfg_weight ?? 0.35;
        localTtsCfgVal.textContent = localTtsCfg.value;
        localTtsTemperature.value = data.local_tts_temperature ?? 0.85;
        localTtsTemperatureVal.textContent = localTtsTemperature.value;
        localTtsTopP.value = data.local_tts_top_p ?? 1;
        localTtsTopPVal.textContent = localTtsTopP.value;
        localTtsMinP.value = data.local_tts_min_p ?? 0.05;
        localTtsMinPVal.textContent = localTtsMinP.value;
        localTtsRepetition.value = data.local_tts_repetition_penalty ?? 1.2;
        localTtsRepetitionVal.textContent = localTtsRepetition.value;
        updateLocalTtsStatus(data.local_tts_status);
        updateAudioProviderUi();
        if(data.elevenlabs_key) {
            elevenLabsKeyInput.value = data.elevenlabs_key;
            elevenLabsVoiceSelect.dataset.savedVoiceId = data.elevenlabs_voice_id || '';
            setElevenLabsKeyButton.click();
        }
        if (localStorage.getItem('sidebar_collapsed') === 'true') {
            D.body.classList.add('sidebar-collapsed');
        }
        D.getElementById('splash-screen').style.display = 'none';
        renderSetup(true, data);
    } else {
        populatePersonaPromptOptions(data && data.persona_prompts, data && data.persona);
        populateModelOptions(data && data.ollama_models, data && data.ollama_model);
        updateOllamaStatus(data && data.ollama_status);
        populateDeviceSettings(data || {});
        populateMotionSettings(data || {});
        populateLocalStyleOptions(data && (data.local_tts_style_presets || (data.local_tts_status && data.local_tts_status.style_presets)));
        populateLocalEngineOptions(data && (data.local_tts_engines || (data.local_tts_status && data.local_tts_status.engines)), data && (data.local_tts_engine || (data.local_tts_status && data.local_tts_status.engine)));
        updateLocalTtsStatus(data && data.local_tts_status);
        updateAudioProviderUi();
        const startHandler = (e) => { if(e.key === 'Enter'){ D.removeEventListener('keydown', startHandler); D.getElementById('splash-screen').classList.add('hidden'); setTimeout(() => renderSetup(false), 1000); }};
        D.addEventListener('keydown', startHandler);
    }
}

// Event Listeners
D.getElementById('send-chat-btn').addEventListener('click', () => sendUserMessage(userChatInput.value));
userChatInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') sendUserMessage(userChatInput.value); });
personaPromptSelect.addEventListener('change', () => {
    personaInput.value = personaPromptSelect.value;
});
setPersonaBtn.addEventListener('click', async () => {
    const data = await setPersonaPrompt(personaInput.value, false);
    if (data) statusText.textContent = 'Persona prompt selected.';
});
savePersonaPromptBtn.addEventListener('click', async () => {
    const data = await setPersonaPrompt(personaInput.value, true);
    if (data) statusText.textContent = 'Persona prompt saved.';
});
setAiNameBtn.addEventListener('click', async () => {
    const newName = aiNameInput.value.trim();
    if (!newName) return;
    const data = await apiCall('/set_ai_name', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name: newName}) });
    if (data && data.status === 'special_persona_activated') {
        easterEggOverlay.innerHTML = `// WARNING: Personality Core Override Detected...<br>// Subject: ${data.persona}<br><br>Good luck.`;
        easterEggOverlay.style.display = 'flex';
        setTimeout(() => { easterEggOverlay.style.opacity = '1'; }, 10);
        setTimeout(() => {
            easterEggOverlay.style.opacity = '0';
            setTimeout(() => {
                easterEggOverlay.style.display = 'none';
                aiName = data.persona;
                aiNameInput.value = aiName;
                D.querySelectorAll('.bot-bubble .speaker-name').forEach(el => el.textContent = aiName);
                addChatMessage('BOT', data.message);
            }, 1000);
        }, 3000);
    } else if (data && data.status === 'success') {
        aiName = data.name;
        statusText.textContent = `AI name updated to ${aiName}!`;
        D.querySelectorAll('.bot-bubble .speaker-name').forEach(el => el.textContent = aiName);
    }
});
toggleSidebarBtn.addEventListener('click', () => {
    const isCollapsed = D.body.classList.toggle('sidebar-collapsed');
    localStorage.setItem('sidebar_collapsed', isCollapsed);
    setTimeout(resizeCanvas, 350);
});
openSettingsBtn.addEventListener('click', () => openSettings('persona'));
closeSettingsBtn.addEventListener('click', () => settingsDialog.classList.remove('open'));
settingsDialog.addEventListener('click', (event) => {
    if (event.target === settingsDialog) settingsDialog.classList.remove('open');
});
settingsTabs.forEach(tab => {
    tab.addEventListener('click', () => setSettingsTab(tab.dataset.settingsTab));
});
D.getElementById('use-selected-model-btn').addEventListener('click', () => setOllamaModel(ollamaModelSelect.value));
D.getElementById('refresh-model-field-btn').addEventListener('click', () => {
    ollamaModelInput.value = ollamaModelSelect.value;
    ollamaModelInput.focus();
});
D.getElementById('save-ollama-model-btn').addEventListener('click', () => setOllamaModel(ollamaModelInput.value));
downloadOllamaModelBtn.addEventListener('click', downloadOllamaModel);
refreshOllamaStatusBtn.addEventListener('click', refreshOllamaStatus);
ollamaModelSelect.addEventListener('change', () => {
    ollamaModelInput.value = ollamaModelSelect.value;
    refreshOllamaStatus();
});
pfpUploadInput.addEventListener('change', (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onloadend = () => {
        const base64String = reader.result;
        pfpPreview.src = base64String;
        typingIndicatorPfp.src = base64String;
        apiCall('/set_profile_picture', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pfp_b64: base64String }) });
    };
    reader.readAsDataURL(file);
});
setElevenLabsKeyButton.addEventListener('click', async () => {
    const apiKey = elevenLabsKeyInput.value.trim();
    if(!apiKey) return;
    const data = await apiCall('/setup_elevenlabs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({api_key:apiKey})});
    if (data && data.status === 'success') {
        const placeholder = D.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '-- Pick a Voice --';
        elevenLabsVoiceSelect.replaceChildren(placeholder);
        for (const [name, id] of Object.entries(data.voices)) {
            const option = D.createElement('option');
            option.value = id;
            option.textContent = name;
            elevenLabsVoiceSelect.appendChild(option);
        }
        elevenLabsVoiceSelect.disabled = false;
        if (elevenLabsVoiceSelect.dataset.savedVoiceId) elevenLabsVoiceSelect.value = elevenLabsVoiceSelect.dataset.savedVoiceId;
    }
});
D.getElementById('like-this-move-btn').addEventListener('click', async () => {
    const data = await apiCall('/like_last_move', { method: 'POST' });
    if (data && data.status === 'boosted') {
        statusText.textContent = `Saved '${data.name}' to my memory!`;
    } else { statusText.textContent = "Status: No active move to like."; }
});
const stopButtons = [D.getElementById('stop-auto-btn'), D.getElementById('emergency-stop-all-btn')];
stopButtons.forEach(btn => btn.addEventListener('click', () => {
    imCloseBtn.style.display = 'none';
    stopEdgingTimer();
    if(btn.id === 'emergency-stop-all-btn') sendUserMessage('stop');
    else apiCall('/stop_auto_mode', {method:'POST'});
}));
edgingModeBtn.addEventListener('click', () => {
    apiCall('/start_edging_mode', {method:'POST'});
    imCloseBtn.style.display = 'block';
    startEdgingTimer();
});
imCloseBtn.addEventListener('click', () => {
    apiCall('/signal_edge', { method: 'POST' });
    imCloseBtn.style.transform = 'scale(0.95)';
    setTimeout(() => { imCloseBtn.style.transform = ''; }, 100);
});
audioProviderSelect.addEventListener('change', async () => {
    updateAudioProviderUi();
    await saveAudioProvider();
});
enableAudioCheckbox.addEventListener('change', async () => {
    if (audioProviderSelect.value === 'local') await saveLocalTtsSettings();
    else await apiCall('/set_elevenlabs_voice', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({voice_id: elevenLabsVoiceSelect.value, enabled: enableAudioCheckbox.checked})});
});
elevenLabsVoiceSelect.addEventListener('change', (e) => apiCall('/set_elevenlabs_voice', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({voice_id: e.target.value, enabled:enableAudioCheckbox.checked})}));
localTtsStyleSelect.addEventListener('change', () => applyLocalStylePreset(localTtsStyleSelect.value));
browseLocalTtsSampleBtn.addEventListener('click', () => localTtsSampleUpload.click());
localTtsSampleUpload.addEventListener('change', (event) => uploadLocalTtsSample(event.target.files[0]));
localTtsExaggeration.addEventListener('input', () => localTtsExaggerationVal.textContent = localTtsExaggeration.value);
localTtsCfg.addEventListener('input', () => localTtsCfgVal.textContent = localTtsCfg.value);
localTtsTemperature.addEventListener('input', () => localTtsTemperatureVal.textContent = localTtsTemperature.value);
localTtsTopP.addEventListener('input', () => localTtsTopPVal.textContent = localTtsTopP.value);
localTtsMinP.addEventListener('input', () => localTtsMinPVal.textContent = localTtsMinP.value);
localTtsRepetition.addEventListener('input', () => localTtsRepetitionVal.textContent = localTtsRepetition.value);
saveHandyKeyBtn.addEventListener('click', saveHandyConnectionKey);
motionDepthMinSlider.addEventListener('input', normalizeMotionDepthRange);
motionDepthMaxSlider.addEventListener('input', normalizeMotionDepthRange);
motionDepthMinSlider.addEventListener('change', testMotionDepthRange);
motionDepthMaxSlider.addEventListener('change', testMotionDepthRange);
D.getElementById('test-motion-depth-range').addEventListener('click', testMotionDepthRange);
D.getElementById('save-motion-depth-range').addEventListener('click', saveMotionDepthRange);
motionSpeedMinSlider.addEventListener('input', normalizeMotionSpeedLimits);
motionSpeedMaxSlider.addEventListener('input', normalizeMotionSpeedLimits);
D.getElementById('save-motion-speed-limits').addEventListener('click', saveMotionSpeedLimits);
D.getElementById('save-timings-btn').addEventListener('click', saveModeTimings);
resetSettingsBtn.addEventListener('click', resetAllSettings);
D.getElementById('set-local-tts-button').addEventListener('click', saveLocalTtsSettings);
downloadLocalTtsModelBtn.addEventListener('click', downloadLocalTtsModel);
D.getElementById('test-local-tts-button').addEventListener('click', async () => {
    await saveLocalTtsSettings();
    const data = await apiCall('/test_local_tts_voice', {method:'POST'});
    if (data && data.message) {
        localTtsStatus.textContent = data.message;
        localTtsStatus.style.color = data.status === 'needs_download' ? 'var(--yellow)' : 'var(--cyan)';
    }
    if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
});
D.getElementById('start-auto-btn').addEventListener('click', () => sendUserMessage('take over'));
D.getElementById('milking-mode-btn').addEventListener('click', () => apiCall('/start_milking_mode', {method:'POST'}));

// Polling Loops
setInterval(async () => {
    const data = await apiCall('/get_updates');
    if (!data) return;
    if (data.messages && data.messages.length > 0) {
        typingIndicator.style.display = 'none';
    }
    if (data.messages) {
        data.messages.forEach(msg => addChatMessage('BOT', msg));
    }
    if (data.audio_error) {
        localTtsStatus.textContent = data.audio_error;
        localTtsStatus.style.color = 'var(--yellow)';
    }
    if (data.audio_ready) {
        await playQueuedAudio();
    }
}, 1500);
setInterval(async () => {
    const data = await apiCall('/get_status');
    if (data) {
        const emoji = {'Curious':'🤔','Teasing':'😉','Playful':'😜','Loving':'❤️','Excited':'✨','Passionate':'🔥','Seductive':'😈','Anticipatory':'👀','Breathless':'🥵','Dominant':'👑','Submissive':'🙇‍♀️','Vulnerable':'😳','Confident':'😏','Intimate':'🥰','Needy':'🥺','Overwhelmed':'🤯','Afterglow':'😌'}[data.mood] || '';
        moodDisplay.textContent = `Mood: ${data.mood} ${emoji}`;
        drawHandyVisualizer(data.speed || 0, data.depth || 0);
    }
}, 500);
setInterval(async () => {
    if (ollamaDownloadPolling) await refreshOllamaStatus();
}, 2500);

// Startup
window.addEventListener('resize', resizeCanvas);
D.addEventListener('DOMContentLoaded', () => {
    resizeCanvas();
    updateAudioProviderUi();
    startupCheck();
});
