import { D, clampNumber, el, fetchWithConnectionState, state } from './context.js';

const DEFAULT_HANDS_FREE_SENSITIVITY = 75;
const DEFAULT_HANDS_FREE_SILENCE_MS = 900;
const DEFAULT_MIN_RECORDING_MS = 450;
const DEFAULT_MAX_RECORDING_MS = 8000;
const DEFAULT_NOISE_FLOOR_RMS = 0;
const DEFAULT_VOICE_INPUT_BEAM_SIZE = 5;
const DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT = false;
const DEFAULT_VOICE_INPUT_VAD_THRESHOLD = 0.5;
const DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS = 500;
const DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS = 400;
const HANDS_FREE_RMS_THRESHOLD_MIN = 0.006;
const HANDS_FREE_RMS_THRESHOLD_MAX = 0.16;
const HANDS_FREE_NOISE_MULTIPLIER_MIN = 1.6;
const HANDS_FREE_NOISE_MULTIPLIER_MAX = 5.0;
const VOICE_INPUT_NOISE_CALIBRATION_MS = 2000;
const SLOW_ASR_WARNING_MS = 2500;
const VOICE_INPUT_TRIM_WINDOW_MS = 20;
const VOICE_INPUT_TRIM_HEAD_PAD_MS = 100;
const VOICE_INPUT_TRIM_TAIL_PAD_MS = 150;
const VOICE_INPUT_TRIM_MIN_REMOVED_MS = 120;
const VOICE_INPUT_PREPROCESS_HIGHPASS_HZ = 100;
const CUSTOM_VOICE_INPUT_MODEL = '__custom__';
const NVIDIA_PARAKEET_PROVIDER = 'local_nvidia_parakeet';
const DEFAULT_NVIDIA_PARAKEET_MODEL = 'nvidia/parakeet-tdt-0.6b-v3';
const FALLBACK_VOICE_INPUT_MODEL_OPTIONS = [
    {id: 'tiny.en', label: 'Fast - tiny.en'},
    {id: 'base.en', label: 'Balanced - base.en'},
    {id: 'small.en', label: 'Accurate - small.en'},
    {id: 'distil-large-v3', label: 'Desktop/GPU - distil-large-v3'},
];
const FALLBACK_NVIDIA_PARAKEET_MODEL_OPTIONS = [
    {id: DEFAULT_NVIDIA_PARAKEET_MODEL, label: 'NVIDIA Parakeet TDT 0.6B v3'},
];

let submitVoiceTranscript = async () => {};
let voiceInputModelLoadPromise = null;
let voiceInputAutoLoadKey = '';

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

function voiceInputNoiseFloorRms() {
    return Number(clampNumber(state.voiceInputNoiseFloorRms, 0, 0.5, DEFAULT_NOISE_FLOOR_RMS).toFixed(4));
}

function voiceInputBeamSize() {
    return Math.round(clampNumber(state.voiceInputBeamSize, 1, 10, DEFAULT_VOICE_INPUT_BEAM_SIZE));
}

function voiceInputVadThreshold() {
    return Number(clampNumber(state.voiceInputVadThreshold, 0.1, 0.9, DEFAULT_VOICE_INPUT_VAD_THRESHOLD).toFixed(2));
}

function voiceInputVadMinSilenceMs() {
    return Math.round(clampNumber(
        state.voiceInputVadMinSilenceMs,
        100,
        3000,
        DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS,
    ));
}

function voiceInputVadSpeechPadMs() {
    return Math.round(clampNumber(
        state.voiceInputVadSpeechPadMs,
        0,
        1000,
        DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS,
    ));
}

function handsFreeRmsThreshold() {
    const ratio = (handsFreeSensitivity() - 1) / 99;
    const floor = voiceInputNoiseFloorRms();
    if (floor > 0) {
        const multiplier = HANDS_FREE_NOISE_MULTIPLIER_MAX
            - (ratio * (HANDS_FREE_NOISE_MULTIPLIER_MAX - HANDS_FREE_NOISE_MULTIPLIER_MIN));
        return clampNumber(floor * multiplier, HANDS_FREE_RMS_THRESHOLD_MIN, HANDS_FREE_RMS_THRESHOLD_MAX, HANDS_FREE_RMS_THRESHOLD_MIN);
    }
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

function formatRms(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return 'auto';
    return number.toFixed(3);
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
    const cached = status.model_cached ? 'cached' : 'not cached';
    const model = status.model || 'unknown';
    const transcript = status.last_transcript ? `${status.last_transcript.length} chars` : '-';
    const issue = state.voiceInputLastIssue || status.last_error || '-';
    const chatTimings = state.voiceInputLastChatTimings || {};
    const processing = [
        state.voiceInputNoiseSuppression ? 'noise suppression' : 'raw noise',
        state.voiceInputEchoCancellation ? 'echo cancel' : 'raw echo',
        state.voiceInputAutoGainControl ? 'auto gain' : 'fixed gain',
        state.voiceInputAudioPreprocessing ? 'high-pass/compress' : 'raw capture',
        state.voiceInputSilenceTrim ? 'trim silence' : 'full clip',
    ].join(', ');
    el.voiceInputDiagnostics.textContent = [
        `State: ${status.status_code || '-'} | Dependency: ${dependency} | Model: ${loaded}, ${cached} (${model}) | Cache: ${compactCachePath(status.model_cache_dir)}`,
        `Recording: ${formatMs(state.voiceInputLastRecordingMs)} | Upload: ${formatMs(state.voiceInputLastUploadMs)} | Clip: ${formatBytes(state.voiceInputLastBlobBytes)}`,
        `Hands-free: ${handsFreeSensitivity()}% | Silence: ${formatMs(handsFreeSilenceMs())} | Clip: ${formatMs(minRecordingMs())}-${formatMs(maxRecordingMs())}`,
        `Microphone: ${processing} | Noise floor: ${formatRms(voiceInputNoiseFloorRms())} | Trigger: ${formatRms(handsFreeRmsThreshold())}`,
        `Recognition: fallback beam ${voiceInputBeamSize()} | VAD ${voiceInputVadThreshold()} | Silence ${formatMs(voiceInputVadMinSilenceMs())} | Padding ${formatMs(voiceInputVadSpeechPadMs())} | Previous text ${state.voiceInputConditionOnPreviousText ? 'on' : 'off'}`,
        `Model load: ${formatMs(timings.model_load_ms)} | ASR: ${formatMs(timings.transcribe_ms)} | Transcript: ${transcript}`,
        `Voice chat: ${formatMs(state.voiceInputLastChatMs)} | LLM: ${formatMs(chatTimings.llm_ms)} | Motion: ${formatMs(chatTimings.motion_apply_ms)}`,
        `Issue: ${issue}`,
    ].join('\n');
}

function voiceInputModelLoadLabel(status = state.voiceInputStatusSnapshot || {}) {
    if (status.model_loaded) return 'Voice Input Model Loaded';
    return status.model_cached ? 'Load Voice Input Model' : 'Download / Load Voice Input Model';
}

function canLoadCachedVoiceInputModel(status = state.voiceInputStatusSnapshot || {}) {
    const requiresDownload = Boolean(status.load_requires_download ?? !status.model_cached);
    return Boolean(status.can_load_model && status.model_cached && !status.model_loaded && !requiresDownload);
}

function shouldAutoLoadHandsFreeModel(status = state.voiceInputStatusSnapshot || {}) {
    return Boolean(
        status.enabled
        && status.provider !== 'disabled'
        && status.mode === 'hands_free'
        && !status.last_error
        && status.status_code !== 'error'
        && canLoadCachedVoiceInputModel(status)
    );
}

function voiceInputModelStateKey(status = state.voiceInputStatusSnapshot || {}) {
    return [
        status.provider || '',
        status.model || '',
        status.model_cache_dir || '',
        status.mode || '',
    ].join('|');
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
        return payload?.message || status.message || 'Voice input dependency is missing. Install the selected provider dependencies, then restart the app.';
    }
    if (status.status_code === 'model_not_loaded') {
        if (status.model_cached) {
            return 'Voice input model is cached but not loaded. Use Load Voice Input Model before recording.';
        }
        return 'Voice input model is not downloaded. Use Download / Load Voice Input Model before recording.';
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

async function submitVoiceTranscriptToChat(transcript) {
    state.voiceInputLastChatMs = null;
    state.voiceInputLastChatTimings = {};
    updateVoiceInputDiagnostics();
    const startedAt = performance.now();
    const result = await submitVoiceTranscript(transcript);
    state.voiceInputLastChatMs = Number.isFinite(result?.elapsed_ms)
        ? result.elapsed_ms
        : Math.max(0, Math.round(performance.now() - startedAt));
    state.voiceInputLastChatTimings = result?.data?.timings || {};
    updateVoiceInputDiagnostics();
    return result;
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

function fallbackVoiceInputModelOptions(provider) {
    if (provider === NVIDIA_PARAKEET_PROVIDER) return FALLBACK_NVIDIA_PARAKEET_MODEL_OPTIONS;
    return FALLBACK_VOICE_INPUT_MODEL_OPTIONS;
}

function defaultVoiceInputModelForProvider(provider) {
    return fallbackVoiceInputModelOptions(provider)[0]?.id || 'tiny.en';
}

function populateVoiceInputModelSelect(model, options = [], provider = state.voiceInputProvider) {
    if (!el.voiceInputModelSelect) return;
    const modelOptions = (options.length ? options : fallbackVoiceInputModelOptions(provider));
    el.voiceInputModelSelect.innerHTML = '';
    modelOptions.forEach(option => {
        const node = D.createElement('option');
        node.value = option.id;
        node.textContent = option.label;
        if (option.description) node.title = option.description;
        el.voiceInputModelSelect.appendChild(node);
    });
    const custom = D.createElement('option');
    custom.value = CUSTOM_VOICE_INPUT_MODEL;
    custom.textContent = 'Custom model...';
    el.voiceInputModelSelect.appendChild(custom);
    el.voiceInputModelSelect.value = modelOptions.some(option => option.id === model)
        ? model
        : CUSTOM_VOICE_INPUT_MODEL;
}

function syncVoiceInputModelSelectFromInput() {
    if (!el.voiceInputModelSelect || !el.voiceInputModelInput) return;
    const model = el.voiceInputModelInput.value.trim();
    const option = [...el.voiceInputModelSelect.options].find(node => node.value === model);
    el.voiceInputModelSelect.value = option ? model : CUSTOM_VOICE_INPUT_MODEL;
}

function selectedVoiceInputModel() {
    const selected = el.voiceInputModelSelect?.value || CUSTOM_VOICE_INPUT_MODEL;
    if (selected && selected !== CUSTOM_VOICE_INPUT_MODEL) return selected;
    const fallback = defaultVoiceInputModelForProvider(state.voiceInputProvider);
    return (el.voiceInputModelInput?.value || fallback).trim() || fallback;
}

async function browseVoiceInputModelPath() {
    if (state.voiceInputHandsFreeArmed || state.voiceInputRecording) {
        stopActiveVoiceInput('Voice input stopped because model selection changed.');
    }
    if (state.voiceInputProvider === NVIDIA_PARAKEET_PROVIDER) {
        voiceStatusMessage('NVIDIA Parakeet uses a NeMo/Hugging Face model ID; local faster-whisper folders do not apply.', 'var(--comment)');
        return;
    }
    try {
        voiceStatusMessage('Choose a local faster-whisper model folder...');
        const response = await fetchWithConnectionState('/browse_voice_input_model_path', {method: 'POST'});
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            voiceStatusMessage(payload?.message || `Model folder selection failed: HTTP ${response.status}`, 'var(--yellow)', {issue: true});
            return;
        }
        if (payload?.status === 'cancelled') {
            voiceStatusMessage(payload.message || 'No model folder selected.');
            return;
        }
        const modelPath = String(payload?.model_path || '').trim();
        if (!modelPath) {
            voiceStatusMessage('Model folder selection did not return a path.', 'var(--yellow)', {issue: true});
            return;
        }
        if (el.voiceInputModelInput) el.voiceInputModelInput.value = modelPath;
        syncVoiceInputModelSelectFromInput();
        voiceStatusMessage(payload.message || 'Voice input model folder selected.', 'var(--cyan)', {clearIssue: true});
    } catch (error) {
        voiceStatusMessage(`Model folder selection failed before the backend responded: ${error.message}`, 'var(--yellow)', {issue: true});
    }
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
    state.voiceInputNoiseFloorRms = Number(clampNumber(
        fromDom ? el.voiceInputNoiseFloorInput?.value : state.voiceInputNoiseFloorRms,
        0,
        0.5,
        DEFAULT_NOISE_FLOOR_RMS,
    ).toFixed(4));
    state.voiceInputBeamSize = Math.round(clampNumber(
        fromDom ? el.voiceInputBeamSizeInput?.value : state.voiceInputBeamSize,
        1,
        10,
        DEFAULT_VOICE_INPUT_BEAM_SIZE,
    ));
    state.voiceInputVadThreshold = Number(clampNumber(
        fromDom ? el.voiceInputVadThresholdInput?.value : state.voiceInputVadThreshold,
        0.1,
        0.9,
        DEFAULT_VOICE_INPUT_VAD_THRESHOLD,
    ).toFixed(2));
    state.voiceInputVadMinSilenceMs = Math.round(clampNumber(
        fromDom ? el.voiceInputVadMinSilenceMsInput?.value : state.voiceInputVadMinSilenceMs,
        100,
        3000,
        DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS,
    ));
    state.voiceInputVadSpeechPadMs = Math.round(clampNumber(
        fromDom ? el.voiceInputVadSpeechPadMsInput?.value : state.voiceInputVadSpeechPadMs,
        0,
        1000,
        DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS,
    ));
    if (fromDom) {
        state.voiceInputNoiseSuppression = Boolean(el.voiceInputNoiseSuppressionCheckbox?.checked);
        state.voiceInputEchoCancellation = Boolean(el.voiceInputEchoCancellationCheckbox?.checked);
        state.voiceInputAutoGainControl = Boolean(el.voiceInputAutoGainControlCheckbox?.checked);
        state.voiceInputAudioPreprocessing = Boolean(el.voiceInputAudioPreprocessingCheckbox?.checked);
        state.voiceInputSilenceTrim = Boolean(el.voiceInputSilenceTrimCheckbox?.checked);
        state.voiceInputConditionOnPreviousText = Boolean(el.voiceInputConditionPreviousCheckbox?.checked);
    }
    if (el.voiceInputSensitivitySlider) el.voiceInputSensitivitySlider.value = String(state.voiceInputHandsFreeSensitivity);
    if (el.voiceInputSensitivityVal) el.voiceInputSensitivityVal.textContent = `${state.voiceInputHandsFreeSensitivity}%`;
    if (el.voiceInputSilenceMsInput) el.voiceInputSilenceMsInput.value = String(state.voiceInputHandsFreeSilenceMs);
    if (el.voiceInputMinRecordingMsInput) el.voiceInputMinRecordingMsInput.value = String(state.voiceInputMinRecordingMs);
    if (el.voiceInputMaxRecordingMsInput) el.voiceInputMaxRecordingMsInput.value = String(state.voiceInputMaxRecordingMs);
    if (el.voiceInputNoiseFloorInput) el.voiceInputNoiseFloorInput.value = String(state.voiceInputNoiseFloorRms);
    if (el.voiceInputBeamSizeInput) el.voiceInputBeamSizeInput.value = String(state.voiceInputBeamSize);
    if (el.voiceInputVadThresholdInput) el.voiceInputVadThresholdInput.value = String(state.voiceInputVadThreshold);
    if (el.voiceInputVadMinSilenceMsInput) el.voiceInputVadMinSilenceMsInput.value = String(state.voiceInputVadMinSilenceMs);
    if (el.voiceInputVadSpeechPadMsInput) el.voiceInputVadSpeechPadMsInput.value = String(state.voiceInputVadSpeechPadMs);
    if (el.voiceInputNoiseSuppressionCheckbox) el.voiceInputNoiseSuppressionCheckbox.checked = state.voiceInputNoiseSuppression;
    if (el.voiceInputEchoCancellationCheckbox) el.voiceInputEchoCancellationCheckbox.checked = state.voiceInputEchoCancellation;
    if (el.voiceInputAutoGainControlCheckbox) el.voiceInputAutoGainControlCheckbox.checked = state.voiceInputAutoGainControl;
    if (el.voiceInputAudioPreprocessingCheckbox) el.voiceInputAudioPreprocessingCheckbox.checked = state.voiceInputAudioPreprocessing;
    if (el.voiceInputSilenceTrimCheckbox) el.voiceInputSilenceTrimCheckbox.checked = state.voiceInputSilenceTrim;
    if (el.voiceInputConditionPreviousCheckbox) el.voiceInputConditionPreviousCheckbox.checked = state.voiceInputConditionOnPreviousText;
    if (el.voiceInputNoiseFloorVal) {
        const floor = voiceInputNoiseFloorRms();
        const threshold = formatRms(handsFreeRmsThreshold());
        el.voiceInputNoiseFloorVal.textContent = floor > 0
            ? `${formatRms(floor)} rms, trigger ${threshold} rms`
            : `auto, trigger ${threshold} rms`;
    }
    updateVoiceInputDiagnostics();
}

function setVoiceButtonState() {
    if (!el.voiceInputMenuBtn) return;
    const canLoadForHandsFree = state.voiceInputMode === 'hands_free' && canLoadCachedVoiceInputModel();
    const disabled = (
        !state.voiceInputEnabled
        || state.voiceInputProvider === 'disabled'
        || Boolean(voiceInputModelLoadPromise)
        || (!state.voiceInputCanTranscribe && !canLoadForHandsFree)
    );
    el.voiceInputMenuBtn.disabled = disabled;
    el.voiceInputMenuBtn.classList.toggle('is-recording', state.voiceInputRecording);
    el.voiceInputMenuBtn.classList.toggle('is-listening', state.voiceInputHandsFreeArmed && !state.voiceInputRecording);
    el.voiceInputMenuBtn.setAttribute('aria-pressed', state.voiceInputRecording || state.voiceInputHandsFreeArmed ? 'true' : 'false');
    if (voiceInputModelLoadPromise) {
        el.voiceInputMenuBtn.title = 'Loading voice input model';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Loading voice input model');
    } else if (state.voiceInputRecording) {
        el.voiceInputMenuBtn.title = 'Stop recording';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Stop recording');
    } else if (state.voiceInputHandsFreeArmed) {
        el.voiceInputMenuBtn.title = 'Stop hands-free listening';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Stop hands-free listening');
    } else if (canLoadForHandsFree) {
        el.voiceInputMenuBtn.title = 'Load cached model and arm hands-free listening';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Load cached model and arm hands-free listening');
    } else if (state.voiceInputMode === 'hands_free') {
        el.voiceInputMenuBtn.title = disabled ? 'Voice input unavailable' : 'Arm hands-free listening';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Arm hands-free listening');
    } else {
        el.voiceInputMenuBtn.title = disabled ? 'Voice input unavailable' : 'Start voice input';
        el.voiceInputMenuBtn.setAttribute('aria-label', 'Start voice input');
    }
}

function selectVoiceInputMode(value) {
    if (state.voiceInputMode !== value && (state.voiceInputHandsFreeArmed || state.voiceInputRecording)) {
        stopActiveVoiceInput('Voice input stopped because settings changed.');
    }
    state.voiceInputMode = value;
    setVoiceButtonState();
}

export function populateVoiceInputSettings(data = {}, {autoLoadHandsFree = true} = {}) {
    const status = data.voice_input_status || data || {};
    state.voiceInputStatusSnapshot = status;
    populateSelect(el.voiceInputProviderSelect, status.provider_options, [
        {id: 'disabled', label: 'Disabled'},
        {id: 'local_faster_whisper', label: 'Local faster-whisper'},
        {id: NVIDIA_PARAKEET_PROVIDER, label: 'NVIDIA Parakeet (NeMo)'},
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
    state.voiceInputNoiseSuppression = Boolean(status.noise_suppression ?? data.voice_input_noise_suppression ?? true);
    state.voiceInputEchoCancellation = Boolean(status.echo_cancellation ?? data.voice_input_echo_cancellation ?? true);
    state.voiceInputAutoGainControl = Boolean(status.auto_gain_control ?? data.voice_input_auto_gain_control ?? true);
    state.voiceInputNoiseFloorRms = status.noise_floor_rms ?? data.voice_input_noise_floor_rms ?? DEFAULT_NOISE_FLOOR_RMS;
    state.voiceInputAudioPreprocessing = Boolean(status.audio_preprocessing ?? data.voice_input_audio_preprocessing ?? true);
    state.voiceInputSilenceTrim = Boolean(status.silence_trim ?? data.voice_input_silence_trim ?? true);
    state.voiceInputBeamSize = status.beam_size ?? data.voice_input_beam_size ?? DEFAULT_VOICE_INPUT_BEAM_SIZE;
    state.voiceInputConditionOnPreviousText = Boolean(
        status.condition_on_previous_text
        ?? data.voice_input_condition_on_previous_text
        ?? DEFAULT_VOICE_INPUT_CONDITION_ON_PREVIOUS_TEXT,
    );
    state.voiceInputVadThreshold = status.vad_threshold ?? data.voice_input_vad_threshold ?? DEFAULT_VOICE_INPUT_VAD_THRESHOLD;
    state.voiceInputVadMinSilenceMs = status.vad_min_silence_ms ?? data.voice_input_vad_min_silence_ms ?? DEFAULT_VOICE_INPUT_VAD_MIN_SILENCE_MS;
    state.voiceInputVadSpeechPadMs = status.vad_speech_pad_ms ?? data.voice_input_vad_speech_pad_ms ?? DEFAULT_VOICE_INPUT_VAD_SPEECH_PAD_MS;

    if (el.voiceInputProviderSelect) el.voiceInputProviderSelect.value = state.voiceInputProvider;
    setCheckedRadioValue(el.voiceInputModeInputs, state.voiceInputMode);
    setCheckedRadioValue(el.voiceInputSubmitModeInputs, state.voiceInputSubmitMode);
    updateVoiceInputTuningReadouts({fromDom: false});
    const model = status.model || data.voice_input_model || defaultVoiceInputModelForProvider(state.voiceInputProvider);
    populateVoiceInputModelSelect(model, status.model_options || data.voice_input_model_options || [], state.voiceInputProvider);
    if (el.voiceInputModelInput) el.voiceInputModelInput.value = model;
    if (el.voiceInputLanguageInput) el.voiceInputLanguageInput.value = status.language || data.voice_input_language || 'auto';
    if (el.voiceInputStatus) {
        el.voiceInputStatus.textContent = status.message || 'Voice input status unavailable.';
        el.voiceInputStatus.style.color = status.can_transcribe ? 'var(--cyan)' : 'var(--comment)';
    }
    if (!status.last_error && status.status_code === 'ready') state.voiceInputLastIssue = '';
    if (el.downloadVoiceInputModelBtn) {
        el.downloadVoiceInputModelBtn.disabled = !status.can_load_model || status.model_loaded;
        el.downloadVoiceInputModelBtn.textContent = voiceInputModelLoadLabel(status);
    }
    updateVoiceInputDiagnostics(status);
    setVoiceButtonState();
    if (autoLoadHandsFree && shouldAutoLoadHandsFreeModel(status)) {
        setTimeout(() => maybeAutoLoadHandsFreeModel(status), 0);
    }
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

async function saveVoiceInputSettings({autoLoadHandsFree = true} = {}) {
    updateVoiceInputTuningReadouts();
    const provider = el.voiceInputProviderSelect?.value || 'disabled';
    const data = {
        provider,
        enabled: provider !== 'disabled',
        mode: getCheckedRadioValue(el.voiceInputModeInputs, 'push_to_talk'),
        submit_mode: getCheckedRadioValue(el.voiceInputSubmitModeInputs, 'preview'),
        model: selectedVoiceInputModel(),
        language: el.voiceInputLanguageInput?.value || 'auto',
        hands_free_sensitivity: handsFreeSensitivity(),
        hands_free_silence_ms: handsFreeSilenceMs(),
        min_recording_ms: minRecordingMs(),
        max_recording_ms: maxRecordingMs(),
        noise_suppression: state.voiceInputNoiseSuppression,
        echo_cancellation: state.voiceInputEchoCancellation,
        auto_gain_control: state.voiceInputAutoGainControl,
        noise_floor_rms: voiceInputNoiseFloorRms(),
        audio_preprocessing: state.voiceInputAudioPreprocessing,
        silence_trim: state.voiceInputSilenceTrim,
        beam_size: voiceInputBeamSize(),
        condition_on_previous_text: state.voiceInputConditionOnPreviousText,
        vad_threshold: voiceInputVadThreshold(),
        vad_min_silence_ms: voiceInputVadMinSilenceMs(),
        vad_speech_pad_ms: voiceInputVadSpeechPadMs(),
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
    populateVoiceInputSettings(payload, {autoLoadHandsFree});
    voiceStatusMessage(payload.message || 'Voice input settings saved.', payload.can_transcribe ? 'var(--cyan)' : 'var(--comment)', {clearIssue: true});
    return payload;
}

async function preloadVoiceInputModel({status = state.voiceInputStatusSnapshot || {}, allowDownload = false, reason = 'manual'} = {}) {
    if (!status.can_load_model) return null;
    const requiresDownload = Boolean(status.load_requires_download ?? !status.model_cached);
    if (requiresDownload && !allowDownload) return null;
    if (voiceInputModelLoadPromise) return voiceInputModelLoadPromise;
    const loadingMessage = requiresDownload
        ? 'Downloading voice input model...'
        : (reason === 'hands_free_auto'
            ? 'Loading cached voice input model for hands-free...'
            : 'Loading cached voice input model...');
    voiceInputModelLoadPromise = (async () => {
        try {
            const response = await fetchWithConnectionState('/preload_voice_input_model', {method: 'POST'});
            const payload = await response.json().catch(() => null);
            if (!response.ok) {
                voiceStatusMessage(voicePayloadFailureMessage(payload, `Voice input model load failed: HTTP ${response.status}`), 'var(--yellow)', {issue: true});
                if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
                return null;
            }
            populateVoiceInputSettings(payload);
            voiceStatusMessage(payload.message || 'Voice input model loaded.', 'var(--cyan)', {clearIssue: true});
            return payload;
        } catch (error) {
            voiceStatusMessage(`Voice input model load failed before the backend responded: ${error.message}`, 'var(--yellow)', {issue: true});
            if (el.downloadVoiceInputModelBtn) {
                el.downloadVoiceInputModelBtn.disabled = false;
                el.downloadVoiceInputModelBtn.textContent = voiceInputModelLoadLabel(status);
            }
            return null;
        } finally {
            voiceInputModelLoadPromise = null;
            setVoiceButtonState();
        }
    })();
    setVoiceButtonState();
    if (el.downloadVoiceInputModelBtn) {
        el.downloadVoiceInputModelBtn.disabled = true;
        el.downloadVoiceInputModelBtn.textContent = 'Loading...';
    }
    voiceStatusMessage(loadingMessage);
    return voiceInputModelLoadPromise;
}

function maybeAutoLoadHandsFreeModel(status = state.voiceInputStatusSnapshot || {}) {
    if (!shouldAutoLoadHandsFreeModel(status) || voiceInputModelLoadPromise) return;
    const key = voiceInputModelStateKey(status);
    if (voiceInputAutoLoadKey === key) return;
    voiceInputAutoLoadKey = key;
    preloadVoiceInputModel({status, allowDownload: false, reason: 'hands_free_auto'});
}

async function downloadVoiceInputModel() {
    const saved = await saveVoiceInputSettings({autoLoadHandsFree: false});
    if (!saved || !saved.can_load_model) return;
    const requiresDownload = Boolean(saved.load_requires_download ?? !saved.model_cached);
    if (requiresDownload) {
        const ok = window.confirm(`Download and load the voice input model '${saved.model}' now? This may download model files.`);
        if (!ok) return;
    }
    await preloadVoiceInputModel({status: saved, allowDownload: true, reason: 'manual'});
}

function microphoneAudioConstraints() {
    return {
        noiseSuppression: {ideal: Boolean(state.voiceInputNoiseSuppression)},
        echoCancellation: {ideal: Boolean(state.voiceInputEchoCancellation)},
        autoGainControl: {ideal: Boolean(state.voiceInputAutoGainControl)},
    };
}

async function ensureMicrophoneStream() {
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        throw new Error('This browser does not support microphone recording.');
    }
    if (state.voiceInputStream?.active) return state.voiceInputStream;
    state.voiceInputStream = await navigator.mediaDevices.getUserMedia({audio: microphoneAudioConstraints()});
    return state.voiceInputStream;
}

function cleanupVoiceInputRecordingPipeline() {
    const cleanup = state.voiceInputRecordingCleanup;
    state.voiceInputRecordingCleanup = null;
    if (typeof cleanup === 'function') cleanup();
}

function voiceInputPreprocessingEnabled() {
    return Boolean(state.voiceInputAudioPreprocessing);
}

function voiceInputSilenceTrimEnabled() {
    return Boolean(state.voiceInputSilenceTrim);
}

async function createVoiceInputRecordingPipeline(stream) {
    if (!voiceInputPreprocessingEnabled()) return {stream, cleanup: null};
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return {stream, cleanup: null};
    const context = new AudioContextClass();
    if (!context.createMediaStreamDestination) {
        await context.close?.();
        return {stream, cleanup: null};
    }
    try {
        const source = context.createMediaStreamSource(stream);
        const highpass = context.createBiquadFilter();
        highpass.type = 'highpass';
        highpass.frequency.value = VOICE_INPUT_PREPROCESS_HIGHPASS_HZ;
        highpass.Q.value = 0.7;

        const compressor = context.createDynamicsCompressor();
        compressor.threshold.value = -32;
        compressor.knee.value = 24;
        compressor.ratio.value = 6;
        compressor.attack.value = 0.003;
        compressor.release.value = 0.18;

        const destination = context.createMediaStreamDestination();
        source.connect(highpass);
        highpass.connect(compressor);
        compressor.connect(destination);
        return {
            stream: destination.stream,
            cleanup: () => {
                try { source.disconnect(); } catch { /* already disconnected */ }
                try { highpass.disconnect(); } catch { /* already disconnected */ }
                try { compressor.disconnect(); } catch { /* already disconnected */ }
                context.close?.();
            },
        };
    } catch (error) {
        try {
            await context.close?.();
        } catch { /* ignore close failure on unsupported browsers */ }
        console.debug('Voice input preprocessing unavailable:', error);
        return {stream, cleanup: null};
    }
}

function stopMicrophoneStream() {
    cleanupVoiceInputRecordingPipeline();
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

function trimRmsThreshold() {
    const floor = voiceInputNoiseFloorRms();
    const adaptive = floor > 0 ? floor * 2.5 : 0.012;
    return clampNumber(adaptive, 0.008, 0.12, 0.012);
}

function monoWindowRms(buffer, startFrame, endFrame) {
    const channelCount = Math.max(1, buffer.numberOfChannels || 1);
    let sum = 0;
    let count = 0;
    for (let channel = 0; channel < channelCount; channel += 1) {
        const data = buffer.getChannelData(channel);
        for (let index = startFrame; index < endFrame; index += 1) {
            const value = data[index] || 0;
            sum += value * value;
            count += 1;
        }
    }
    return count ? Math.sqrt(sum / count) : 0;
}

function speechTrimRange(buffer) {
    const sampleRate = buffer.sampleRate || 48000;
    const totalFrames = buffer.length || 0;
    const windowFrames = Math.max(1, Math.round(sampleRate * VOICE_INPUT_TRIM_WINDOW_MS / 1000));
    const threshold = trimRmsThreshold();
    let firstSpeechFrame = null;
    let lastSpeechFrame = null;
    for (let start = 0; start < totalFrames; start += windowFrames) {
        const end = Math.min(totalFrames, start + windowFrames);
        if (monoWindowRms(buffer, start, end) > threshold) {
            if (firstSpeechFrame === null) firstSpeechFrame = start;
            lastSpeechFrame = end;
        }
    }
    if (firstSpeechFrame === null || lastSpeechFrame === null) return null;
    const headPad = Math.round(sampleRate * VOICE_INPUT_TRIM_HEAD_PAD_MS / 1000);
    const tailPad = Math.round(sampleRate * VOICE_INPUT_TRIM_TAIL_PAD_MS / 1000);
    const startFrame = Math.max(0, firstSpeechFrame - headPad);
    const endFrame = Math.min(totalFrames, lastSpeechFrame + tailPad);
    const removedMs = Math.round((totalFrames - (endFrame - startFrame)) / sampleRate * 1000);
    if (removedMs < VOICE_INPUT_TRIM_MIN_REMOVED_MS) return null;
    if (endFrame <= startFrame) return null;
    return {startFrame, endFrame};
}

function writeAscii(view, offset, text) {
    for (let index = 0; index < text.length; index += 1) {
        view.setUint8(offset + index, text.charCodeAt(index));
    }
}

function encodeAudioBufferRangeToWav(buffer, range) {
    const sampleRate = buffer.sampleRate || 48000;
    const channelCount = Math.max(1, buffer.numberOfChannels || 1);
    const startFrame = range.startFrame;
    const frameCount = Math.max(0, range.endFrame - range.startFrame);
    const bytesPerSample = 2;
    const blockAlign = channelCount * bytesPerSample;
    const dataBytes = frameCount * blockAlign;
    const arrayBuffer = new ArrayBuffer(44 + dataBytes);
    const view = new DataView(arrayBuffer);

    writeAscii(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataBytes, true);
    writeAscii(view, 8, 'WAVE');
    writeAscii(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, channelCount, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, 'data');
    view.setUint32(40, dataBytes, true);

    let offset = 44;
    const channels = Array.from({length: channelCount}, (_, channel) => buffer.getChannelData(channel));
    for (let frame = 0; frame < frameCount; frame += 1) {
        const sourceFrame = startFrame + frame;
        for (let channel = 0; channel < channelCount; channel += 1) {
            const sample = Math.max(-1, Math.min(1, channels[channel][sourceFrame] || 0));
            view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
            offset += bytesPerSample;
        }
    }
    return arrayBuffer;
}

async function trimVoiceInputSilence(blob) {
    if (!voiceInputSilenceTrimEnabled() || !blob || !blob.arrayBuffer) return null;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;
    const context = new AudioContextClass();
    try {
        const buffer = await context.decodeAudioData(await blob.arrayBuffer());
        const range = speechTrimRange(buffer);
        if (!range) return null;
        const wav = encodeAudioBufferRangeToWav(buffer, range);
        return new Blob([wav], {type: 'audio/wav'});
    } catch (error) {
        console.debug('Voice input silence trim skipped:', error);
        return null;
    } finally {
        try {
            await context.close?.();
        } catch { /* ignore close failure on unsupported browsers */ }
    }
}

async function prepareVoiceBlobForUpload(blob) {
    if (!voiceInputSilenceTrimEnabled()) return {blob, filename: `voice-${Date.now()}.webm`};
    voiceStatusMessage('Preparing voice input...');
    const trimmed = await trimVoiceInputSilence(blob);
    if (!trimmed) return {blob, filename: `voice-${Date.now()}.webm`};
    return {blob: trimmed, filename: `voice-${Date.now()}.wav`};
}

// Pure upload+transcribe helper. Returns the parsed payload on success, or
// null if the audio blob was empty, the request failed, or the backend
// returned a non-OK status. Surfaces user-facing error messages but does
// NOT touch the transcript preview, auto-submit logic, or any behavior
// that depends on what the caller wants to do with the transcript. This
// seam exists so callers that should NOT auto-submit (e.g. a future test
// transcription button) can reuse the network path without re-implementing
// it. Behavior preserved for the existing transcribeVoiceBlob caller.
async function requestVoiceTranscription(blob, filename, message) {
    state.voiceInputLastBlobBytes = blob?.size || 0;
    updateVoiceInputDiagnostics();
    if (!blob || blob.size === 0) {
        voiceStatusMessage('Recorded audio was empty. Check microphone permission and input level, then try again.', 'var(--yellow)', {issue: true});
        return null;
    }
    voiceStatusMessage(message || 'Transcribing voice input...');
    const formData = new FormData();
    formData.append('audio', blob, filename || `voice-${Date.now()}.webm`);
    try {
        const uploadStartedAt = performance.now();
        const response = await fetchWithConnectionState('/transcribe_voice', {method: 'POST', body: formData});
        state.voiceInputLastUploadMs = performance.now() - uploadStartedAt;
        const payload = await response.json().catch(() => null);
        if (!response.ok) {
            voiceStatusMessage(voicePayloadFailureMessage(payload, `Voice transcription failed: HTTP ${response.status}`), 'var(--yellow)', {issue: true});
            if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
            else updateVoiceInputDiagnostics();
            return null;
        }
        return payload;
    } catch (error) {
        state.voiceInputLastUploadMs = null;
        updateVoiceInputDiagnostics();
        voiceStatusMessage(`Voice transcription failed before the backend responded: ${error.message}`, 'var(--yellow)', {issue: true});
        return null;
    }
}

async function transcribeVoiceBlob(blob) {
    const prepared = await prepareVoiceBlobForUpload(blob);
    const payload = await requestVoiceTranscription(prepared.blob, prepared.filename, 'Transcribing voice input...');
    if (!payload) return;
    if (payload?.voice_input_status) populateVoiceInputSettings(payload.voice_input_status);
    const transcript = (payload?.transcript || '').trim();
    if (!transcript) {
        voiceStatusMessage(payload?.message || 'No speech detected. Try speaking closer to the microphone, reducing background noise, or using push-to-talk.', 'var(--yellow)', {issue: true});
        return;
    }
    const slowWarning = slowAsrWarning(payload);
    if (state.voiceInputSubmitMode === 'auto_submit') {
        hideTranscriptPreview();
        await submitVoiceTranscriptToChat(transcript);
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
        const recordingPipeline = await createVoiceInputRecordingPipeline(stream);
        state.voiceInputRecordingCleanup = recordingPipeline.cleanup;
        const mimeType = preferredMimeType();
        state.voiceInputChunks = [];
        state.voiceInputRecorder = new MediaRecorder(recordingPipeline.stream, mimeType ? {mimeType} : undefined);
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
            cleanupVoiceInputRecordingPipeline();
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

function analyserRms(analyser) {
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

function currentRms() {
    return analyserRms(state.voiceInputAnalyser);
}

function percentile(values, ratio) {
    const sorted = values.filter(value => Number.isFinite(value)).sort((a, b) => a - b);
    if (!sorted.length) return 0;
    const index = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * ratio)));
    return sorted[index];
}

function collectRmsSamples(analyser, durationMs) {
    return new Promise(resolve => {
        const samples = [];
        const startedAt = performance.now();
        const sample = () => {
            samples.push(analyserRms(analyser));
            if (performance.now() - startedAt >= durationMs) {
                resolve(samples);
                return;
            }
            requestAnimationFrame(sample);
        };
        requestAnimationFrame(sample);
    });
}

function calibratedNoiseFloor(samples) {
    return Number(clampNumber(percentile(samples, 0.75), 0, 0.5, DEFAULT_NOISE_FLOOR_RMS).toFixed(4));
}

async function calibrateVoiceInputNoise() {
    if (state.voiceInputRecording) {
        voiceStatusMessage('Stop the current voice recording before room-noise calibration.', 'var(--yellow)', {issue: true});
        return;
    }
    if (state.voiceInputHandsFreeArmed) {
        stopHandsFree('Hands-free listening stopped for room-noise calibration.');
    }
    let context = null;
    let source = null;
    let analyser = null;
    try {
        voiceStatusMessage('Calibrating room noise. Stay quiet for 2 seconds...');
        const stream = await ensureMicrophoneStream();
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw new Error('This browser does not support audio level monitoring.');
        context = new AudioContextClass();
        source = context.createMediaStreamSource(stream);
        analyser = context.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
        const samples = await collectRmsSamples(analyser, VOICE_INPUT_NOISE_CALIBRATION_MS);
        const floor = calibratedNoiseFloor(samples);
        state.voiceInputNoiseFloorRms = floor;
        updateVoiceInputTuningReadouts({fromDom: false});
        const saved = await saveVoiceInputSettings({autoLoadHandsFree: false});
        if (saved) {
            voiceStatusMessage(`Room noise calibrated. Hands-free trigger ${formatRms(handsFreeRmsThreshold())} rms.`, 'var(--cyan)', {clearIssue: true});
        }
    } catch (error) {
        voiceStatusMessage(microphoneErrorMessage(error), 'var(--yellow)', {issue: true});
    } finally {
        source?.disconnect?.();
        analyser?.disconnect?.();
        try {
            await context?.close?.();
        } catch (error) {
            console.debug('Voice input calibration context close failed:', error);
        }
        if (!state.voiceInputHandsFreeArmed && !state.voiceInputRecording) stopMicrophoneStream();
    }
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

async function ensureHandsFreeModelReady() {
    if (state.voiceInputCanTranscribe) return true;
    const status = state.voiceInputStatusSnapshot || {};
    if (canLoadCachedVoiceInputModel(status)) {
        const payload = await preloadVoiceInputModel({status, allowDownload: false, reason: 'hands_free_toggle'});
        return Boolean(payload?.can_transcribe || payload?.voice_input_status?.can_transcribe || state.voiceInputCanTranscribe);
    }
    voiceStatusMessage(
        voicePayloadFailureMessage({voice_input_status: status}, 'Voice input is not ready. Download and load the voice input model before recording.'),
        'var(--yellow)',
        {issue: true},
    );
    return false;
}

async function startHandsFree() {
    try {
        if (!await ensureHandsFreeModelReady()) return;
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
    if (transcript) await submitVoiceTranscriptToChat(transcript);
}

function retryVoiceInput() {
    hideTranscriptPreview();
    if (state.voiceInputMode === 'hands_free') {
        if (!state.voiceInputHandsFreeArmed) startHandsFree();
    } else {
        startRecording('manual');
    }
}

async function toggleVoiceInput() {
    if (state.voiceInputMode === 'hands_free') {
        if (state.voiceInputHandsFreeArmed) stopHandsFree();
        else await startHandsFree();
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
        input.addEventListener('click', event => selectVoiceInputMode(event.target.value));
        input.addEventListener('change', event => selectVoiceInputMode(event.target.value));
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
        const model = defaultVoiceInputModelForProvider(state.voiceInputProvider);
        populateVoiceInputModelSelect(model, [], state.voiceInputProvider);
        if (el.voiceInputModelInput) el.voiceInputModelInput.value = model;
        setVoiceButtonState();
    });
    el.voiceInputModelSelect?.addEventListener('change', event => {
        if (event.target.value !== CUSTOM_VOICE_INPUT_MODEL && el.voiceInputModelInput) {
            el.voiceInputModelInput.value = event.target.value;
        }
    });
    el.voiceInputModelInput?.addEventListener('input', syncVoiceInputModelSelectFromInput);
    el.browseVoiceInputModelBtn?.addEventListener('click', browseVoiceInputModelPath);
    [
        el.voiceInputSensitivitySlider,
        el.voiceInputSilenceMsInput,
        el.voiceInputMinRecordingMsInput,
        el.voiceInputMaxRecordingMsInput,
        el.voiceInputNoiseFloorInput,
        el.voiceInputBeamSizeInput,
        el.voiceInputVadThresholdInput,
        el.voiceInputVadMinSilenceMsInput,
        el.voiceInputVadSpeechPadMsInput,
    ].forEach(input => input?.addEventListener('input', () => updateVoiceInputTuningReadouts()));
    [
        el.voiceInputNoiseSuppressionCheckbox,
        el.voiceInputEchoCancellationCheckbox,
        el.voiceInputAutoGainControlCheckbox,
        el.voiceInputAudioPreprocessingCheckbox,
        el.voiceInputSilenceTrimCheckbox,
        el.voiceInputConditionPreviousCheckbox,
    ].forEach(input => input?.addEventListener('change', () => updateVoiceInputTuningReadouts()));
    el.calibrateVoiceInputNoiseBtn?.addEventListener('click', calibrateVoiceInputNoise);
    el.sendVoiceTranscriptBtn?.addEventListener('click', sendPendingTranscript);
    el.retryVoiceTranscriptBtn?.addEventListener('click', retryVoiceInput);
    el.cancelVoiceTranscriptBtn?.addEventListener('click', hideTranscriptPreview);
    D.addEventListener('backend-connection-restored', refreshVoiceInputStatus);
    refreshVoiceInputStatus();
}
