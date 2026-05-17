import { D, apiCall, el, fetchWithConnectionState, formatElapsed, formatPercent, reportSaveFailure, setSliderValue, state } from './context.js';

let lastKnownAudioEnabled = false;

export function updateVoiceOutputToggleUi(enabled = el.enableAudioCheckbox.checked) {
    lastKnownAudioEnabled = Boolean(enabled);
    el.enableAudioCheckbox.checked = lastKnownAudioEnabled;
    if (!el.topBarVoiceToggleBtn) return;
    el.topBarVoiceToggleBtn.textContent = lastKnownAudioEnabled ? 'Voice On' : 'Voice Off';
    el.topBarVoiceToggleBtn.title = lastKnownAudioEnabled ? 'Turn voice output off' : 'Turn voice output on';
    el.topBarVoiceToggleBtn.setAttribute('aria-label', lastKnownAudioEnabled ? 'Voice output on' : 'Voice output off');
    el.topBarVoiceToggleBtn.setAttribute('aria-pressed', lastKnownAudioEnabled ? 'true' : 'false');
    if (lastKnownAudioEnabled) el.topBarVoiceToggleBtn.classList.add('is-on');
    else el.topBarVoiceToggleBtn.classList.remove('is-on');
}

export function voiceOutputEnabled() {
    return Boolean(lastKnownAudioEnabled || el.enableAudioCheckbox?.checked);
}

export function updateAudioProviderUi() {
    const provider = el.audioProviderSelect.value;
    el.elevenLabsPanel.style.display = provider === 'elevenlabs' ? 'flex' : 'none';
    el.localTtsPanel.style.display = provider === 'local' ? 'flex' : 'none';
}

export function populateLocalStyleOptions(presets) {
    state.localTtsStylePresets = presets || {};
    el.localTtsStyleSelect.innerHTML = '';
    for (const [id, preset] of Object.entries(state.localTtsStylePresets)) {
        const option = D.createElement('option');
        option.value = id;
        option.textContent = preset.label || id;
        el.localTtsStyleSelect.appendChild(option);
    }
}

export function populateLocalEngineOptions(engines = [], currentEngine = '') {
    const options = engines.length ? engines : [
        {id: 'chatterbox_turbo', label: 'Chatterbox Turbo', available: true},
        {id: 'chatterbox', label: 'Chatterbox Standard', available: true},
    ];
    el.localTtsEngineSelect.innerHTML = '';
    options.forEach(engine => {
        const option = D.createElement('option');
        option.value = engine.id;
        option.textContent = engine.available ? engine.label : `${engine.label} (not installed)`;
        option.disabled = engine.available === false;
        el.localTtsEngineSelect.appendChild(option);
    });
    el.localTtsEngineSelect.value = currentEngine || options.find(engine => engine.available !== false)?.id || 'chatterbox_turbo';
}

export function applyLocalStylePreset(styleId) {
    const preset = state.localTtsStylePresets[styleId];
    if (!preset) return;
    setSliderValue(el.localTtsExaggeration, el.localTtsExaggerationVal, preset.exaggeration);
    setSliderValue(el.localTtsCfg, el.localTtsCfgVal, preset.cfg_weight);
    setSliderValue(el.localTtsTemperature, el.localTtsTemperatureVal, preset.temperature);
    setSliderValue(el.localTtsTopP, el.localTtsTopPVal, preset.top_p);
    setSliderValue(el.localTtsMinP, el.localTtsMinPVal, preset.min_p);
    setSliderValue(el.localTtsRepetition, el.localTtsRepetitionVal, preset.repetition_penalty);
}

async function saveAudioProvider() {
    const data = await apiCall('/set_audio_provider', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({provider: el.audioProviderSelect.value, enabled: el.enableAudioCheckbox.checked}),
    });
    if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
    if (data && data.status === 'error') reportSaveFailure(el.statusText, data, 'Could not save audio provider.');
    else if (!data || !data.local_tts_status) reportSaveFailure(el.statusText, data, 'Could not save audio provider.');
    else updateVoiceOutputToggleUi(el.enableAudioCheckbox.checked);
    return data;
}

export function updateLocalTtsStatus(status) {
    if (!status) return;
    const loading = status.preload_status === 'loading';
    const generating = status.generation_status === 'generating';
    const preloadElapsed = formatElapsed(status.preload_elapsed_seconds);
    const preloadProgress = formatPercent(status.preload_progress_percent);
    const generationElapsed = formatElapsed(status.generation_elapsed_seconds);
    let message = status.message || 'Local voice status unavailable.';
    if (loading && preloadProgress) message += ` Progress: ${preloadProgress}.`;
    if (loading && preloadElapsed) message += ` Elapsed: ${preloadElapsed}.`;
    if (generating && generationElapsed) message += ` Generation elapsed: ${generationElapsed}.`;
    el.localTtsStatus.textContent = message;
    el.localTtsStatus.style.color = loading || generating
        ? 'var(--comment)'
        : (status.available && status.status !== 'cpu_only' && status.preload_status !== 'error' && status.generation_status !== 'error' ? 'var(--cyan)' : 'var(--yellow)');
    state.localTtsStatusPolling = loading || generating;
    if (status.engines && D.activeElement !== el.localTtsEngineSelect) {
        populateLocalEngineOptions(status.engines, status.engine);
    }
    if (el.downloadLocalTtsModelBtn) {
        el.downloadLocalTtsModelBtn.disabled = loading;
        el.downloadLocalTtsModelBtn.textContent = loading
            ? `Downloading / Loading${preloadProgress ? ` ${preloadProgress}` : ''}...`
            : (status.model_loaded ? 'Local Voice Model Loaded' : 'Download / Load Local Voice Model');
    }
}

export async function refreshLocalTtsStatus() {
    const data = await apiCall('/local_tts_status');
    if (data) updateLocalTtsStatus(data);
    return data;
}

export async function saveLocalTtsSettings({failureTarget = el.localTtsStatus} = {}) {
    const data = await apiCall('/set_local_tts_voice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            enabled: el.enableAudioCheckbox.checked,
            engine: el.localTtsEngineSelect.value,
            style: el.localTtsStyleSelect.value,
            prompt_path: el.localTtsPromptPath.value.trim(),
            exaggeration: el.localTtsExaggeration.value,
            cfg_weight: el.localTtsCfg.value,
            temperature: el.localTtsTemperature.value,
            top_p: el.localTtsTopP.value,
            min_p: el.localTtsMinP.value,
            repetition_penalty: el.localTtsRepetition.value,
        }),
    });
    if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
    if (data && data.status === 'error') reportSaveFailure(failureTarget, data, 'Could not save local voice settings.');
    else if (!data || !data.local_tts_status) reportSaveFailure(failureTarget, data, 'Could not save local voice settings.');
    return data;
}

async function saveElevenLabsEnabled() {
    const data = await apiCall('/set_elevenlabs_voice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({voice_id: el.elevenLabsVoiceSelect.value, enabled: el.enableAudioCheckbox.checked}),
    });
    if (data && data.status === 'error') reportSaveFailure(el.statusText, data, 'Could not save voice output setting.');
    else if (!data) reportSaveFailure(el.statusText, data, 'Could not save voice output setting.');
    return data;
}

async function saveAudioEnabled(enabled, {failureTarget = el.statusText} = {}) {
    const previousEnabled = lastKnownAudioEnabled;
    el.enableAudioCheckbox.checked = Boolean(enabled);
    updateVoiceOutputToggleUi(enabled);

    const data = el.audioProviderSelect.value === 'local'
        ? await saveLocalTtsSettings({failureTarget})
        : await saveElevenLabsEnabled();

    if (!data || data.status === 'error') {
        el.enableAudioCheckbox.checked = previousEnabled;
        updateVoiceOutputToggleUi(previousEnabled);
        return data;
    }

    updateVoiceOutputToggleUi(enabled);
    return data;
}

async function downloadLocalTtsModel() {
    const saved = await saveLocalTtsSettings();
    if (!saved || saved.status === 'error') {
        reportSaveFailure(el.localTtsStatus, saved, 'Could not save local voice settings before model download.');
        return;
    }
    const ok = window.confirm('Download/load the local Chatterbox voice model now? If it is not cached, this may download several GB.');
    if (!ok) return;
    state.localTtsStatusPolling = true;
    el.localTtsStatus.textContent = 'Starting local voice model download/load... Progress: 0%.';
    el.localTtsStatus.style.color = 'var(--comment)';
    el.downloadLocalTtsModelBtn.disabled = true;
    el.downloadLocalTtsModelBtn.textContent = 'Starting 0%...';
    const data = await apiCall('/preload_local_tts_model', {method: 'POST'});
    if (data && data.status === 'error') {
        state.localTtsStatusPolling = false;
        reportSaveFailure(el.localTtsStatus, data, 'Local voice model download/load request failed. Check the app console for details.');
        el.downloadLocalTtsModelBtn.disabled = false;
        el.downloadLocalTtsModelBtn.textContent = 'Download / Load Local Voice Model';
        return;
    }
    if (data && data.local_tts_status) {
        updateLocalTtsStatus(data.local_tts_status);
        if (data.status === 'started') {
            state.localTtsStatusPolling = true;
            window.setTimeout(() => refreshLocalTtsStatus(), 750);
        }
        return;
    }
    state.localTtsStatusPolling = false;
    reportSaveFailure(el.localTtsStatus, data, 'Local voice model download/load request failed. Check the app console for details.');
    el.downloadLocalTtsModelBtn.disabled = false;
    el.downloadLocalTtsModelBtn.textContent = 'Download / Load Local Voice Model';
}

async function uploadLocalTtsSample(file) {
    if (!file) return;
    const formData = new FormData();
    formData.append('sample', file);
    try {
        el.localTtsStatus.textContent = 'Uploading sample audio...';
        el.localTtsStatus.style.color = 'var(--comment)';
        const response = await fetchWithConnectionState('/upload_local_tts_sample', {method: 'POST', body: formData});
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || `HTTP error! status: ${response.status}`);
        el.localTtsPromptPath.value = data.prompt_path;
        if (data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
        el.localTtsStatus.textContent = data.message || 'Sample audio saved.';
        el.localTtsStatus.style.color = 'var(--cyan)';
    } catch (error) {
        console.error('Sample audio upload failed:', error);
        el.localTtsStatus.textContent = `Sample upload failed: ${error.message}`;
        el.localTtsStatus.style.color = 'var(--yellow)';
    } finally {
        el.localTtsSampleUpload.value = '';
    }
}

async function setupElevenLabsKey() {
    const apiKey = el.elevenLabsKeyInput.value.trim();
    if (!apiKey) return;
    const data = await apiCall('/setup_elevenlabs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({api_key: apiKey}),
    });
    if (data && data.status === 'success') {
        const placeholder = D.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '-- Pick a Voice --';
        el.elevenLabsVoiceSelect.replaceChildren(placeholder);
        for (const [name, id] of Object.entries(data.voices)) {
            const option = D.createElement('option');
            option.value = id;
            option.textContent = name;
            el.elevenLabsVoiceSelect.appendChild(option);
        }
        el.elevenLabsVoiceSelect.disabled = false;
        if (el.elevenLabsVoiceSelect.dataset.savedVoiceId) {
            el.elevenLabsVoiceSelect.value = el.elevenLabsVoiceSelect.dataset.savedVoiceId;
        }
    } else {
        reportSaveFailure(el.statusText, data, 'Could not validate ElevenLabs API key.');
    }
}

export async function playQueuedAudio({waitMs = 0, followupWaitMs = 350} = {}) {
    if (state.audioFetchInProgress) return false;
    state.audioFetchInProgress = true;
    let playedAny = false;
    try {
        let nextWaitMs = Math.max(0, Number(waitMs) || 0);
        while (true) {
            const query = nextWaitMs > 0 ? `?wait_ms=${Math.round(nextWaitMs)}` : '';
            const response = await fetchWithConnectionState('/get_audio' + query);
            if (response.status === 204) return playedAny;
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const audioUrl = URL.createObjectURL(await response.blob());
            const audio = new Audio(audioUrl);
            await new Promise((resolve, reject) => {
                let settled = false;
                const finish = (error = null) => {
                    if (settled) return;
                    settled = true;
                    URL.revokeObjectURL(audioUrl);
                    if (error) reject(error);
                    else resolve();
                };
                audio.onended = () => finish();
                audio.onerror = () => finish(new Error('Browser could not play the generated audio.'));
                const playback = audio.play();
                if (playback && typeof playback.catch === 'function') playback.catch(finish);
            });
            playedAny = true;
            nextWaitMs = Math.max(0, Number(followupWaitMs) || 0);
        }
    } catch (error) {
        console.error('Audio playback failed:', error);
        el.localTtsStatus.textContent = `Audio playback failed: ${error.message}`;
        el.localTtsStatus.style.color = 'var(--yellow)';
        return playedAny;
    } finally {
        state.audioFetchInProgress = false;
    }
}

export function populateAudioSettings(data = {}) {
    el.audioProviderSelect.value = data.audio_provider || 'elevenlabs';
    el.enableAudioCheckbox.checked = Boolean(data.audio_enabled);
    updateVoiceOutputToggleUi(data.audio_enabled);
    populateLocalStyleOptions(data.local_tts_style_presets || (data.local_tts_status && data.local_tts_status.style_presets));
    populateLocalEngineOptions(
        data.local_tts_engines || (data.local_tts_status && data.local_tts_status.engines),
        data.local_tts_engine || (data.local_tts_status && data.local_tts_status.engine),
    );
    el.localTtsStyleSelect.value = data.local_tts_style || 'expressive';
    el.localTtsPromptPath.value = data.local_tts_prompt_path || '';
    el.localTtsExaggeration.value = data.local_tts_exaggeration ?? 0.65;
    el.localTtsExaggerationVal.textContent = el.localTtsExaggeration.value;
    el.localTtsCfg.value = data.local_tts_cfg_weight ?? 0.35;
    el.localTtsCfgVal.textContent = el.localTtsCfg.value;
    el.localTtsTemperature.value = data.local_tts_temperature ?? 0.85;
    el.localTtsTemperatureVal.textContent = el.localTtsTemperature.value;
    el.localTtsTopP.value = data.local_tts_top_p ?? 1;
    el.localTtsTopPVal.textContent = el.localTtsTopP.value;
    el.localTtsMinP.value = data.local_tts_min_p ?? 0.05;
    el.localTtsMinPVal.textContent = el.localTtsMinP.value;
    el.localTtsRepetition.value = data.local_tts_repetition_penalty ?? 1.2;
    el.localTtsRepetitionVal.textContent = el.localTtsRepetition.value;
    updateLocalTtsStatus(data.local_tts_status);
    updateAudioProviderUi();
}

export function initAudioControls() {
    el.setElevenLabsKeyButton.addEventListener('click', setupElevenLabsKey);
    el.audioProviderSelect.addEventListener('change', async () => {
        updateAudioProviderUi();
        await saveAudioProvider();
    });
    el.enableAudioCheckbox.addEventListener('change', async () => {
        await saveAudioEnabled(el.enableAudioCheckbox.checked, {failureTarget: el.localTtsStatus});
    });
    el.topBarVoiceToggleBtn.addEventListener('click', async () => {
        await saveAudioEnabled(!lastKnownAudioEnabled, {failureTarget: el.statusText});
    });
    el.elevenLabsVoiceSelect.addEventListener('change', event => apiCall('/set_elevenlabs_voice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({voice_id: event.target.value, enabled: el.enableAudioCheckbox.checked}),
    }));
    el.localTtsStyleSelect.addEventListener('change', () => applyLocalStylePreset(el.localTtsStyleSelect.value));
    el.browseLocalTtsSampleBtn.addEventListener('click', () => el.localTtsSampleUpload.click());
    el.localTtsSampleUpload.addEventListener('change', event => uploadLocalTtsSample(event.target.files[0]));
    el.localTtsExaggeration.addEventListener('input', () => { el.localTtsExaggerationVal.textContent = el.localTtsExaggeration.value; });
    el.localTtsCfg.addEventListener('input', () => { el.localTtsCfgVal.textContent = el.localTtsCfg.value; });
    el.localTtsTemperature.addEventListener('input', () => { el.localTtsTemperatureVal.textContent = el.localTtsTemperature.value; });
    el.localTtsTopP.addEventListener('input', () => { el.localTtsTopPVal.textContent = el.localTtsTopP.value; });
    el.localTtsMinP.addEventListener('input', () => { el.localTtsMinPVal.textContent = el.localTtsMinP.value; });
    el.localTtsRepetition.addEventListener('input', () => { el.localTtsRepetitionVal.textContent = el.localTtsRepetition.value; });
    D.getElementById('set-local-tts-button').addEventListener('click', saveLocalTtsSettings);
    el.downloadLocalTtsModelBtn.addEventListener('click', downloadLocalTtsModel);
    D.getElementById('test-local-tts-button').addEventListener('click', async () => {
        await saveLocalTtsSettings();
        const data = await apiCall('/test_local_tts_voice', {method: 'POST'});
        if (data && data.message) {
            el.localTtsStatus.textContent = data.message;
            el.localTtsStatus.style.color = data.status === 'needs_download' ? 'var(--yellow)' : 'var(--cyan)';
        }
        if (data && data.local_tts_status) updateLocalTtsStatus(data.local_tts_status);
        if (data && data.status === 'queued') state.localTtsStatusPolling = true;
    });
}
