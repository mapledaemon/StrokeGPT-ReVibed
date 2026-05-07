import { D, el, fetchWithConnectionState, state } from './context.js';

const HANDS_FREE_RMS_THRESHOLD = 0.035;
const HANDS_FREE_SILENCE_MS = 900;
const MIN_RECORDING_MS = 450;
const MAX_RECORDING_MS = 8000;

let submitVoiceTranscript = async () => {};

function voiceStatusMessage(message, color = 'var(--comment)') {
    if (el.voiceInputStatus) {
        el.voiceInputStatus.textContent = message;
        el.voiceInputStatus.style.color = color;
    }
    if (el.statusText) el.statusText.textContent = message;
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
    populateSelect(el.voiceInputProviderSelect, status.provider_options, [
        {id: 'disabled', label: 'Disabled'},
        {id: 'local_faster_whisper', label: 'Local faster-whisper'},
    ]);
    populateSelect(el.voiceInputModeSelect, status.mode_options, [
        {id: 'push_to_talk', label: 'Push to talk'},
        {id: 'hands_free', label: 'Hands-free'},
    ]);
    populateSelect(el.voiceInputSubmitModeSelect, status.submit_options, [
        {id: 'preview', label: 'Preview before send'},
        {id: 'auto_submit', label: 'Auto-send transcript'},
    ]);

    state.voiceInputProvider = status.provider || data.voice_input_provider || 'disabled';
    state.voiceInputEnabled = Boolean(status.enabled ?? data.voice_input_enabled);
    state.voiceInputMode = status.mode || data.voice_input_mode || 'push_to_talk';
    state.voiceInputSubmitMode = status.submit_mode || data.voice_input_submit_mode || 'preview';
    state.voiceInputCanTranscribe = Boolean(status.can_transcribe);

    if (el.voiceInputProviderSelect) el.voiceInputProviderSelect.value = state.voiceInputProvider;
    if (el.voiceInputModeSelect) el.voiceInputModeSelect.value = state.voiceInputMode;
    if (el.voiceInputSubmitModeSelect) el.voiceInputSubmitModeSelect.value = state.voiceInputSubmitMode;
    if (el.voiceInputModelInput) el.voiceInputModelInput.value = status.model || data.voice_input_model || 'tiny.en';
    if (el.voiceInputLanguageInput) el.voiceInputLanguageInput.value = status.language || data.voice_input_language || 'auto';
    if (el.voiceInputStatus) {
        el.voiceInputStatus.textContent = status.message || 'Voice input status unavailable.';
        el.voiceInputStatus.style.color = status.can_transcribe ? 'var(--cyan)' : 'var(--comment)';
    }
    if (el.downloadVoiceInputModelBtn) {
        el.downloadVoiceInputModelBtn.disabled = !status.can_load_model || status.model_loaded;
        el.downloadVoiceInputModelBtn.textContent = status.model_loaded ? 'Voice Input Model Loaded' : 'Download / Load Voice Input Model';
    }
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
        mode: el.voiceInputModeSelect?.value || 'push_to_talk',
        submit_mode: el.voiceInputSubmitModeSelect?.value || 'preview',
        model: el.voiceInputModelInput?.value || 'tiny.en',
        language: el.voiceInputLanguageInput?.value || 'auto',
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
    voiceStatusMessage(payload.message || 'Voice input settings saved.', payload.can_transcribe ? 'var(--cyan)' : 'var(--comment)');
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
    const response = await fetchWithConnectionState('/preload_voice_input_model', {method: 'POST'});
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
        voiceStatusMessage(payload?.message || `Voice input model load failed: HTTP ${response.status}`, 'var(--yellow)');
        if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
        return;
    }
    populateVoiceInputSettings(payload);
    voiceStatusMessage(payload.message || 'Voice input model loaded.', 'var(--cyan)');
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
    if (!blob || blob.size === 0) {
        voiceStatusMessage('Recorded audio was empty.', 'var(--yellow)');
        return;
    }
    voiceStatusMessage('Transcribing voice input...');
    const formData = new FormData();
    formData.append('audio', blob, `voice-${Date.now()}.webm`);
    let payload = null;
    try {
        const response = await fetchWithConnectionState('/transcribe_voice', {method: 'POST', body: formData});
        payload = await response.json().catch(() => null);
        if (!response.ok) {
            voiceStatusMessage(payload?.message || `Voice transcription failed: HTTP ${response.status}`, 'var(--yellow)');
            if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
            return;
        }
    } catch (error) {
        voiceStatusMessage(`Voice transcription failed: ${error.message}`, 'var(--yellow)');
        return;
    }
    if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
    const transcript = (payload?.transcript || '').trim();
    if (!transcript) {
        voiceStatusMessage(payload?.message || 'No speech detected.', 'var(--yellow)');
        return;
    }
    if (state.voiceInputSubmitMode === 'auto_submit') {
        hideTranscriptPreview();
        await submitVoiceTranscript(transcript);
        voiceStatusMessage('Voice transcript sent.', 'var(--cyan)');
    } else {
        showTranscriptPreview(transcript);
        voiceStatusMessage('Transcript ready to review.', 'var(--cyan)');
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
            state.voiceInputRecording = false;
            clearTimeout(state.voiceInputStopTimer);
            setVoiceButtonState();
            if (duration >= MIN_RECORDING_MS) {
                const blob = new Blob(state.voiceInputChunks, {type: state.voiceInputRecorder.mimeType || 'audio/webm'});
                await transcribeVoiceBlob(blob);
            } else if (source !== 'hands_free') {
                voiceStatusMessage('Recording was too short.', 'var(--yellow)');
            }
            state.voiceInputChunks = [];
            if (!state.voiceInputHandsFreeArmed) stopMicrophoneStream();
        });
        state.voiceInputRecorder.start();
        state.voiceInputRecording = true;
        state.voiceInputSilenceStartedAt = 0;
        state.voiceInputStopTimer = setTimeout(() => stopRecording(), MAX_RECORDING_MS);
        voiceStatusMessage(source === 'hands_free' ? 'Speech detected. Recording...' : 'Recording voice input...');
        setVoiceButtonState();
    } catch (error) {
        if (source === 'hands_free') {
            state.voiceInputHandsFreeArmed = false;
            cancelHandsFreeMonitor();
        }
        stopMicrophoneStream();
        voiceStatusMessage(`Microphone unavailable: ${error.message}`, 'var(--yellow)');
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
    if (!state.voiceInputRecording && rms > HANDS_FREE_RMS_THRESHOLD) {
        startRecording('hands_free');
    } else if (state.voiceInputRecording) {
        if (rms <= HANDS_FREE_RMS_THRESHOLD) {
            if (!state.voiceInputSilenceStartedAt) state.voiceInputSilenceStartedAt = now;
            if (recordingDurationMs() >= MIN_RECORDING_MS && now - state.voiceInputSilenceStartedAt >= HANDS_FREE_SILENCE_MS) {
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
        voiceStatusMessage('Hands-free listening armed.');
        setVoiceButtonState();
    } catch (error) {
        stopMicrophoneStream();
        voiceStatusMessage(`Hands-free listening unavailable: ${error.message}`, 'var(--yellow)');
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
    el.voiceInputModeSelect?.addEventListener('change', event => {
        if (state.voiceInputHandsFreeArmed || state.voiceInputRecording) {
            stopActiveVoiceInput('Voice input stopped because settings changed.');
        }
        state.voiceInputMode = event.target.value;
        setVoiceButtonState();
    });
    el.voiceInputSubmitModeSelect?.addEventListener('change', event => {
        state.voiceInputSubmitMode = event.target.value;
    });
    el.voiceInputProviderSelect?.addEventListener('change', event => {
        if (state.voiceInputHandsFreeArmed || state.voiceInputRecording) {
            stopActiveVoiceInput('Voice input stopped because settings changed.');
        }
        state.voiceInputProvider = event.target.value;
        state.voiceInputEnabled = event.target.value !== 'disabled';
        setVoiceButtonState();
    });
    el.sendVoiceTranscriptBtn?.addEventListener('click', sendPendingTranscript);
    el.retryVoiceTranscriptBtn?.addEventListener('click', retryVoiceInput);
    el.cancelVoiceTranscriptBtn?.addEventListener('click', hideTranscriptPreview);
    refreshVoiceInputStatus();
}
