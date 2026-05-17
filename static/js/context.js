export const D = document;
const UI_CLIENT_ID_STORAGE_KEY = 'strokegpt.uiClientId.v1';

function createUiClientId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `ui-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function loadUiClientId() {
    try {
        const existing = globalThis.sessionStorage?.getItem?.(UI_CLIENT_ID_STORAGE_KEY);
        if (existing) return existing;
        const next = createUiClientId();
        globalThis.sessionStorage?.setItem?.(UI_CLIENT_ID_STORAGE_KEY, next);
        return next;
    } catch {
        return createUiClientId();
    }
}

export function getUiClientId() {
    if (!state.uiClientId) state.uiClientId = loadUiClientId();
    return state.uiClientId;
}

export function appendQueryParams(endpoint, params = {}) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null || value === '') continue;
        search.set(key, String(value));
    }
    if (!search.toString()) return endpoint;
    const separator = endpoint.includes('?') ? '&' : '?';
    return `${endpoint}${separator}${search.toString()}`;
}

export const el = {
    userChatInput: D.getElementById('user-chat-input'),
    personaInput: D.getElementById('persona-input'),
    personaPromptSelect: D.getElementById('persona-prompt-select'),
    setPersonaBtn: D.getElementById('set-persona-btn'),
    savePersonaPromptBtn: D.getElementById('save-persona-prompt-btn'),
    aiNameInput: D.getElementById('ai-name-input'),
    setAiNameBtn: D.getElementById('set-ai-name-btn'),
    profileMenu: D.getElementById('profile-menu'),
    profileMenuBtn: D.getElementById('profile-menu-btn'),
    profileMenuPopover: D.getElementById('profile-menu-popover'),
    profileMenuPfp: D.getElementById('profile-menu-pfp'),
    profileMenuSettingsBtns: D.querySelectorAll('[data-settings-target]'),
    profileAboutMenuBtn: D.getElementById('profile-about-menu-btn'),
    aboutDialog: D.getElementById('about-dialog'),
    closeAboutBtn: D.getElementById('close-about-btn'),
    openSettingsBtn: D.getElementById('open-settings-btn'),
    settingsDialog: D.getElementById('settings-dialog'),
    closeSettingsBtn: D.getElementById('close-settings-btn'),
    settingsTabs: D.querySelectorAll('.settings-tab'),
    settingsPanels: D.querySelectorAll('.settings-panel'),
    refreshSystemPromptsBtn: D.getElementById('refresh-system-prompts-btn'),
    userGenitaliaSelect: D.getElementById('user-genitalia-select'),
    userGenitaliaCustomInput: D.getElementById('user-genitalia-custom-input'),
    saveUserGenitaliaBtn: D.getElementById('save-user-genitalia-btn'),
    userGenitaliaStatus: D.getElementById('user-genitalia-status'),
    llmPromptModeSelect: D.getElementById('llm-prompt-mode-select'),
    saveLlmPromptModeBtn: D.getElementById('save-llm-prompt-mode-btn'),
    editLlmPromptStyleBtn: D.getElementById('edit-llm-prompt-style-btn'),
    cancelLlmPromptEditBtn: D.getElementById('cancel-llm-prompt-edit-btn'),
    llmPromptModeStatus: D.getElementById('llm-prompt-mode-status'),
    systemPromptsStatus: D.getElementById('system-prompts-status'),
    systemPromptChat: D.getElementById('system-prompt-chat'),
    systemPromptRepair: D.getElementById('system-prompt-repair'),
    systemPromptNameThisMove: D.getElementById('system-prompt-name-this-move'),
    systemPromptNameThisMoveSample: D.getElementById('system-prompt-name-this-move-sample'),
    systemPromptProfileConsolidation: D.getElementById('system-prompt-profile-consolidation'),
    ollamaModelSelect: D.getElementById('ollama-model-select'),
    ollamaModelList: D.getElementById('ollama-model-list'),
    ollamaModelInput: D.getElementById('ollama-model-input'),
    ollamaModelStatus: D.getElementById('ollama-model-status'),
    ollamaThinkingEnabledCheckbox: D.getElementById('ollama-thinking-enabled-checkbox'),
    saveOllamaThinkingBtn: D.getElementById('save-ollama-thinking-btn'),
    ollamaThinkingStatus: D.getElementById('ollama-thinking-status'),
    downloadOllamaModelBtn: D.getElementById('download-ollama-model-btn'),
    refreshOllamaStatusBtn: D.getElementById('refresh-ollama-status-btn'),
    ollamaModelRequiredDialog: D.getElementById('ollama-model-required-dialog'),
    closeOllamaModelRequiredBtn: D.getElementById('close-ollama-model-required-btn'),
    ollamaModelRequiredMessage: D.getElementById('ollama-model-required-message'),
    ollamaModelRequiredSelect: D.getElementById('ollama-model-required-select'),
    useAvailableOllamaModelBtn: D.getElementById('use-available-ollama-model-btn'),
    downloadRequiredOllamaModelBtn: D.getElementById('download-required-ollama-model-btn'),
    openModelSettingsBtn: D.getElementById('open-model-settings-btn'),
    ollamaModelRequiredStatus: D.getElementById('ollama-model-required-status'),
    topBarIntensityGuideBtn: D.getElementById('top-bar-intensity-guide-btn'),
    topBarVoiceToggleBtn: D.getElementById('top-bar-voice-toggle-btn'),
    topBarAutospeakToggleBtn: D.getElementById('top-bar-autospeak-toggle-btn'),
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
    voiceInputMenuBtn: D.getElementById('voice-input-menu-btn'),
    voiceInputOptionsBtn: D.getElementById('voice-input-options-btn'),
    voiceInputPopover: D.getElementById('voice-input-popover'),
    voiceInputDeviceSelect: D.getElementById('voice-input-device-select'),
    refreshMicrophoneDevicesBtn: D.getElementById('refresh-microphone-devices-btn'),
    voiceInputDeviceStatus: D.getElementById('voice-input-device-status'),
    voiceInputProviderSelect: D.getElementById('voice-input-provider-select'),
    voiceInputModeInputs: D.querySelectorAll('input[name="voice-input-mode"]'),
    voiceInputSubmitModeInputs: D.querySelectorAll('input[name="voice-input-submit-mode"]'),
    voiceInputSensitivitySlider: D.getElementById('voice-input-sensitivity-slider'),
    voiceInputSensitivityVal: D.getElementById('voice-input-sensitivity-val'),
    voiceInputSilenceMsInput: D.getElementById('voice-input-silence-ms-input'),
    voiceInputMinRecordingMsInput: D.getElementById('voice-input-min-recording-ms-input'),
    voiceInputMaxRecordingMsInput: D.getElementById('voice-input-max-recording-ms-input'),
    voiceInputNoiseSuppressionCheckbox: D.getElementById('voice-input-noise-suppression-checkbox'),
    voiceInputEchoCancellationCheckbox: D.getElementById('voice-input-echo-cancellation-checkbox'),
    voiceInputAutoGainControlCheckbox: D.getElementById('voice-input-auto-gain-checkbox'),
    voiceInputNoiseFloorInput: D.getElementById('voice-input-noise-floor-input'),
    voiceInputNoiseFloorVal: D.getElementById('voice-input-noise-floor-val'),
    voiceInputAudioPreprocessingCheckbox: D.getElementById('voice-input-audio-preprocessing-checkbox'),
    voiceInputSilenceTrimCheckbox: D.getElementById('voice-input-silence-trim-checkbox'),
    voiceInputHandsFreeModeActionsCheckbox: D.getElementById('voice-input-hands-free-mode-actions-checkbox'),
    calibrateVoiceInputNoiseBtn: D.getElementById('calibrate-voice-input-noise-btn'),
    voiceInputModelSelect: D.getElementById('voice-input-model-select'),
    voiceInputModelInput: D.getElementById('voice-input-model-input'),
    browseVoiceInputModelBtn: D.getElementById('browse-voice-input-model-btn'),
    voiceInputLanguageInput: D.getElementById('voice-input-language-input'),
    voiceInputBeamSizeInput: D.getElementById('voice-input-beam-size-input'),
    voiceInputConditionPreviousCheckbox: D.getElementById('voice-input-condition-previous-checkbox'),
    voiceInputVadThresholdInput: D.getElementById('voice-input-vad-threshold-input'),
    voiceInputVadMinSilenceMsInput: D.getElementById('voice-input-vad-min-silence-ms-input'),
    voiceInputVadSpeechPadMsInput: D.getElementById('voice-input-vad-speech-pad-ms-input'),
    voiceInputStatus: D.getElementById('voice-input-status'),
    voiceInputDiagnostics: D.getElementById('voice-input-diagnostics'),
    saveVoiceInputBtn: D.getElementById('save-voice-input-btn'),
    downloadVoiceInputModelBtn: D.getElementById('download-voice-input-model-btn'),
    voiceTranscriptPreview: D.getElementById('voice-transcript-preview'),
    voiceTranscriptText: D.getElementById('voice-transcript-text'),
    sendVoiceTranscriptBtn: D.getElementById('send-voice-transcript-btn'),
    retryVoiceTranscriptBtn: D.getElementById('retry-voice-transcript-btn'),
    cancelVoiceTranscriptBtn: D.getElementById('cancel-voice-transcript-btn'),
    handyKeyInput: D.getElementById('handy-key-input'),
    saveHandyKeyBtn: D.getElementById('save-handy-key-btn'),
    handyKeyStatus: D.getElementById('handy-key-status'),
    handyFirmwareSelect: D.getElementById('handy-firmware-select'),
    handyApiV3KeyInput: D.getElementById('handy-api-v3-key-input'),
    saveHandyDeviceConfigBtn: D.getElementById('save-handy-device-config-btn'),
    handyFirmwareStatus: D.getElementById('handy-firmware-status'),
    sidebarHandyKeyInput: D.getElementById('sidebar-handy-key-input'),
    sidebarSaveHandyKeyBtn: D.getElementById('sidebar-save-handy-key-btn'),
    sidebarHandyKeyStatus: D.getElementById('sidebar-handy-key-status'),
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
    motionStyleSelect: D.getElementById('motion-style-select'),
    saveMotionStyleBtn: D.getElementById('save-motion-style-btn'),
    motionStyleStatus: D.getElementById('motion-style-status'),
    motionDirectionNormalRadio: D.getElementById('motion-direction-normal'),
    motionDirectionReverseRadio: D.getElementById('motion-direction-reverse'),
    saveMotionReverseDirectionBtn: D.getElementById('save-motion-reverse-direction-btn'),
    motionReverseDirectionStatus: D.getElementById('motion-reverse-direction-status'),
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
    allowLlmModeActionsChatCheckbox: D.getElementById('allow-llm-mode-actions-chat-checkbox'),
    autospeakMinSecondsInput: D.getElementById('autospeak-min-seconds'),
    autospeakMaxSecondsInput: D.getElementById('autospeak-max-seconds'),
    saveLlmEdgePermissionsBtn: D.getElementById('save-llm-edge-permissions-btn'),
    llmEdgePermissionsStatus: D.getElementById('llm-edge-permissions-status'),
    refreshMotionPatternsBtn: D.getElementById('refresh-motion-patterns-btn'),
    importMotionPatternBtn: D.getElementById('import-motion-pattern-btn'),
    openMotionTrainingBtn: D.getElementById('open-motion-training-btn'),
    motionPatternImportInput: D.getElementById('motion-pattern-import-input'),
    refreshMotionProgramsBtn: D.getElementById('refresh-motion-programs-btn'),
    importMotionProgramBtn: D.getElementById('import-motion-program-btn'),
    motionProgramImportInput: D.getElementById('motion-program-import-input'),
    motionProgramStatus: D.getElementById('motion-program-status'),
    motionProgramList: D.getElementById('motion-program-list'),
    motionProgramDialog: D.getElementById('motion-program-dialog'),
    closeMotionProgramBtn: D.getElementById('close-motion-program-btn'),
    motionProgramDialogTitle: D.getElementById('motion-program-dialog-title'),
    motionProgramDialogMeta: D.getElementById('motion-program-dialog-meta'),
    motionProgramPlayerStatus: D.getElementById('motion-program-player-status'),
    motionProgramPlaybackTabBtn: D.getElementById('motion-program-playback-tab-btn'),
    motionProgramSectionTabBtn: D.getElementById('motion-program-section-tab-btn'),
    motionProgramPlaybackPanel: D.getElementById('motion-program-playback-panel'),
    motionProgramSectionPanel: D.getElementById('motion-program-section-panel'),
    motionProgramRangeTimeline: D.getElementById('motion-program-range-timeline'),
    motionProgramTimelineCanvas: D.getElementById('motion-program-timeline-canvas'),
    motionProgramSectionSelection: D.getElementById('motion-program-section-selection'),
    motionProgramSectionStartHandle: D.getElementById('motion-program-section-start-handle'),
    motionProgramSectionEndHandle: D.getElementById('motion-program-section-end-handle'),
    playMotionProgramFullBtn: D.getElementById('play-motion-program-full-btn'),
    playMotionProgramSectionBtn: D.getElementById('play-motion-program-section-btn'),
    stopMotionProgramPlaybackBtn: D.getElementById('stop-motion-program-playback-btn'),
    motionProgramSectionStartInput: D.getElementById('motion-program-section-start'),
    motionProgramSectionEndInput: D.getElementById('motion-program-section-end'),
    motionProgramSectionDuration: D.getElementById('motion-program-section-duration'),
    motionProgramSectionNameInput: D.getElementById('motion-program-section-name'),
    saveMotionProgramSectionPatternBtn: D.getElementById('save-motion-program-section-pattern-btn'),
    motionTrainingDialog: D.getElementById('motion-training-dialog'),
    closeMotionTrainingBtn: D.getElementById('close-motion-training-btn'),
    motionTrainingStatus: D.getElementById('motion-training-status'),
    stopMotionTrainingBtn: D.getElementById('stop-motion-training-btn'),
    motionTrainingPatternList: D.getElementById('motion-training-pattern-list'),
    motionTrainingPatternTitle: D.getElementById('motion-training-pattern-title'),
    motionTrainingPatternMeta: D.getElementById('motion-training-pattern-meta'),
    motionStudioPanel: D.getElementById('motion-studio-panel'),
    motionStudioDrawControls: D.getElementById('motion-studio-draw-controls'),
    motionStudioNewPatternBtn: D.getElementById('motion-studio-new-pattern-btn'),
    motionStudioToolEditBtn: D.getElementById('motion-studio-tool-edit-btn'),
    motionStudioToolDrawBtn: D.getElementById('motion-studio-tool-draw-btn'),
    motionStudioDeletePointBtn: D.getElementById('motion-studio-delete-point-btn'),
    motionStudioToolHint: D.getElementById('motion-studio-tool-hint'),
    motionStudioClearDrawingBtn: D.getElementById('motion-studio-clear-drawing-btn'),
    motionStudioImportBtn: D.getElementById('motion-studio-import-btn'),
    motionStudioImportInput: D.getElementById('motion-studio-import-input'),
    motionStudioSourceStatus: D.getElementById('motion-studio-source-status'),
    motionStudioCropPanel: D.getElementById('motion-studio-crop-panel'),
    motionStudioCropTimeline: D.getElementById('motion-studio-crop-timeline'),
    motionStudioCropCanvas: D.getElementById('motion-studio-crop-canvas'),
    motionStudioCropSelection: D.getElementById('motion-studio-crop-selection'),
    motionStudioCropStartHandle: D.getElementById('motion-studio-crop-start-handle'),
    motionStudioCropEndHandle: D.getElementById('motion-studio-crop-end-handle'),
    motionStudioCropDuration: D.getElementById('motion-studio-crop-duration'),
    motionStudioZoomOutBtn: D.getElementById('motion-studio-zoom-out-btn'),
    motionStudioZoomSlider: D.getElementById('motion-studio-zoom'),
    motionStudioZoomValue: D.getElementById('motion-studio-zoom-value'),
    motionStudioZoomInBtn: D.getElementById('motion-studio-zoom-in-btn'),
    motionStudioFitBtn: D.getElementById('motion-studio-fit-btn'),
    motionStudioPanSlider: D.getElementById('motion-studio-pan'),
    motionStudioWindowValue: D.getElementById('motion-studio-window-value'),
    motionStudioCropStartInput: D.getElementById('motion-studio-crop-start'),
    motionStudioCropEndInput: D.getElementById('motion-studio-crop-end'),
    motionStudioPlayCropBtn: D.getElementById('motion-studio-play-crop-btn'),
    motionStudioApplyCropBtn: D.getElementById('motion-studio-apply-crop-btn'),
    motionStudioSaveProgramBtn: D.getElementById('motion-studio-save-program-btn'),
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
    splashScreen: D.getElementById('splash-screen'),
    splashPrompt: D.getElementById('splash-prompt'),
    splashStatus: D.getElementById('splash-status'),
    splashProgressBar: D.getElementById('splash-progress-bar'),
    splashProgressText: D.getElementById('splash-progress-text'),
    setupOverlay: D.getElementById('setup-overlay'),
    setupBox: D.getElementById('setup-box'),
    refreshSystemStatusBtn: D.getElementById('refresh-system-status-btn'),
    copySystemStatusBtn: D.getElementById('copy-system-status-btn'),
    systemStatusCopyStatus: D.getElementById('system-status-copy-status'),
    systemStatusOutput: D.getElementById('system-status-output'),
    runSetupCheckBtn: D.getElementById('run-setup-check-btn'),
    setupCheckStatus: D.getElementById('setup-check-status'),
    setupCheckResults: D.getElementById('setup-check-results'),
    runLatencyTestsBtn: D.getElementById('run-latency-tests-btn'),
    latencyTestStatus: D.getElementById('latency-test-status'),
    latencyTestResults: D.getElementById('latency-test-results'),
    startMotionCaptureBtn: D.getElementById('start-motion-capture-btn'),
    finishMotionCaptureBtn: D.getElementById('finish-motion-capture-btn'),
    downloadMotionCaptureBtn: D.getElementById('download-motion-capture-btn'),
    motionCaptureStatus: D.getElementById('motion-capture-status'),
    motionCaptureResults: D.getElementById('motion-capture-results'),
    motionCaptureOutput: D.getElementById('motion-capture-output'),
    sendChatBtn: D.getElementById('send-chat-btn'),
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
    motionHistoryPanel: D.getElementById('motion-history-panel'),
    motionCurrentStatusPanel: D.getElementById('motion-current-status-panel'),
    motionSequenceIndicator: D.getElementById('motion-sequence-indicator'),
    motionDiagnosticsPanel: D.getElementById('motion-diagnostics-panel'),
    typingIndicator: D.getElementById('typing-indicator'),
    chatView: D.getElementById('chat-view'),
    chatMessagesContainer: D.getElementById('chat-messages-container'),
    jumpToLatestBtn: D.getElementById('jump-to-latest-btn'),
    pfpUploadInput: D.getElementById('pfp-upload'),
    pfpPreview: D.getElementById('ai-pfp-preview'),
    typingIndicatorPfp: D.getElementById('typing-indicator-pfp'),
    toggleSidebarBtn: D.getElementById('toggle-sidebar-btn'),
    toggleMemoryBtn: D.getElementById('toggle-memory-btn'),
    pauseResumeBtn: D.getElementById('pause-resume-btn'),
    imCloseBtn: D.getElementById('im-close-btn'),
    edgingModeBtn: D.getElementById('edging-mode-btn'),
    freestyleModeBtn: D.getElementById('freestyle-mode-btn'),
    activeModeStatus: D.getElementById('active-mode-status'),
    activeModeLabel: D.getElementById('active-mode-label'),
    edgingTimer: D.getElementById('edging-timer'),
    easterEggOverlay: D.getElementById('easter-egg-overlay'),
    connectionLostBanner: D.getElementById('connection-lost-banner'),
    multiTabWarningBanner: D.getElementById('multi-tab-warning-banner'),
};

export const state = {
    uiClientId: '',
    myHandyKey: '',
    handyFirmwareVersion: 'fw4',
    handyApiV3Key: '',
    myPersonaDescription: '',
    aiName: 'BOT',
    activeModeName: '',
    activeModeElapsedSeconds: null,
    chatSessionElapsedSeconds: null,
    chatIntensityGuide: 'steady',
    chatIntensityCountDirection: 'steady',
    motionPaused: false,
    personaPrompts: [],
    localTtsStylePresets: {},
    audioFetchInProgress: false,
    motionMinDepth: 5,
    motionMaxDepth: 100,
    motionMinSpeed: 10,
    motionMaxSpeed: 80,
    motionBackend: 'continuous',
    motionBackends: [],
    motionStyle: 'balanced',
    motionStyleOptions: [],
    motionReverseDirection: false,
    motionDiagnosticsLevel: 'compact',
    ollamaDiagnosticsLevel: 'compact',
    diagnosticsLevels: [],
    systemStatusText: '',
    systemStatusPayload: null,
    systemStatusLoading: false,
    ollamaModels: [],
    ollamaCurrentModel: '',
    ollamaThinkingEnabled: false,
    ollamaStatus: {},
    ollamaModelDetails: {},
    ollamaModelPromptDismissedKey: '',
    motionFeedbackAutoDisable: false,
    allowLlmEdgeInFreestyle: true,
    allowLlmEdgeInChat: true,
    allowLlmModeActionsInChat: false,
    autospeakEnabled: false,
    autospeakMinSeconds: 12,
    autospeakMaxSeconds: 45,
    useLongTermMemory: true,
    ollamaDownloadPolling: false,
    localTtsStatusPolling: false,
    voiceInputProvider: 'disabled',
    voiceInputEnabled: false,
    voiceInputMode: 'push_to_talk',
    voiceInputSubmitMode: 'preview',
    voiceInputCanTranscribe: false,
    voiceInputHandsFreeSensitivity: 75,
    voiceInputHandsFreeSilenceMs: 900,
    voiceInputMinRecordingMs: 450,
    voiceInputMaxRecordingMs: 8000,
    voiceInputNoiseSuppression: true,
    voiceInputEchoCancellation: true,
    voiceInputAutoGainControl: true,
    voiceInputNoiseFloorRms: 0,
    voiceInputAudioPreprocessing: true,
    voiceInputSilenceTrim: true,
    voiceInputHandsFreeModeActions: false,
    voiceInputBeamSize: 5,
    voiceInputConditionOnPreviousText: false,
    voiceInputVadThreshold: 0.5,
    voiceInputVadMinSilenceMs: 500,
    voiceInputVadSpeechPadMs: 400,
    voiceInputDevices: [],
    voiceInputDeviceId: '',
    voiceInputDeviceMenuOpen: false,
    voiceInputStatusSnapshot: {},
    voiceInputLastRecordingMs: null,
    voiceInputLastUploadMs: null,
    voiceInputLastChatMs: null,
    voiceInputLastChatTimings: {},
    voiceInputLastBlobBytes: null,
    voiceInputLastIssue: '',
    voiceInputRecording: false,
    voiceInputHandsFreeArmed: false,
    voiceInputStream: null,
    voiceInputRecorder: null,
    voiceInputChunks: [],
    voiceInputRecordingStartedAt: 0,
    voiceInputStopTimer: null,
    voiceInputAudioContext: null,
    voiceInputAudioSource: null,
    voiceInputAnalyser: null,
    voiceInputRecordingCleanup: null,
    voiceInputMonitorFrame: null,
    voiceInputSilenceStartedAt: 0,
    voiceInputPendingTranscript: '',
    voiceInputPendingSource: '',
    systemPromptsLoadedOnce: false,
    userGenitalia: 'penis',
    userGenitaliaCustom: '',
    userGenitaliaOptions: [],
    llmPromptMode: 'revibed',
    llmPromptModeOptions: [],
    llmPromptEditActive: false,
    llmPromptEditName: '',
    chatModelBlockedMessage: '',
    pendingQueuedBotEcho: '',
    chatStreamingEnabled: true,
    motionPatterns: [],
    motionPrograms: [],
    motionProgramSelected: null,
    motionProgramSectionStartMs: 0,
    motionProgramSectionEndMs: 0,
    motionProgramSectionDragHandle: '',
    motionProgramTimelineZoom: 1,
    motionProgramTimelineOffsetMs: 0,
    motionProgramActiveTab: 'playback',
    motionTraining: {state: 'idle', pattern_id: '', pattern_name: ''},
    motionTrainingSelectedPatternId: '',
    motionTrainingPreviewPattern: null,
    motionTrainingOriginalPattern: null,
    motionTrainingEditedPattern: null,
    motionTrainingDirty: false,
    motionStudioSourcePattern: null,
    motionStudioCropStartMs: 0,
    motionStudioCropEndMs: 0,
    motionStudioTimelineZoom: 1,
    motionStudioTimelineOffsetMs: 0,
    motionStudioDrawingEnabled: false,
    motionStudioDrawingActive: false,
    motionStudioDrawBuffer: [],
    // Active studio tool. ``edit`` allows drag/insert/delete on existing
    // points and is the default whenever an editable pattern is loaded.
    // ``draw`` records one freehand sweep that replaces the pattern's
    // actions and then auto-reverts to ``edit`` so accidental sweeps do
    // not wipe carefully-tweaked patterns.
    motionStudioTool: 'edit',
    motionStudioDragPointIndex: -1,
    motionStudioSelectedPointIndex: -1,
    motionStudioCropDragHandle: '',
    motionStudioFlow: '',
    motionObservability: null,
    motionTransportCapture: null,
    motionTransportCaptureActive: false,
    motionCylinderAnimationStarted: false,
    connectionLost: false,
    backendControlGuardInitialized: false,
    singleActiveTabWarningInitialized: false,
};

export const BACKEND_REQUIRED_SELECTOR = '[data-requires-backend]';
const STATUS_TONE_COLORS = {
    neutral: '',
    info: 'var(--comment)',
    success: 'var(--cyan)',
    warning: 'var(--yellow)',
    error: 'var(--red)',
};

export function setStatusMessage(statusEl, message, tone = 'neutral') {
    if (!statusEl) return;
    statusEl.textContent = message;
    const normalizedTone = Object.prototype.hasOwnProperty.call(STATUS_TONE_COLORS, tone) ? tone : 'neutral';
    statusEl.dataset.statusTone = normalizedTone;
    statusEl.style.color = STATUS_TONE_COLORS[normalizedTone];
}

export function applyBackendRequiredControlState(control) {
    if (!control || !('disabled' in control)) return control;
    if (state.connectionLost) {
        if (control.dataset.backendLocked !== 'true') {
            control.dataset.backendPreviousDisabled = control.disabled ? 'true' : 'false';
        }
        control.disabled = true;
        control.dataset.backendLocked = 'true';
        control.setAttribute('aria-disabled', 'true');
        return control;
    }
    if (control.dataset.backendLocked === 'true') {
        if (control.dataset.backendPreviousDisabled === 'false') control.disabled = false;
        delete control.dataset.backendLocked;
        delete control.dataset.backendPreviousDisabled;
        control.removeAttribute('aria-disabled');
    }
    return control;
}

export function syncBackendRequiredControls(root = D) {
    if (root.matches?.(BACKEND_REQUIRED_SELECTOR)) applyBackendRequiredControlState(root);
    root.querySelectorAll?.(BACKEND_REQUIRED_SELECTOR).forEach(applyBackendRequiredControlState);
}

export function markRequiresBackend(control) {
    if (!control) return control;
    control.dataset.requiresBackend = 'true';
    return applyBackendRequiredControlState(control);
}

function blockBackendRequiredInteraction(event) {
    if (!state.connectionLost) return;
    const control = event.target?.closest?.(BACKEND_REQUIRED_SELECTOR);
    if (!control) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    setStatusMessage(
        el.statusText,
        'Connection lost. Reconnect before changing settings or sending commands.',
        'error',
    );
}

export function initBackendRequiredControlGuard() {
    if (state.backendControlGuardInitialized) return;
    state.backendControlGuardInitialized = true;
    ['click', 'change', 'submit', 'keydown'].forEach(type => {
        D.addEventListener(type, blockBackendRequiredInteraction, true);
    });
    const observer = new MutationObserver(mutations => {
        mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
                if (node.nodeType === Node.ELEMENT_NODE) syncBackendRequiredControls(node);
            });
        });
    });
    observer.observe(D.body, {childList: true, subtree: true});
    syncBackendRequiredControls();
}

export function setConnectionLost(isLost) {
    const next = Boolean(isLost);
    if (state.connectionLost === next) {
        syncBackendRequiredControls();
        return;
    }
    state.connectionLost = next;
    if (el.connectionLostBanner) el.connectionLostBanner.hidden = !next;
    syncBackendRequiredControls();
    if (!next) D.dispatchEvent(new CustomEvent('backend-connection-restored'));
}

export async function fetchWithConnectionState(endpoint, options = {}) {
    try {
        const wasConnectionLost = state.connectionLost;
        const response = await fetch(endpoint, options);
        setConnectionLost(false);
        if (wasConnectionLost) {
            setStatusMessage(el.statusText, 'Connection restored.', 'success');
        } else if (el.statusText?.dataset.statusTone === 'error') {
            setStatusMessage(el.statusText, el.statusText.textContent, 'neutral');
        }
        return response;
    } catch (error) {
        console.error(`API call to ${endpoint} failed:`, error);
        setConnectionLost(true);
        setStatusMessage(el.statusText, 'Error: Cannot connect to server.', 'error');
        throw error;
    }
}

export async function apiCall(endpoint, options = {}) {
    let response;
    try {
        response = await fetchWithConnectionState(endpoint, options);
    } catch (error) {
        // Network failure: backend unreachable. Surface the persistent
        // connection-lost banner so the user does not silently keep editing
        // settings, sliders, or feedback that will not save.
        return undefined;
    }
    // The backend answered, so the connection is alive even if this specific
    // request returned an HTTP error. The route handlers in this app return
    // useful detail in a JSON body (e.g. ``{"status": "error",
    // "message": "Persona prompt is required."}``) even on 4xx responses;
    // surface that message in the global statusText instead of the
    // generic "Error: server returned 400." line, so the user sees WHY
    // the save failed without having to open the app terminal. Closes the
    // KNOWN_PROBLEMS "Web UI Stays Functional After Backend Shutdown" gap
    // for the backend-reachable-but-rejected case.
    if (!response.ok) {
        console.error(`API call to ${endpoint} returned HTTP ${response.status}`);
        let serverMessage = '';
        try {
            const errorBody = await response.clone().json();
            if (errorBody && typeof errorBody.message === 'string' && errorBody.message.trim()) {
                serverMessage = errorBody.message.trim();
            }
        } catch { /* response body was not JSON or was empty */ }
        setStatusMessage(el.statusText, serverMessage || `Error: server returned ${response.status}.`, 'error');
        return undefined;
    }
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('audio/')) return response.blob();
    return response.json();
}

// Backend-failure feedback has three levels:
// - Network loss: persistent banner + global error tone from apiCall().
// - HTTP error: global error tone from apiCall().
// - Reachable route rejection: one local warning from reportSaveFailure().
//
// Use:
//   const data = await apiCall(...);
//   if (data && data.status === 'success') {
//       // ... success branch
//   } else {
//       reportSaveFailure(el.someStatus, data, 'Save failed.');
//   }
//
// Pass ``el.statusText`` as ``statusEl`` for endpoints without a dedicated
// status span. When ``data`` is undefined, apiCall() already reported the
// network/HTTP failure and this helper deliberately stays silent.
export function reportSaveFailure(statusEl, data, fallbackMessage = 'Save failed.') {
    if (!statusEl) return;
    if (data === undefined) return; // banner + statusText already surfaced the network failure
    if (data && data.status === 'success') return;
    const detail = (data && typeof data.message === 'string' && data.message.trim()) || fallbackMessage;
    setStatusMessage(statusEl, detail, 'warning');
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

export function formatPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '';
    const clamped = clampNumber(number, 0, 100, 0);
    const rounded = Math.round(clamped * 10) / 10;
    return Number.isInteger(rounded) ? `${rounded}%` : `${rounded.toFixed(1)}%`;
}
