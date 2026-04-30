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
    refreshSystemPromptsBtn: D.getElementById('refresh-system-prompts-btn'),
    systemPromptsStatus: D.getElementById('system-prompts-status'),
    systemPromptChat: D.getElementById('system-prompt-chat'),
    systemPromptRepair: D.getElementById('system-prompt-repair'),
    systemPromptNameThisMove: D.getElementById('system-prompt-name-this-move'),
    systemPromptNameThisMoveSample: D.getElementById('system-prompt-name-this-move-sample'),
    systemPromptProfileConsolidation: D.getElementById('system-prompt-profile-consolidation'),
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
    motionBackendSelect: D.getElementById('motion-backend-select'),
    saveMotionBackendBtn: D.getElementById('save-motion-backend-btn'),
    motionBackendStatus: D.getElementById('motion-backend-status'),
    motionDiagnosticsLevelSelect: D.getElementById('motion-diagnostics-level-select'),
    saveMotionDiagnosticsLevelBtn: D.getElementById('save-motion-diagnostics-level-btn'),
    ollamaDiagnosticsLevelSelect: D.getElementById('ollama-diagnostics-level-select'),
    saveOllamaDiagnosticsLevelBtn: D.getElementById('save-ollama-diagnostics-level-btn'),
    ollamaDiagnosticsOutput: D.getElementById('ollama-diagnostics-output'),
    appMotionBackendBadge: D.getElementById('app-motion-backend-badge'),
    autoMinTimeInput: D.getElementById('auto-min-time'),
    autoMaxTimeInput: D.getElementById('auto-max-time'),
    edgingMinTimeInput: D.getElementById('edging-min-time'),
    edgingMaxTimeInput: D.getElementById('edging-max-time'),
    milkingMinTimeInput: D.getElementById('milking-min-time'),
    milkingMaxTimeInput: D.getElementById('milking-max-time'),
    motionPatternList: D.getElementById('motion-pattern-list'),
    motionPatternStatus: D.getElementById('motion-pattern-status'),
    motionFeedbackHistory: D.getElementById('motion-feedback-history'),
    motionFeedbackAutoDisableCheckbox: D.getElementById('motion-feedback-auto-disable-checkbox'),
    allowLlmEdgeFreestyleCheckbox: D.getElementById('allow-llm-edge-freestyle-checkbox'),
    allowLlmEdgeChatCheckbox: D.getElementById('allow-llm-edge-chat-checkbox'),
    saveLlmEdgePermissionsBtn: D.getElementById('save-llm-edge-permissions-btn'),
    llmEdgePermissionsStatus: D.getElementById('llm-edge-permissions-status'),
    refreshMotionPatternsBtn: D.getElementById('refresh-motion-patterns-btn'),
    importMotionPatternBtn: D.getElementById('import-motion-pattern-btn'),
    openMotionTrainingBtn: D.getElementById('open-motion-training-btn'),
    motionPatternImportInput: D.getElementById('motion-pattern-import-input'),
    motionTrainingDialog: D.getElementById('motion-training-dialog'),
    closeMotionTrainingBtn: D.getElementById('close-motion-training-btn'),
    motionTrainingStatus: D.getElementById('motion-training-status'),
    stopMotionTrainingBtn: D.getElementById('stop-motion-training-btn'),
    motionTrainingPatternList: D.getElementById('motion-training-pattern-list'),
    motionTrainingPatternTitle: D.getElementById('motion-training-pattern-title'),
    motionTrainingPatternMeta: D.getElementById('motion-training-pattern-meta'),
    motionTrainingOriginalPreviewCanvas: D.getElementById('motion-training-original-preview-canvas'),
    motionTrainingPreviewCanvas: D.getElementById('motion-training-preview-canvas'),
    motionTransformSmoothBtn: D.getElementById('motion-transform-smooth-btn'),
    motionTransformHarshenBtn: D.getElementById('motion-transform-harshen-btn'),
    motionTransformDurationDownBtn: D.getElementById('motion-transform-duration-down-btn'),
    motionTransformDurationUpBtn: D.getElementById('motion-transform-duration-up-btn'),
    motionTransformTempoDownBtn: D.getElementById('motion-transform-tempo-down-btn'),
    motionTransformTempoUpBtn: D.getElementById('motion-transform-tempo-up-btn'),
    motionTransformResetBtn: D.getElementById('motion-transform-reset-btn'),
    motionTrainingDurationValue: D.getElementById('motion-training-duration-value'),
    motionTrainingTempoValue: D.getElementById('motion-training-tempo-value'),
    motionTrainingRangeMinInput: D.getElementById('motion-training-range-min'),
    motionTrainingRangeMaxInput: D.getElementById('motion-training-range-max'),
    motionTransformRangeBtn: D.getElementById('motion-transform-range-btn'),
    motionTrainingSaveNameInput: D.getElementById('motion-training-save-name'),
    playMotionTrainingPreviewBtn: D.getElementById('play-motion-training-preview-btn'),
    saveMotionTrainingPatternBtn: D.getElementById('save-motion-training-pattern-btn'),
    motionTrainingEditStatus: D.getElementById('motion-training-edit-status'),
    motionTrainingFeedbackUp: D.getElementById('motion-training-feedback-up'),
    motionTrainingFeedbackNeutral: D.getElementById('motion-training-feedback-neutral'),
    motionTrainingFeedbackDown: D.getElementById('motion-training-feedback-down'),
    setupOverlay: D.getElementById('setup-overlay'),
    setupBox: D.getElementById('setup-box'),
    statusText: D.getElementById('status-text'),
    resetSettingsBtn: D.getElementById('reset-settings-btn'),
    resetSettingsStatus: D.getElementById('reset-settings-status'),
    moodDisplay: D.getElementById('mood-display'),
    handyCylinderRange: D.getElementById('handy-cylinder-range'),
    handyCylinderPosition: D.getElementById('handy-cylinder-position'),
    motionSpeedMeterFill: D.getElementById('motion-speed-meter-fill'),
    motionSpeedMeterValue: D.getElementById('motion-speed-meter-value'),
    motionDepthMeterFill: D.getElementById('motion-depth-meter-fill'),
    motionDepthMeterValue: D.getElementById('motion-depth-meter-value'),
    motionSequenceIndicator: D.getElementById('motion-sequence-indicator'),
    motionDiagnosticsPanel: D.getElementById('motion-diagnostics-panel'),
    typingIndicator: D.getElementById('typing-indicator'),
    chatView: D.getElementById('chat-view'),
    chatMessagesContainer: D.getElementById('chat-messages-container'),
    pfpUploadInput: D.getElementById('pfp-upload'),
    pfpPreview: D.getElementById('ai-pfp-preview'),
    typingIndicatorPfp: D.getElementById('typing-indicator-pfp'),
    toggleSidebarBtn: D.getElementById('toggle-sidebar-btn'),
    toggleMemoryBtn: D.getElementById('toggle-memory-btn'),
    pauseResumeBtn: D.getElementById('pause-resume-btn'),
    imCloseBtn: D.getElementById('im-close-btn'),
    edgingModeBtn: D.getElementById('edging-mode-btn'),
    freestyleModeBtn: D.getElementById('freestyle-mode-btn'),
    edgingTimer: D.getElementById('edging-timer'),
    easterEggOverlay: D.getElementById('easter-egg-overlay'),
    connectionLostBanner: D.getElementById('connection-lost-banner'),
};

export const state = {
    myHandyKey: '',
    myPersonaDescription: '',
    aiName: 'BOT',
    activeModeName: '',
    activeModeElapsedSeconds: null,
    motionPaused: false,
    personaPrompts: [],
    localTtsStylePresets: {},
    audioFetchInProgress: false,
    motionMinDepth: 5,
    motionMaxDepth: 100,
    motionMinSpeed: 10,
    motionMaxSpeed: 80,
    motionBackend: 'hamp',
    motionBackends: [],
    motionDiagnosticsLevel: 'compact',
    ollamaDiagnosticsLevel: 'compact',
    diagnosticsLevels: [],
    motionFeedbackAutoDisable: false,
    allowLlmEdgeInFreestyle: true,
    allowLlmEdgeInChat: true,
    useLongTermMemory: true,
    ollamaDownloadPolling: false,
    localTtsStatusPolling: false,
    systemPromptsLoadedOnce: false,
    motionPatterns: [],
    motionTraining: {state: 'idle', pattern_id: '', pattern_name: ''},
    motionTrainingSelectedPatternId: '',
    motionTrainingPreviewPattern: null,
    motionTrainingOriginalPattern: null,
    motionTrainingEditedPattern: null,
    motionTrainingDirty: false,
    motionObservability: null,
    motionCylinderAnimationStarted: false,
    connectionLost: false,
};

export function setConnectionLost(isLost) {
    const next = Boolean(isLost);
    if (state.connectionLost === next) return;
    state.connectionLost = next;
    if (el.connectionLostBanner) el.connectionLostBanner.hidden = !next;
}

export async function apiCall(endpoint, options = {}) {
    let response;
    try {
        response = await fetch(endpoint, options);
    } catch (error) {
        // Network failure: backend unreachable. Surface the persistent
        // connection-lost banner so the user does not silently keep editing
        // settings, sliders, or feedback that will not save.
        console.error(`API call to ${endpoint} failed:`, error);
        setConnectionLost(true);
        if (el.statusText) el.statusText.textContent = 'Error: Cannot connect to server.';
        return undefined;
    }
    // The backend answered, so the connection is alive even if this specific
    // request returned an HTTP error. Hide the banner and let the caller
    // surface its own error message for the non-OK case.
    setConnectionLost(false);
    if (!response.ok) {
        console.error(`API call to ${endpoint} returned HTTP ${response.status}`);
        if (el.statusText) el.statusText.textContent = `Error: server returned ${response.status}.`;
        return undefined;
    }
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('audio/')) return response.blob();
    return response.json();
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
