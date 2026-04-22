export const D = document;

export const el = {
    userChatInput: D.getElementById('user-chat-input'),
    personaInput: D.getElementById('persona-input'),
    personaPromptSelect: D.getElementById('persona-prompt-select'),
    setPersonaBtn: D.getElementById('set-persona-btn'),
    savePersonaPromptBtn: D.getElementById('save-persona-prompt-btn'),
    aiNameInput: D.getElementById('ai-name-input'),
    setAiNameBtn: D.getElementById('set-ai-name-btn'),
    openSettingsBtn: D.getElementById('open-settings-btn'),
    settingsDialog: D.getElementById('settings-dialog'),
    closeSettingsBtn: D.getElementById('close-settings-btn'),
    settingsTabs: D.querySelectorAll('.settings-tab'),
    settingsPanels: D.querySelectorAll('.settings-panel'),
    ollamaModelSelect: D.getElementById('ollama-model-select'),
    ollamaModelInput: D.getElementById('ollama-model-input'),
    ollamaModelStatus: D.getElementById('ollama-model-status'),
    downloadOllamaModelBtn: D.getElementById('download-ollama-model-btn'),
    refreshOllamaStatusBtn: D.getElementById('refresh-ollama-status-btn'),
    audioProviderSelect: D.getElementById('audio-provider-select'),
    enableAudioCheckbox: D.getElementById('enable-audio-checkbox'),
    elevenLabsPanel: D.getElementById('elevenlabs-settings-panel'),
    localTtsPanel: D.getElementById('local-tts-settings-panel'),
    elevenLabsKeyInput: D.getElementById('elevenlabs-key-input'),
    setElevenLabsKeyButton: D.getElementById('set-elevenlabs-key-button'),
    elevenLabsVoiceSelect: D.getElementById('elevenlabs-voice-select-box'),
    localTtsEngineSelect: D.getElementById('local-tts-engine-select'),
    localTtsStyleSelect: D.getElementById('local-tts-style-select'),
    localTtsPromptPath: D.getElementById('local-tts-prompt-path'),
    localTtsSampleUpload: D.getElementById('local-tts-sample-upload'),
    browseLocalTtsSampleBtn: D.getElementById('browse-local-tts-sample-btn'),
    downloadLocalTtsModelBtn: D.getElementById('download-local-tts-model-button'),
    localTtsExaggeration: D.getElementById('local-tts-exaggeration'),
    localTtsExaggerationVal: D.getElementById('local-tts-exaggeration-val'),
    localTtsCfg: D.getElementById('local-tts-cfg'),
    localTtsCfgVal: D.getElementById('local-tts-cfg-val'),
    localTtsTemperature: D.getElementById('local-tts-temperature'),
    localTtsTemperatureVal: D.getElementById('local-tts-temperature-val'),
    localTtsTopP: D.getElementById('local-tts-top-p'),
    localTtsTopPVal: D.getElementById('local-tts-top-p-val'),
    localTtsMinP: D.getElementById('local-tts-min-p'),
    localTtsMinPVal: D.getElementById('local-tts-min-p-val'),
    localTtsRepetition: D.getElementById('local-tts-repetition'),
    localTtsRepetitionVal: D.getElementById('local-tts-repetition-val'),
    localTtsStatus: D.getElementById('local-tts-status'),
    handyKeyInput: D.getElementById('handy-key-input'),
    saveHandyKeyBtn: D.getElementById('save-handy-key-btn'),
    handyKeyStatus: D.getElementById('handy-key-status'),
    motionDepthMinSlider: D.getElementById('motion-depth-min-slider'),
    motionDepthMaxSlider: D.getElementById('motion-depth-max-slider'),
    motionDepthMinVal: D.getElementById('motion-depth-min-val'),
    motionDepthMaxVal: D.getElementById('motion-depth-max-val'),
    motionSpeedMinSlider: D.getElementById('motion-speed-min-slider'),
    motionSpeedMaxSlider: D.getElementById('motion-speed-max-slider'),
    motionSpeedMinVal: D.getElementById('motion-speed-min-val'),
    motionSpeedMaxVal: D.getElementById('motion-speed-max-val'),
    autoMinTimeInput: D.getElementById('auto-min-time'),
    autoMaxTimeInput: D.getElementById('auto-max-time'),
    edgingMinTimeInput: D.getElementById('edging-min-time'),
    edgingMaxTimeInput: D.getElementById('edging-max-time'),
    milkingMinTimeInput: D.getElementById('milking-min-time'),
    milkingMaxTimeInput: D.getElementById('milking-max-time'),
    motionPatternList: D.getElementById('motion-pattern-list'),
    motionPatternStatus: D.getElementById('motion-pattern-status'),
    refreshMotionPatternsBtn: D.getElementById('refresh-motion-patterns-btn'),
    importMotionPatternBtn: D.getElementById('import-motion-pattern-btn'),
    motionPatternImportInput: D.getElementById('motion-pattern-import-input'),
    motionTrainingStatus: D.getElementById('motion-training-status'),
    stopMotionTrainingBtn: D.getElementById('stop-motion-training-btn'),
    motionTrainingFeedbackUp: D.getElementById('motion-training-feedback-up'),
    motionTrainingFeedbackNeutral: D.getElementById('motion-training-feedback-neutral'),
    motionTrainingFeedbackDown: D.getElementById('motion-training-feedback-down'),
    setupOverlay: D.getElementById('setup-overlay'),
    setupBox: D.getElementById('setup-box'),
    statusText: D.getElementById('status-text'),
    resetSettingsBtn: D.getElementById('reset-settings-btn'),
    resetSettingsStatus: D.getElementById('reset-settings-status'),
    moodDisplay: D.getElementById('mood-display'),
    rhythmCanvas: D.getElementById('rhythm-canvas'),
    typingIndicator: D.getElementById('typing-indicator'),
    chatView: D.getElementById('chat-view'),
    chatMessagesContainer: D.getElementById('chat-messages-container'),
    pfpUploadInput: D.getElementById('pfp-upload'),
    pfpPreview: D.getElementById('ai-pfp-preview'),
    typingIndicatorPfp: D.getElementById('typing-indicator-pfp'),
    toggleSidebarBtn: D.getElementById('toggle-sidebar-btn'),
    imCloseBtn: D.getElementById('im-close-btn'),
    edgingModeBtn: D.getElementById('edging-mode-btn'),
    edgingTimer: D.getElementById('edging-timer'),
    easterEggOverlay: D.getElementById('easter-egg-overlay'),
};

export const state = {
    myHandyKey: '',
    myPersonaDescription: '',
    aiName: 'BOT',
    edgingTimerInterval: null,
    personaPrompts: [],
    localTtsStylePresets: {},
    audioFetchInProgress: false,
    motionMinDepth: 5,
    motionMaxDepth: 100,
    motionMinSpeed: 10,
    motionMaxSpeed: 80,
    ollamaDownloadPolling: false,
    localTtsStatusPolling: false,
    motionPatterns: [],
    motionTraining: {state: 'idle', pattern_id: '', pattern_name: ''},
};

export const ctx = el.rhythmCanvas.getContext('2d');

export async function apiCall(endpoint, options = {}) {
    try {
        const response = await fetch(endpoint, options);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('audio/')) return response.blob();
        return response.json();
    } catch (error) {
        console.error(`API call to ${endpoint} failed:`, error);
        el.statusText.textContent = 'Error: Cannot connect to server.';
        return undefined;
    }
}

export function clampNumber(value, min, max, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, parsed));
}

export function setSliderValue(slider, valueEl, value) {
    slider.value = value;
    valueEl.textContent = slider.value;
}

export function formatElapsed(seconds) {
    if (seconds === null || seconds === undefined) return '';
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    if (total >= 60) return `${Math.floor(total / 60)}m ${total % 60}s`;
    return `${total}s`;
}
