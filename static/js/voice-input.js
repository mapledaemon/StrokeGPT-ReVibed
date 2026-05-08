import { D, clampNumber, el, fetchWithConnectionState, state } from './context.js';

const DEFAULT_HANDS_FREE_SENSITIVITY = 75;
const DEFAULT_HANDS_FREE_SILENCE_MS = 900;
const DEFAULT_MIN_RECORDING_MS = 450;
const DEFAULT_MAX_RECORDING_MS = 8000;
const HANDS_FREE_RMS_THRESHOLD_MIN = 0.01;
const HANDS_FREE_RMS_THRESHOLD_MAX = 0.12;
const SLOW_ASR_WARNING_MS = 2500;

let submitVoiceTranscript = async () => {};

function voiceStatusMessage(message, color = 'var(--comment)', {issue = false, clearIssue = false} = {}) {
    if (issue) state.voiceInputLastIssue = message;
    else if (clearIssue) state.voiceInputLastIssue = '';
    if (el.voiceInputStatus) {
        el.voiceInputStatus.textContent = message;
        el.voiceInputStatus.style.color = color;
    }
    if (el.statusText) el.statusText.textContent = message;
    updateVoiceInputDiagnostics();
}

function formatMs(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '-';
    return `${Math.max(0, Math.round(number))} ms`;
}

function handsFreeSensitivity() {
    return Math.round(clampNumber(state.voiceInputHandsFreeSensitivity, 1, 100, DEFAULT_HANDS_FREE_SENSITIVITY));
}

function handsFreeRmsThreshold() {
    const ratio = (handsFreeSensitivity() - 1) / 99;
    return HANDS_FREE_RMS_THRESHOLD_MAX - (ratio * (HANDS_FREE_RMS_THRESHOLD_MAX - HANDS_FREE_RMS_THRESHOLD_MIN));
}

function handsFreeSilenceMs() {
    return Math.round(clampNumber(state.voiceInputHandsFreeSilenceMs, 250, 5000, DEFAULT_HANDS_FREE_SILENCE_MS));
}

function minRecordingMs() {
    return Math.round(clampNumber(state.voiceInputMinRecordingMs, 150, 3000, DEFAULT_MIN_RECORDING_MS));
}

function maxRecordingMs() {
    return Math.max(
        minRecordingMs(),
        Math.round(clampNumber(state.voiceInputMaxRecordingMs, 1000, 30000, DEFAULT_MAX_RECORDING_MS)),
    );
}

function formatBytes(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return '-';
    if (number >= 1024 * 1024) return `${(number / (1024 * 1024)).toFixed(1)} MB`;
    if (number >= 1024) return `${Math.round(number / 1024)} KB`;
    return `${Math.round(number)} B`;
}

function compactCachePath(path = '') {
    const normalized = String(path || '').trim().replaceAll('\\', '/');
    if (!normalized) return '-';
    const marker = 'user_data/';
    const markerIndex = normalized.lastIndexOf(marker);
    if (markerIndex >= 0) return normalized.slice(markerIndex);
    return normalized.split('/').filter(Boolean).slice(-2).join('/') || normalized;
}

function updateVoiceInputDiagnostics(status = state.voiceInputStatusSnapshot || {}) {
    if (!el.voiceInputDiagnostics) return;
    const timings = status.last_timings || {};
    const dependency = status.dependency_available ? 'available' : 'missing';
    const loaded = status.model_loaded ? 'loaded' : 'not loaded';
    const model = status.model || 'unknown';
    const transcript = status.last_transcript ? `${status.last_transcript.length} chars` : '-';
    const issue = state.voiceInputLastIssue || status.last_error || '-';
    el.voiceInputDiagnostics.textContent = [
        `State: ${status.status_code || '-'} | Dependency: ${dependency} | Model: ${loaded} (${model}) | Cache: ${compactCachePath(status.model_cache_dir)}`,
        `Recording: ${formatMs(state.voiceInputLastRecordingMs)} | Upload: ${formatMs(state.voiceInputLastUploadMs)} | Clip: ${formatBytes(state.voiceInputLastBlobBytes)}`,
        `Hands-free: ${handsFreeSensitivity()}% | Silence: ${formatMs(handsFreeSilenceMs())} | Clip: ${formatMs(minRecordingMs())}-${formatMs(maxRecordingMs())}`,
        `Model load: ${formatMs(timings.model_load_ms)} | ASR: ${formatMs(timings.transcribe_ms)} | Transcript: ${transcript}`,
        `Issue: ${issue}`,
    ].join('\n');
}

function microphoneErrorMessage(error) {
    const name = error?.name || '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
        return 'Microphone permission is blocked. Allow microphone access for this site, then try voice input again.';
    }
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
        return 'No microphone was found. Connect or select a microphone, then try voice input again.';
    }
    if (name === 'NotReadableError' || name === 'TrackStartError') {
        return 'Microphone is busy or unavailable. Close other apps using it, then try again.';
    }
    if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
        return 'The selected microphone settings are not available. Check your browser audio input settings.';
    }
    return `Microphone unavailable: ${error?.message || 'unknown browser error'}`;
}

function voicePayloadFailureMessage(payload, fallback) {
    const status = payload?.voice_input_status || {};
    if (status.status_code === 'dependency_missing') {
        return 'Voice input dependency is missing. Install faster-whisper, then restart the app.';
    }
    if (status.status_code === 'model_not_loaded') {
        return 'Voice input model is not loaded. Use Download / Load Voice Input Model before recording.';
    }
    if (status.status_code === 'error' && status.last_error) {
        return `Voice input model error: ${status.last_error}`;
    }
    return payload?.message || fallback;
}

function slowAsrWarning(payload) {
    const transcribeMs = Number(payload?.timings?.transcribe_ms ?? payload?.voice_input_status?.last_timings?.transcribe_ms);
    if (!Number.isFinite(transcribeMs) || transcribeMs < SLOW_ASR_WARNING_MS) return '';
    return `ASR took ${formatMs(transcribeMs)}. On CPU-only machines, use tiny.en or a GPU for lower latency.`;
}

function preferredMimeType() {
    if (!window.MediaRecorder) return '';
    const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
    return options.find(type => MediaRecorder.isTypeSupported(type)) || '';
}

function populateSelect(selectEl, options = [], fallbackOptions = []) {
    if (!selectEl) return;
    const selected = selectEl.value;
    selectEl.innerHTML = '';
    (options.length ? options : fallbackOptions).forEach(option => {
        const node = D.createElement('option');
        node.value = option.id;
        node.textContent = option.label;
        selectEl.appendChild(node);
    });
    if ([...selectEl.options].some(option => option.value === selected)) selectEl.value = selected;
}

function populateChoiceLabels(inputs, options = [], fallbackOptions = []) {
    const labelById = new Map((options.length ? options : fallbackOptions).map(option => [option.id, option.label]));
    [...inputs].forEach(input => {
        const label = D.querySelector(`[data-choice-label="${input.id}"]`);
        if (labelById.has(input.value) && label) label.textContent = labelById.get(input.value);
    });
}

function setCheckedRadioValue(inputs, value) {
    [...inputs].forEach(input => {
        input.checked = input.value === value;
    });
}

function getCheckedRadioValue(inputs, fallback) {
    return [...inputs].find(input => input.checked)?.value || fallback;
}

function updateVoiceInputTuningReadouts({fromDom = true} = {}) {
    state.voiceInputHandsFreeSensitivity = Math.round(clampNumber(
        fromDom ? el.voiceInputSensitivitySlider?.value : state.voiceInputHandsFreeSensitivity,
        1,
        100,
        DEFAULT_HANDS_FREE_SENSITIVITY,
    ));
    state.voiceInputHandsFreeSilenceMs = Math.round(clampNumber(
        fromDom ? el.voiceInputSilenceMsInput?.value : state.voiceInputHandsFreeSilenceMs,
        250,
        5000,
        DEFAULT_HANDS_FREE_SILENCE_MS,
    ));
    state.voiceInputMinRecordingMs = Math.round(clampNumber(
        fromDom ? el.voiceInputMinRecordingMsInput?.value : state.voiceInputMinRecordingMs,
        150,
        3000,
        DEFAULT_MIN_RECORDING_MS,
    ));
    state.voiceInputMaxRecordingMs = Math.max(
        state.voiceInputMinRecordingMs,
        Math.round(clampNumber(
            fromDom ? el.voiceInputMaxRecordingMsInput?.value : state.voiceInputMaxRecordingMs,
            1000,
            30000,
            DEFAULT_MAX_RECORDING_MS,
        )),
    );
    if (el.voiceInputSensitivitySlider) el.voiceInputSensitivitySlider.value = String(state.voiceInputHandsFreeSensitivity);
    if (el.voiceInputSensitivityVal) el.voiceInputSensitivityVal.textContent = `${state.voiceInputHandsFreeSensitivity}%`;
    if (el.voiceInputSilenceMsInput) el.voiceInputSilenceMsInput.value = String(state.voiceInputHandsFreeSilenceMs);
    if (el.voiceInputMinRecordingMsInput) el.voiceInputMinRecordingMsInput.value = String(state.voiceInputMinRecordingMs);
    if (el.voiceInputMaxRecordingMsInput) el.voiceInputMaxRecordingMsInput.value = String(state.voiceInputMaxRecordingMs);
    updateVoiceInputDiagnostics();
}

function setVoiceButtonState() {
    if (!el.voiceInputMenuBtn) return;
    const disabled = !state.voiceInputEnabled || !state.voiceInputCanTranscribe || state.voiceInputProvider === 'disabled';
    el.voiceInputMenuBtn.disabled = disabled;
    el.voiceInputMenuBtn.classList.toggle('is-recording', state.voiceInputRecording);
    el.voiceInputMenuBtn.classList.toggle('is-listening', state.voiceInputHandsFreeArmed && !state.voiceInputRecording);
    el.voiceInputMenuBtn.setAttribute('aria-pressed', state.voiceInputRecording || state.voiceInputHandsFreeArmed ? 'true' : 'false');
    if (state.voiceInputRecording) {
        el.voiceInputMenuBtn.title = 'Stop recording';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Stop recording');
    } else if (state.voiceInputHandsFreeArmed) {
        el.voiceInputMenuBtn.title = 'Stop hands-free listening';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Stop hands-free listening');
    } else if (state.voiceInputMode === 'hands_free') {
        el.voiceInputMenuBtn.title = disabled ? 'Voice input unavailable' : 'Arm hands-free listening';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Arm hands-free listening');
    } else {
        el.voiceInputMenuBtn.title = disabled ? 'Voice input unavailable' : 'Start voice input';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Start voice input');
    }
}

export function populateVoiceInputSettings(data = {}) {
    const status = data.voice_input_status || data || {};
    state.voiceInputStatusSnapshot = status;
    populateSelect(el.voiceInputProviderSelect, status.provider_options, [
        {id: 'disabled', label: 'Disabled'},
        {id: 'local_faster_whisper', label: 'Local faster-whisper'},
    ]);
    populateChoiceLabels(el.voiceInputModeInputs, status.mode_options, [
        {id: 'push_to_talk', label: 'Push to talk'},
        {id: 'hands_free', label: 'Hands-free'},
    ]);
    populateChoiceLabels(el.voiceInputSubmitModeInputs, status.submit_options, [
        {id: 'preview', label: 'Preview before send'},
        {id: 'auto_submit', label: 'Auto-send transcript'},
    ]);

    state.voiceInputProvider = status.provider || data.voice_input_provider || 'disabled';
    state.voiceInputEnabled = Boolean(status.enabled ?? data.voice_input_enabled);
    state.voiceInputMode = status.mode || data.voice_input_mode || 'push_to_talk';
    state.voiceInputSubmitMode = status.submit_mode || data.voice_input_submit_mode || 'preview';
    state.voiceInputCanTranscribe = Boolean(status.can_transcribe);
    state.voiceInputHandsFreeSensitivity = status.hands_free_sensitivity ?? data.voice_input_hands_free_sensitivity ?? DEFAULT_HANDS_FREE_SENSITIVITY;
    state.voiceInputHandsFreeSilenceMs = status.hands_free_silence_ms ?? data.voice_input_hands_free_silence_ms ?? DEFAULT_HANDS_FREE_SILENCE_MS;
    state.voiceInputMinRecordingMs = status.min_recording_ms ?? data.voice_input_min_recording_ms ?? DEFAULT_MIN_RECORDING_MS;
    state.voiceInputMaxRecordingMs = status.max_recording_ms ?? data.voice_input_max_recording_ms ?? DEFAULT_MAX_RECORDING_MS;

    if (el.voiceInputProviderSelect) el.voiceInputProviderSelect.value = state.voiceInputProvider;
    setCheckedRadioValue(el.voiceInputModeInputs, state.voiceInputMode);
    setCheckedRadioValue(el.voiceInputSubmitModeInputs, state.voiceInputSubmitMode);
    updateVoiceInputTuningReadouts({fromDom: false});
    if (el.voiceInputModelInput) el.voiceInputModelInput.value = status.model || data.voice_input_model || 'tiny.en';
    if (el.voiceInputLanguageInput) el.voiceInputLanguageInput.value = status.language || data.voice_input_language || 'auto';
    if (el.voiceInputStatus) {
        el.voiceInputStatus.textContent = status.message || 'Voice input status unavailable.';
        el.voiceInputStatus.style.color = status.can_transcribe ? 'var(--cyan)' : 'var(--comment)';
    }
    if (!status.last_error && status.status_code === 'ready') state.voiceInputLastIssue = '';
    if (el.downloadVoiceInputModelBtn) {
        el.downloadVoiceInputModelBtn.disabled = !status.can_load_model || status.model_loaded;
        el.downloadVoiceInputModelBtn.textContent = status.model_loaded ? 'Voice Input Model Loaded' : 'Download / Load Voice Input Model';
    }
    updateVoiceInputDiagnostics(status);
    setVoiceButtonState();
}

export async function refreshVoiceInputStatus() {
    try {
        const response = await fetchWithConnectionState('/voice_input_status');
        if (!response.ok) return null;
        const data = await response.json();
        populateVoiceInputSettings(data);
        return data;
    } catch (error) {
        voiceStatusMessage(`Voice input status unavailable: ${error.message}`, 'var(--yellow)');
        return null;
    }
}

async function saveVoiceInputSettings() {
    const provider = el.voiceInputProviderSelect?.value || 'disabled';
    const data = {
        provider,
        enabled: provider !== 'disabled',
        mode: getCheckedRadioValue(el.voiceInputModeInputs, 'push_to_talk'),
        submit_mode: getCheckedRadioValue(el.voiceInputSubmitModeInputs, 'preview'),
        model: el.voiceInputModelInput?.value || 'tiny.en',
        language: el.voiceInputLanguageInput?.value || 'auto',
        hands_free_sensitivity: handsFreeSensitivity(),
        hands_free_silence_ms: handsFreeSilenceMs(),
        min_recording_ms: minRecordingMs(),
        max_recording_ms: maxRecordingMs(),
    };
    const response = await fetchWithConnectionState('/set_voice_input', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
    });
    if (!response.ok) {
        voiceStatusMessage(`Voice input save failed: HTTP ${response.status}`, 'var(--yellow)');
        return null;
    }
    const payload = await response.json();
    populateVoiceInputSettings(payload);
    voiceStatusMessage(payload.message || 'Voice input settings saved.', payload.can_transcribe ? 'var(--cyan)' : 'var(--comment)', {clearIssue: true});
    return payload;
}

async function downloadVoiceInputModel() {
    const saved = await saveVoiceInputSettings();
    if (!saved || !saved.can_load_model) return;
    const ok = window.confirm(`Download/load the voice input model '${saved.model}' now? If it is not cached, this may download model files.`);
    if (!ok) return;
    if (el.downloadVoiceInputModelBtn) {
        el.downloadVoiceInputModelBtn.disabled = true;
        el.downloadVoiceInputModelBtn.textContent = 'Loading...';
    }
    voiceStatusMessage('Loading voice input model...');
    try {
        const response = await fetchWithConnectionState('/preload_voice_input_model', {method: 'POST'});
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            voiceStatusMessage(voicePayloadFailureMessage(payload, `Voice input model load failed: HTTP ${response.status}`), 'var(--yellow)', {issue: true});
            if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
            return;
        }
        populateVoiceInputSettings(payload);
        voiceStatusMessage(payload.message || 'Voice input model loaded.', 'var(--cyan)', {clearIssue: true});
    } catch (error) {
        voiceStatusMessage(`Voice input model load failed before the backend responded: ${error.message}`, 'var(--yellow)', {issue: true});
        if (el.downloadVoiceInputModelBtn) {
            el.downloadVoiceInputModelBtn.disabled = false;
            el.downloadVoiceInputModelBtn.textContent = 'Download / Load Voice Input Model';
        }
    }
}

async function ensureMicrophoneStream() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error('This browser does not support microphone recording.');
    }
    if (state.voiceInputStream?.active) return state.voiceInputStream;
    state.voiceInputStream = await navigator.mediaDevices.getUserMedia({audio: true});
    return state.voiceInputStream;
}

function stopMicrophoneStream() {
    if (state.voiceInputStream) {
        state.voiceInputStream.getTracks().forEach(track => track.stop());
        state.voiceInputStream = null;
    }
    state.voiceInputAudioSource?.disconnect?.();
    state.voiceInputAudioSource = null;
    state.voiceInputAnalyser?.disconnect?.();
    state.voiceInputAnalyser = null;
    if (state.voiceInputAudioContext) {
        state.voiceInputAudioContext.close();
        state.voiceInputAudioContext = null;
    }
}

function stopActiveVoiceInput(message = '') {
    if (state.voiceInputHandsFreeArmed) {
        stopHandsFree(message || 'Hands-free listening stopped.');
    } else if (state.voiceInputRecording) {
        stopRecording();
        if (message) voiceStatusMessage(message);
    } else {
        stopMicrophoneStream();
    }
}

function cancelHandsFreeMonitor() {
    if (state.voiceInputMonitorFrame) cancelAnimationFrame(state.voiceInputMonitorFrame);
    state.voiceInputMonitorFrame = null;
}

function recordingDurationMs() {
    return performance.now() - state.voiceInputRecordingStartedAt;
}

async function transcribeVoiceBlob(blob) {
    state.voiceInputLastBlobBytes = blob?.size || 0;
    updateVoiceInputDiagnostics();
    if (!blob || blob.size === 0) {
        voiceStatusMessage('Recorded audio was empty. Check microphone permission and input level, then try again.', 'var(--yellow)', {issue: true});
        return;
    }
    voiceStatusMessage('Transcribing voice input...');
    const formData = new FormData();
    formData.append('audio', blob, `voice-${Date.now()}.webm`);
    let payload = null;
    try {
        const uploadStartedAt = performance.now();
        const response = await fetchWithConnectionState('/transcribe_voice', {method: 'POST', body: formData});
        state.voiceInputLastUploadMs = performance.now() - uploadStartedAt;
        payload = await response.json().catch(() => null);
        if (!response.ok) {
            voiceStatusMessage(voicePayloadFailureMessage(payload, `Voice transcription failed: HTTP ${response.status}`), 'var(--yellow)', {issue: true});
            if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
            else updateVoiceInputDiagnostics();
            return;
        }
    } catch (error) {
        state.voiceInputLastUploadMs = null;
        updateVoiceInputDiagnostics();
        voiceStatusMessage(`Voice transcription failed before the backend responded: ${error.message}`, 'var(--yellow)', {issue: true});
        return;
    }
    if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
    const transcript = (payload?.transcript || '').trim();
    if (!transcript) {
        voiceStatusMessage(payload?.message || 'No speech detected. Try speaking closer to the microphone, reducing background noise, or using push-to-talk.', 'var(--yellow)', {issue: true});
        return;
    }
    const slowWarning = slowAsrWarning(payload);
    if (state.voiceInputSubmitMode === 'auto_submit') {
        hideTranscriptPreview();
        await submitVoiceTranscript(transcript);
        voiceStatusMessage(slowWarning || 'Voice transcript sent.', slowWarning ? 'var(--yellow)' : 'var(--cyan)', slowWarning ? {issue: true} : {clearIssue: true});
    } else {
        showTranscriptPreview(transcript);
        voiceStatusMessage(slowWarning || 'Transcript ready to review.', slowWarning ? 'var(--yellow)' : 'var(--cyan)', slowWarning ? {issue: true} : {clearIssue: true});
    }
}

async function startRecording(source = 'manual') {
    if (state.voiceInputRecording) return;
    try {
        const stream = await ensureMicrophoneStream();
        const mimeType = preferredMimeType();
        state.voiceInputChunks = [];
        state.voiceInputRecorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
        state.voiceInputRecordingStartedAt = performance.now();
        state.voiceInputRecorder.addEventListener('dataavailable', event => {
            if (event.data && event.data.size > 0) state.voiceInputChunks.push(event.data);
        });
        state.voiceInputRecorder.addEventListener('stop', async () => {
            const duration = recordingDurationMs();
            state.voiceInputLastRecordingMs = duration;
            state.voiceInputRecording = false;
            clearTimeout(state.voiceInputStopTimer);
            setVoiceButtonState();
            if (duration >= minRecordingMs()) {
                const blob = new Blob(state.voiceInputChunks, {type: state.voiceInputRecorder.mimeType || 'audio/webm'});
                await transcribeVoiceBlob(blob);
            } else if (source !== 'hands_free') {
                voiceStatusMessage('Recording was too short. Hold the microphone button long enough to capture a full command.', 'var(--yellow)', {issue: true});
            }
            state.voiceInputChunks = [];
            if (!state.voiceInputHandsFreeArmed) stopMicrophoneStream();
        });
        state.voiceInputRecorder.start();
        state.voiceInputRecording = true;
        state.voiceInputSilenceStartedAt = 0;
        state.voiceInputStopTimer = setTimeout(() => stopRecording(), maxRecordingMs());
        voiceStatusMessage(source === 'hands_free' ? 'Speech detected. Recording...' : 'Recording voice input...');
        setVoiceButtonState();
    } catch (error) {
        if (source === 'hands_free') {
            state.voiceInputHandsFreeArmed = false;
            cancelHandsFreeMonitor();
        }
        stopMicrophoneStream();
        voiceStatusMessage(microphoneErrorMessage(error), 'var(--yellow)', {issue: true});
        setVoiceButtonState();
    }
}

function stopRecording() {
    if (state.voiceInputRecorder && state.voiceInputRecorder.state !== 'inactive') {
        state.voiceInputRecorder.stop();
    }
}

function currentRms() {
    const analyser = state.voiceInputAnalyser;
    if (!analyser) return 0;
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    data.forEach(value => {
        const centered = (value - 128) / 128;
        sum += centered * centered;
    });
    return Math.sqrt(sum / data.length);
}

function monitorHandsFree() {
    if (!state.voiceInputHandsFreeArmed) return;
    const now = performance.now();
    const rms = currentRms();
    const threshold = handsFreeRmsThreshold();
    if (!state.voiceInputRecording && rms > threshold) {
        startRecording('hands_free');
    } else if (state.voiceInputRecording) {
        if (rms <= threshold) {
            if (!state.voiceInputSilenceStartedAt) state.voiceInputSilenceStartedAt = now;
            if (recordingDurationMs() >= minRecordingMs() && now - state.voiceInputSilenceStartedAt >= handsFreeSilenceMs()) {
                stopRecording();
            }
        } else {
            state.voiceInputSilenceStartedAt = 0;
        }
    }
    state.voiceInputMonitorFrame = requestAnimationFrame(monitorHandsFree);
}

async function startHandsFree() {
    try {
        const stream = await ensureMicrophoneStream();
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw new Error('This browser does not support audio level monitoring.');
        state.voiceInputAudioContext = state.voiceInputAudioContext || new AudioContextClass();
        state.voiceInputAudioSource = state.voiceInputAudioContext.createMediaStreamSource(stream);
        state.voiceInputAnalyser = state.voiceInputAudioContext.createAnalyser();
        state.voiceInputAnalyser.fftSize = 512;
        state.voiceInputAudioSource.connect(state.voiceInputAnalyser);
        state.voiceInputHandsFreeArmed = true;
        state.voiceInputMonitorFrame = requestAnimationFrame(monitorHandsFree);
        voiceStatusMessage('Hands-free listening armed.', 'var(--comment)', {clearIssue: true});
        setVoiceButtonState();
    } catch (error) {
        stopMicrophoneStream();
        voiceStatusMessage(microphoneErrorMessage(error), 'var(--yellow)', {issue: true});
    }
}

function stopHandsFree(message = 'Hands-free listening stopped.') {
    state.voiceInputHandsFreeArmed = false;
    cancelHandsFreeMonitor();
    if (state.voiceInputRecording) stopRecording();
    else stopMicrophoneStream();
    if (message) voiceStatusMessage(message);
    setVoiceButtonState();
}

function showTranscriptPreview(transcript) {
    state.voiceInputPendingTranscript = transcript;
    if (el.voiceTranscriptText) el.voiceTranscriptText.textContent = transcript;
    if (el.voiceTranscriptPreview) el.voiceTranscriptPreview.hidden = false;
}

function hideTranscriptPreview() {
    state.voiceInputPendingTranscript = '';
    if (el.voiceTranscriptText) el.voiceTranscriptText.textContent = '';
    if (el.voiceTranscriptPreview) el.voiceTranscriptPreview.hidden = true;
}

async function sendPendingTranscript() {
    const transcript = state.voiceInputPendingTranscript.trim();
    hideTranscriptPreview();
    if (transcript) await submitVoiceTranscript(transcript);
}

function retryVoiceInput() {
    hideTranscriptPreview();
    if (state.voiceInputMode === 'hands_free') {
        if (!state.voiceInputHandsFreeArmed) startHandsFree();
    } else {
        startRecording('manual');
    }
}

function toggleVoiceInput() {
    if (state.voiceInputMode === 'hands_free') {
        if (state.voiceInputHandsFreeArmed) stopHandsFree();
        else startHandsFree();
        return;
    }
    if (state.voiceInputRecording) stopRecording();
    else startRecording('manual');
}

export function initVoiceInputControls({sendUserMessage}) {
    submitVoiceTranscript = sendUserMessage;
    el.saveVoiceInputBtn?.addEventListener('click', saveVoiceInputSettings);
    el.downloadVoiceInputModelBtn?.addEventListener('click', downloadVoiceInputModel);
    el.voiceInputMenuBtn?.addEventListener('click', toggleVoiceInput);
    el.voiceInputModeInputs?.forEach(input => {
        input.addEventListener('change', event => {
            if (state.voiceInputHandsFreeArmed || state.voiceInputRecording) {
                stopActiveVoiceInput('Voice input stopped because settings changed.');
            }
            state.voiceInputMode = event.target.value;
            setVoiceButtonState();
        });
    });
    el.voiceInputSubmitModeInputs?.forEach(input => {
        input.addEventListener('change', event => {
            state.voiceInputSubmitMode = event.target.value;
        });
    });
    el.voiceInputProviderSelect?.addEventListener('change', event => {
        if (state.voiceInputHandsFreeArmed || state.voiceInputRecording) {
            stopActiveVoiceInput('Voice input stopped because settings changed.');
        }
        state.voiceInputProvider = event.target.value;
        state.voiceInputEnabled = event.target.value !== 'disabled';
        setVoiceButtonState();
    });
    [
        el.voiceInputSensitivitySlider,
        el.voiceInputSilenceMsInput,
        el.voiceInputMinRecordingMsInput,
        el.voiceInputMaxRecordingMsInput,
    ].forEach(input => input?.addEventListener('input', () => updateVoiceInputTuningReadouts()));
    el.sendVoiceTranscriptBtn?.addEventListener('click', sendPendingTranscript);
    el.retryVoiceTranscriptBtn?.addEventListener('click', retryVoiceInput);
    el.cancelVoiceTranscriptBtn?.addEventListener('click', hideTranscriptPreview);
    refreshVoiceInputStatus();
}
