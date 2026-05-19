import { D, apiCall, clampNumber, el, fetchWithConnectionState, markRequiresBackend, reportSaveFailure, setSliderValue, state } from './context.js';
import {
    formatBackendName,
    formatClockElapsed,
    formatMotionFrame,
    formatMotionTraceTiming,
    latestTracePoint,
    resetMotionSequenceLog,
    updateMotionSequenceIndicator,
} from './motion/sequence-log.js';
import {
    bindMotionPauseControls,
    updatePauseResumeUi,
} from './motion/pause-controls.js';
import {
    clonePattern,
    configureMotionPatternList,
    createPatternDeleteButton,
    createPatternExportButton,
    createPatternFeedbackResetButton,
    createPatternTagsButton,
    createPatternText,
    formatPatternDuration,
    formatPatternMetadata,
    normalizedActions,
    patternById,
    patternDisplayName,
    patternHasFeedbackState,
    renderCompactMotionPatternList,
    setMotionPatternTags,
    setPatternStatus,
    updatePatternStats,
} from './motion/pattern-list.js';
import {
    configureMotionFeedbackControls,
    renderMotionFeedbackHistory,
    resetMotionPreferences,
    saveMotionFeedbackOptions,
} from './motion/feedback-controls.js';
import {
    bindMotionProgramControls,
    configureMotionProgramList,
    refreshMotionPrograms,
    renderMotionPrograms,
    setMotionProgramTags,
    setProgramStatus,
} from './motion/program-list.js';
import {
    bindMotionProgramPlayerControls,
    closeMotionProgramWindow,
    configureMotionProgramPlayer,
    openMotionProgramWindow,
} from './motion/program-player.js';
import { updateMotionTagSuggestions } from './motion/tag-editor.js';
import { updateHandyConnectionStatusFromMotion } from './device-control.js';
import {
    bindMotionPatternStudioControls,
    drawMotionTrainingPreview,
    drawOpenMotionTrainingPreview,
    drawPatternPreviewCanvas,
    editablePatternPayload,
    harshenEditedPattern,
    patternTempoScale,
    refreshMotionTrainingDetail,
    remapEditedPatternRange,
    resetEditedPattern,
    setEditedPatternDuration,
    setEditedPatternTempo,
    setMotionEditStatus,
    setMotionTrainingDetail,
    setMotionTrainingLoadingDetail,
    simplifyEditedPattern,
    smoothEditedPattern,
    studioCropPreviewPayload,
    studioSourceProgramPayload,
    stepMotionTrainingRangeInput,
    syncRangeInputsFromPattern,
    updateMotionTrainingEditButtons,
    updateMotionTrainingTimingReadouts,
} from './motion/training-editor.js';

// Compatibility shim - do not extend. New code imports from './motion/sequence-log.js'.
export { resetMotionSequenceLog, updateMotionSequenceIndicator } from './motion/sequence-log.js';
// Compatibility shim - do not extend. New code imports from './motion/pause-controls.js'.
export {
    closeSignalAvailable,
    handleMotionHotkey,
    signalImClose,
    stopMotion,
    toggleMotionPause,
    updatePauseResumeUi,
} from './motion/pause-controls.js';
// Compatibility shim - do not extend. New code imports from './motion/pattern-list.js'.
export {
    clonePattern,
    configureMotionPatternList,
    createPatternExportButton,
    createPatternFeedbackResetButton,
    createPatternTagsButton,
    createPatternText,
    formatPatternDuration,
    formatPatternMetadata,
    normalizedActions,
    patternById,
    patternDisplayName,
    patternHasFeedbackState,
    renderCompactMotionPatternList,
    resetMotionPatternFeedback,
    setMotionPatternEnabled,
    setMotionPatternTags,
    setMotionPatternWeight,
    setPatternStatus,
    updatePatternStats,
} from './motion/pattern-list.js';
// Compatibility shim - do not extend. New code imports from './motion/feedback-controls.js'.
export {
    configureMotionFeedbackControls,
    renderMotionFeedbackHistory,
    resetMotionPreferences,
    saveMotionFeedbackOptions,
} from './motion/feedback-controls.js';
// Compatibility shim - do not extend. New code imports from './motion/program-list.js'.
export {
    bindMotionProgramControls,
    configureMotionProgramList,
    refreshMotionPrograms,
    renderMotionPrograms,
    setMotionProgramTags,
    setProgramStatus,
} from './motion/program-list.js';
// Compatibility shim - do not extend. New code imports from './motion/program-player.js'.
export {
    bindMotionProgramPlayerControls,
    closeMotionProgramWindow,
    configureMotionProgramPlayer,
    openMotionProgramWindow,
} from './motion/program-player.js';
// Compatibility shim - do not extend. New code imports from './motion/training-editor.js'.
export {
    drawMotionTrainingPreview,
    drawOpenMotionTrainingPreview,
    drawPatternPreviewCanvas,
    editablePatternPayload,
    harshenEditedPattern,
    patternTempoScale,
    refreshMotionTrainingDetail,
    remapEditedPatternRange,
    resetEditedPattern,
    setEditedPatternDuration,
    setEditedPatternTempo,
    setMotionEditStatus,
    setMotionTrainingDetail,
    setMotionTrainingLoadingDetail,
    simplifyEditedPattern,
    smoothEditedPattern,
    studioSourceProgramPayload,
    stepMotionTrainingRangeInput,
    syncRangeInputsFromPattern,
    updateMotionTrainingEditButtons,
    updateMotionTrainingTimingReadouts,
} from './motion/training-editor.js';

const HSP_STATE_MAX_EXTRAPOLATION_AGE_MS = 750;

let lastCylinderDebug = {source: 'init'};

function normalizeMotionSpeedLimits() {
    const a = parseInt(el.motionSpeedMinSlider.value, 10);
    const b = parseInt(el.motionSpeedMaxSlider.value, 10);
    state.motionMinSpeed = Math.min(a, b);
    state.motionMaxSpeed = Math.max(a, b);
    el.motionSpeedMinVal.textContent = `${state.motionMinSpeed}%`;
    el.motionSpeedMaxVal.textContent = `${state.motionMaxSpeed}%`;
}

function motionBackendDetails(backendId) {
    return state.motionBackends.find(backend => backend.id === backendId) || {
        id: 'continuous',
        label: 'Continuous position',
        description: 'Recommended default: fixed patterns run as live sampled motion until the next command or stop.',
        experimental: false,
    };
}

function updateMotionBackendUi(backendId) {
    state.motionBackend = ['continuous', 'position', 'hamp'].includes(backendId) ? backendId : 'continuous';
    if (el.motionBackendSelect) el.motionBackendSelect.value = state.motionBackend;
    const details = motionBackendDetails(state.motionBackend);
    const suffix = details.experimental ? ' (experimental)' : details.deprecated ? ' (legacy)' : '';
    if (el.motionBackendStatus) {
        el.motionBackendStatus.textContent = `Current backend: ${details.label}${suffix}. ${details.description || ''}`.trim();
    }
    if (el.appMotionBackendBadge) {
        el.appMotionBackendBadge.textContent = `App motion: ${details.label}${suffix}`;
    }
}

function renderMotionBackendOptions(options = [], currentBackend = 'continuous') {
    state.motionBackends = options.length ? options : [
        {
            id: 'continuous',
            label: 'Continuous position',
            description: 'Recommended default: fixed patterns run as live sampled motion until the next command or stop.',
            experimental: false,
        },
        {
            id: 'hamp',
            label: 'HAMP legacy',
            description: 'Legacy bounded-oscillation path. Kept as a fallback, but fixed patterns lose shape fidelity here.',
            experimental: false,
            deprecated: true,
        },
        {
            id: 'position',
            label: 'Flexible position/script',
            description: 'Finite position/script playback for previews and compatibility.',
            experimental: true,
        },
    ];
    if (el.motionBackendSelect) {
        el.motionBackendSelect.replaceChildren();
        state.motionBackends.forEach(backend => {
            const option = D.createElement('option');
            option.value = backend.id;
            option.textContent = `${backend.label}${backend.experimental ? ' (experimental)' : backend.deprecated ? ' (legacy)' : backend.id === 'continuous' ? ' (recommended)' : ''}`;
            el.motionBackendSelect.appendChild(option);
        });
    }
    updateMotionBackendUi(currentBackend);
}

function motionStyleDetails(styleId) {
    return state.motionStyleOptions.find(style => style.id === styleId) || {
        id: 'balanced',
        label: 'Balanced',
        description: 'Let the model choose a sensible mix.',
    };
}

function updateMotionStyleUi(styleId) {
    const validIds = (state.motionStyleOptions || []).map(style => style.id);
    state.motionStyle = validIds.includes(styleId) ? styleId : 'balanced';
    if (el.motionStyleSelect) el.motionStyleSelect.value = state.motionStyle;
    const details = motionStyleDetails(state.motionStyle);
    if (el.motionStyleStatus) {
        el.motionStyleStatus.textContent = `Current style: ${details.label}. ${details.description || ''}`.trim();
    }
}

function renderMotionStyleOptions(options = [], currentStyle = 'balanced') {
    state.motionStyleOptions = options.length ? options : [
        {id: 'balanced', label: 'Balanced', description: 'Let the model choose a sensible mix.'},
    ];
    if (el.motionStyleSelect) {
        el.motionStyleSelect.replaceChildren();
        state.motionStyleOptions.forEach(style => {
            const option = D.createElement('option');
            option.value = style.id;
            option.textContent = style.label;
            el.motionStyleSelect.appendChild(option);
        });
    }
    updateMotionStyleUi(currentStyle);
}

function updateMotionReverseDirectionUi(enabled) {
    state.motionReverseDirection = Boolean(enabled);
    if (el.motionDirectionNormalRadio) {
        el.motionDirectionNormalRadio.checked = !state.motionReverseDirection;
    }
    if (el.motionDirectionReverseRadio) {
        el.motionDirectionReverseRadio.checked = state.motionReverseDirection;
    }
    if (el.motionReverseDirectionStatus) {
        el.motionReverseDirectionStatus.textContent = `Current direction: ${state.motionReverseDirection ? 'Reverse' : 'Normal'}.`;
    }
}

function updateMemoryToggleUi(enabled) {
    state.useLongTermMemory = Boolean(enabled);
    if (!el.toggleMemoryBtn) return;
    el.toggleMemoryBtn.textContent = `Memories: ${state.useLongTermMemory ? 'ON' : 'OFF'}`;
    el.toggleMemoryBtn.setAttribute('aria-pressed', state.useLongTermMemory ? 'true' : 'false');
}

function updateAutospeakToggleUi(enabled) {
    state.autospeakEnabled = Boolean(enabled);
    if (!el.topBarAutospeakToggleBtn) return;
    el.topBarAutospeakToggleBtn.textContent = state.autospeakEnabled ? 'Auto On' : 'Auto Off';
    el.topBarAutospeakToggleBtn.title = state.autospeakEnabled ? 'Turn Autospeak off' : 'Turn Autospeak on';
    el.topBarAutospeakToggleBtn.setAttribute('aria-label', state.autospeakEnabled ? 'Autospeak on' : 'Autospeak off');
    el.topBarAutospeakToggleBtn.setAttribute('aria-pressed', state.autospeakEnabled ? 'true' : 'false');
    if (state.autospeakEnabled) el.topBarAutospeakToggleBtn.classList.add('is-on');
    else el.topBarAutospeakToggleBtn.classList.remove('is-on');
}

export function populateMotionSettings(data = {}) {
    const timings = data.timings || {};
    state.motionDiagnosticsLevel = data.motion_diagnostics_level || state.motionDiagnosticsLevel || 'compact';
    state.motionFeedbackAutoDisable = data.motion_feedback_auto_disable ?? state.motionFeedbackAutoDisable ?? false;
    state.motionPatternLibraryEnabledInFreestyle = data.motion_pattern_library_enabled_in_freestyle ?? state.motionPatternLibraryEnabledInFreestyle ?? false;
    state.motionPatternLibraryEnabledInChat = data.motion_pattern_library_enabled_in_chat ?? state.motionPatternLibraryEnabledInChat ?? false;
    state.allowLlmEdgeInFreestyle = data.allow_llm_edge_in_freestyle ?? state.allowLlmEdgeInFreestyle ?? true;
    state.allowLlmEdgeInChat = data.allow_llm_edge_in_chat ?? state.allowLlmEdgeInChat ?? true;
    state.allowLlmModeActionsInChat = data.allow_llm_mode_actions_in_chat ?? state.allowLlmModeActionsInChat ?? false;
    state.autospeakMinSeconds = data.autospeak_min_seconds ?? state.autospeakMinSeconds ?? 12;
    state.autospeakMaxSeconds = data.autospeak_max_seconds ?? state.autospeakMaxSeconds ?? 45;
    updateAutospeakToggleUi(data.autospeak_enabled ?? state.autospeakEnabled ?? false);
    if (el.motionFeedbackAutoDisableCheckbox) {
        el.motionFeedbackAutoDisableCheckbox.checked = Boolean(state.motionFeedbackAutoDisable);
    }
    if (el.motionPatternLibraryFreestyleCheckbox) {
        el.motionPatternLibraryFreestyleCheckbox.checked = Boolean(state.motionPatternLibraryEnabledInFreestyle);
    }
    if (el.motionPatternLibraryChatCheckbox) {
        el.motionPatternLibraryChatCheckbox.checked = Boolean(state.motionPatternLibraryEnabledInChat);
    }
    if (el.allowLlmEdgeFreestyleCheckbox) {
        el.allowLlmEdgeFreestyleCheckbox.checked = Boolean(state.allowLlmEdgeInFreestyle);
    }
    if (el.allowLlmEdgeChatCheckbox) {
        el.allowLlmEdgeChatCheckbox.checked = Boolean(state.allowLlmEdgeInChat);
    }
    if (el.allowLlmModeActionsChatCheckbox) {
        el.allowLlmModeActionsChatCheckbox.checked = Boolean(state.allowLlmModeActionsInChat);
    }
    if (el.autospeakMinSecondsInput) el.autospeakMinSecondsInput.value = state.autospeakMinSeconds;
    if (el.autospeakMaxSecondsInput) el.autospeakMaxSecondsInput.value = state.autospeakMaxSeconds;
    readAutospeakTimingPair();
    if (el.llmEdgePermissionsStatus) {
        el.llmEdgePermissionsStatus.textContent = `Freestyle edge: ${state.allowLlmEdgeInFreestyle ? 'allowed' : 'blocked'}. Chat edge: ${state.allowLlmEdgeInChat ? 'allowed' : 'blocked'}. Chat mode actions: ${state.allowLlmModeActionsInChat ? 'allowed' : 'blocked'}. Autospeak: ${state.autospeakEnabled ? 'on' : 'off'} (${state.autospeakMinSeconds}-${state.autospeakMaxSeconds}s).`;
    }
    updateMemoryToggleUi(data.use_long_term_memory ?? state.useLongTermMemory);
    renderMotionBackendOptions(data.motion_backends || state.motionBackends, data.motion_backend || state.motionBackend);
    renderMotionStyleOptions(data.motion_style_options || state.motionStyleOptions, data.motion_style || state.motionStyle);
    updateMotionReverseDirectionUi(data.motion_reverse_direction ?? state.motionReverseDirection);
    setSliderValue(el.motionSpeedMinSlider, el.motionSpeedMinVal, data.min_speed ?? state.motionMinSpeed);
    setSliderValue(el.motionSpeedMaxSlider, el.motionSpeedMaxVal, data.max_speed ?? state.motionMaxSpeed);
    normalizeMotionSpeedLimits();
    el.autoMinTimeInput.value = timings.auto_min ?? el.autoMinTimeInput.value ?? 4;
    el.autoMaxTimeInput.value = timings.auto_max ?? el.autoMaxTimeInput.value ?? 7;
    el.edgingMinTimeInput.value = timings.edging_min ?? el.edgingMinTimeInput.value ?? 5;
    el.edgingMaxTimeInput.value = timings.edging_max ?? el.edgingMaxTimeInput.value ?? 8;
    el.milkingMinTimeInput.value = timings.milking_min ?? el.milkingMinTimeInput.value ?? 2.5;
    el.milkingMaxTimeInput.value = timings.milking_max ?? el.milkingMaxTimeInput.value ?? 4.5;
    if (data.motion_patterns) renderMotionPatterns(data.motion_patterns);
    if (data.motion_programs) renderMotionPrograms(data.motion_programs);
}

async function saveMotionBackend() {
    const motionBackend = el.motionBackendSelect?.value || 'continuous';
    const data = await apiCall('/set_motion_backend', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({motion_backend: motionBackend}),
    });
    if (data && data.status === 'success') {
        updateMotionBackendUi(data.motion_backend);
        el.statusText.textContent = `Motion backend saved: ${motionBackendDetails(data.motion_backend).label}.`;
    } else {
        reportSaveFailure(el.motionBackendStatus, data, 'Could not save motion backend.');
    }
}

async function saveMotionStyle() {
    const motionStyle = el.motionStyleSelect?.value || 'balanced';
    const data = await apiCall('/set_motion_style', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({motion_style: motionStyle}),
    });
    if (data && data.status === 'success') {
        renderMotionStyleOptions(data.motion_style_options || state.motionStyleOptions, data.motion_style);
        el.statusText.textContent = `Motion style saved: ${motionStyleDetails(data.motion_style).label}.`;
    } else {
        reportSaveFailure(el.motionStyleStatus || el.statusText, data, 'Could not save motion style.');
    }
}

async function saveMotionReverseDirection() {
    const motionReverseDirection = Boolean(el.motionDirectionReverseRadio?.checked);
    const data = await apiCall('/set_motion_reverse_direction', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({motion_reverse_direction: motionReverseDirection}),
    });
    if (data && data.status === 'success') {
        updateMotionReverseDirectionUi(data.motion_reverse_direction);
        el.statusText.textContent = `Motion direction saved: ${state.motionReverseDirection ? 'reverse' : 'normal'}.`;
    } else {
        reportSaveFailure(el.motionReverseDirectionStatus || el.statusText, data, 'Could not save motion direction.');
    }
}

async function saveMotionSpeedLimits() {
    normalizeMotionSpeedLimits();
    const res = await apiCall('/set_speed_limits', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({min_speed: state.motionMinSpeed, max_speed: state.motionMaxSpeed}),
    });
    if (res && res.status === 'success') {
        populateMotionSettings({min_speed: res.min_speed, max_speed: res.max_speed});
        el.statusText.textContent = `Speed limits saved: ${state.motionMinSpeed}-${state.motionMaxSpeed}%.`;
    } else {
        reportSaveFailure(el.statusText, res, 'Could not save speed limits.');
    }
}

async function toggleLongTermMemory() {
    const data = await apiCall('/toggle_memory', {method: 'POST'});
    if (data && data.status === 'success') {
        updateMemoryToggleUi(data.use_long_term_memory);
        el.statusText.textContent = `Long-term memories ${data.use_long_term_memory ? 'enabled' : 'disabled'}.`;
    } else {
        reportSaveFailure(el.statusText, data, 'Could not toggle long-term memory.');
    }
}

function readTimingPair(minInput, maxInput) {
    const a = clampNumber(minInput.value, 1, 60, 1);
    const b = clampNumber(maxInput.value, 1, 60, a);
    minInput.value = Math.min(a, b);
    maxInput.value = Math.max(a, b);
    return [Number(minInput.value), Number(maxInput.value)];
}

function readAutospeakTimingPair() {
    const a = clampNumber(el.autospeakMinSecondsInput?.value, 0, 300, state.autospeakMinSeconds ?? 12);
    const b = clampNumber(el.autospeakMaxSecondsInput?.value, 0, 300, state.autospeakMaxSeconds ?? 45);
    state.autospeakMinSeconds = Math.min(a, b);
    state.autospeakMaxSeconds = Math.max(a, b);
    if (el.autospeakMinSecondsInput) el.autospeakMinSecondsInput.value = state.autospeakMinSeconds;
    if (el.autospeakMaxSecondsInput) el.autospeakMaxSecondsInput.value = state.autospeakMaxSeconds;
    return [state.autospeakMinSeconds, state.autospeakMaxSeconds];
}

async function saveModeTimings() {
    const [autoMin, autoMax] = readTimingPair(el.autoMinTimeInput, el.autoMaxTimeInput);
    const [edgingMin, edgingMax] = readTimingPair(el.edgingMinTimeInput, el.edgingMaxTimeInput);
    const [milkingMin, milkingMax] = readTimingPair(el.milkingMinTimeInput, el.milkingMaxTimeInput);
    const data = await apiCall('/set_mode_timings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            auto_min: autoMin,
            auto_max: autoMax,
            edging_min: edgingMin,
            edging_max: edgingMax,
            milking_min: milkingMin,
            milking_max: milkingMax,
        }),
    });
    if (data && data.status === 'success') {
        populateMotionSettings({timings: data.timings});
        el.statusText.textContent = 'Mode timings saved.';
    } else {
        reportSaveFailure(el.statusText, data, 'Could not save mode timings.');
    }
}

function updateMotionTrainingStatus(status = {}) {
    state.motionTraining = {
        state: status.state || state.motionTraining.state || 'idle',
        pattern_id: status.pattern_id || state.motionTraining.pattern_id || '',
        pattern_name: status.pattern_name || state.motionTraining.pattern_name || '',
        message: status.message || '',
        last_feedback: status.last_feedback || '',
        preview: Boolean(status.preview),
    };
    if (!el.motionTrainingStatus) return;

    const isPlaying = state.motionTraining.state === 'playing' || state.motionTraining.state === 'starting';
    const hasPattern = Boolean(state.motionTraining.pattern_id) && !state.motionTraining.preview;
    el.motionTrainingStatus.textContent = state.motionTraining.message || 'Training player idle.';
    el.motionTrainingStatus.style.color = isPlaying ? 'var(--cyan)' : 'var(--comment)';
    if (el.stopMotionTrainingBtn) el.stopMotionTrainingBtn.disabled = !isPlaying;
    [
        el.motionTrainingFeedbackUp,
        el.motionTrainingFeedbackNeutral,
        el.motionTrainingFeedbackDown,
    ].forEach(button => {
        if (button) button.disabled = !hasPattern;
    });
    if (state.motionTraining.pattern_id && !state.motionTrainingSelectedPatternId) {
        state.motionTrainingSelectedPatternId = state.motionTraining.pattern_id;
        renderMotionTrainingPatternList(state.motionPatterns);
    }
}

async function fetchJsonWithMessage(endpoint, options = {}) {
    try {
        const response = await fetchWithConnectionState(endpoint, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            const message = data.message || `Request failed: ${response.status}`;
            reportSaveFailure(el.statusText, data, message);
            return data;
        }
        return data;
    } catch {
        return undefined;
    }
}

async function selectMotionTrainingPattern(patternId) {
    const cleanId = String(patternId || '').trim();
    if (!cleanId) {
        state.motionTrainingSelectedPatternId = '';
        setMotionTrainingDetail(null);
        renderMotionTrainingPatternList(state.motionPatterns);
        return;
    }

    state.motionTrainingSelectedPatternId = cleanId;
    renderMotionTrainingPatternList(state.motionPatterns);
    const summary = patternById(cleanId);
    if (summary) setMotionTrainingLoadingDetail(summary);

    const data = await fetchJsonWithMessage(`/motion_patterns/${encodeURIComponent(cleanId)}`);
    if (data && data.status === 'success' && data.pattern) {
        state.motionTrainingSelectedPatternId = data.pattern.id;
        setMotionTrainingDetail(data.pattern);
        renderMotionTrainingPatternList(state.motionPatterns);
    } else if (!summary) {
        setMotionTrainingDetail(null);
    }
}

function renderMotionTrainingPatternList(patterns) {
    if (!el.motionTrainingPatternList) return;
    el.motionTrainingPatternList.replaceChildren();

    if (!patterns.length) return;

    patterns.forEach(pattern => {
        const row = D.createElement('div');
        row.className = 'motion-pattern-row motion-training-pattern-row';
        if (pattern.id === state.motionTrainingSelectedPatternId) row.classList.add('selected');
        row.tabIndex = 0;
        row.setAttribute('role', 'button');
        row.setAttribute('aria-label', `Preview ${patternDisplayName(pattern)}`);
        row.addEventListener('click', () => selectMotionTrainingPattern(pattern.id));
        row.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                selectMotionTrainingPattern(pattern.id);
            }
        });

        const main = D.createElement('div');
        main.className = 'motion-pattern-main';
        main.appendChild(createPatternText(pattern, {
            includeDescription: false,
            compactMetadata: true,
        }));

        const actions = D.createElement('div');
        actions.className = 'motion-pattern-row-actions';

        const playButton = D.createElement('button');
        playButton.type = 'button';
        playButton.className = 'my-button motion-pattern-play';
        playButton.textContent = 'Play';
        markRequiresBackend(playButton);
        playButton.addEventListener('click', event => {
            event.stopPropagation();
            startMotionTraining(pattern.id);
        });

        actions.append(playButton);
        if (patternHasFeedbackState(pattern)) actions.append(createPatternFeedbackResetButton(pattern));
        actions.append(createPatternExportButton(pattern));
        actions.append(createPatternDeleteButton(pattern));
        row.append(main, actions);
        el.motionTrainingPatternList.appendChild(row);
    });
}

export function renderMotionPatterns(catalog = {}) {
    updateMotionTagSuggestions(catalog);
    const patterns = Array.isArray(catalog.patterns) ? catalog.patterns : [];
    state.motionPatterns = patterns;
    renderMotionFeedbackHistory(catalog.feedback_history);
    renderCompactMotionPatternList(patterns);
    renderMotionTrainingPatternList(patterns);

    if (!patterns.length) {
        setPatternStatus('No motion patterns found.', 'var(--yellow)');
        state.motionTrainingSelectedPatternId = '';
        setMotionTrainingDetail(null);
        return;
    }

    if (state.motionTrainingSelectedPatternId && !patternById(state.motionTrainingSelectedPatternId)) {
        state.motionTrainingSelectedPatternId = '';
        setMotionTrainingDetail(null);
        renderMotionTrainingPatternList(patterns);
    }

    const errors = Array.isArray(catalog.errors) ? catalog.errors : [];
    if (errors.length) {
        setPatternStatus(`Loaded ${patterns.length} patterns. ${errors.length} file issue(s) need attention.`, 'var(--yellow)');
    } else {
        setPatternStatus(`Loaded ${patterns.length} patterns.`, 'var(--cyan)');
    }
}

async function startMotionTraining(patternId) {
    await selectMotionTrainingPattern(patternId);
    const data = await fetchJsonWithMessage('/motion_training/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pattern_id: patternId}),
    });
    if (data && data.motion_training) {
        updateMotionTrainingStatus(data.motion_training);
        el.statusText.textContent = data.motion_training.message || 'Motion training started.';
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start motion training.');
    }
}

async function playEditedMotionTrainingPreview() {
    if (!state.motionTrainingEditedPattern) {
        el.statusText.textContent = 'Select a pattern before playing an edited preview.';
        return;
    }
    const data = await fetchJsonWithMessage('/motion_training/preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pattern: editablePatternPayload()}),
    });
    if (data && data.motion_training) {
        updateMotionTrainingStatus(data.motion_training);
        el.statusText.textContent = data.motion_training.message || 'Edited preview started.';
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start edited preview.');
    }
}

async function playStudioCropPreview() {
    let pattern;
    try {
        pattern = studioCropPreviewPayload();
    } catch (error) {
        el.statusText.textContent = error.message || 'Select a valid crop before playing it.';
        return;
    }
    if (!pattern) {
        el.statusText.textContent = 'Import a funscript before playing a crop preview.';
        return;
    }
    const data = await fetchJsonWithMessage('/motion_training/preview', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pattern}),
    });
    if (data && data.motion_training) {
        updateMotionTrainingStatus(data.motion_training);
        el.statusText.textContent = data.motion_training.message || 'Crop preview started.';
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start crop preview.');
    }
}

async function saveStudioSourceProgram() {
    let program;
    try {
        program = studioSourceProgramPayload();
    } catch (error) {
        el.statusText.textContent = error.message || 'Import a funscript before saving a program.';
        return;
    }
    const data = await fetchJsonWithMessage('/import_motion_program', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({program}),
    });
    if (data && data.status === 'success') {
        if (data.motion_programs) renderMotionPrograms(data.motion_programs);
        setProgramStatus(`Saved program: ${data.program.name}.`, 'success');
        el.statusText.textContent = `Saved program: ${data.program.name}.`;
    } else {
        reportSaveFailure(el.motionProgramStatus || el.statusText, data, 'Could not save program.');
    }
}

async function stopMotionTraining() {
    const data = await apiCall('/motion_training/stop', {method: 'POST'});
    if (data && data.motion_training) {
        updateMotionTrainingStatus(data.motion_training);
        el.statusText.textContent = data.motion_training.message || 'Motion training stopped.';
    } else {
        reportSaveFailure(el.statusText, data, 'Could not stop motion training.');
    }
}

async function sendMotionTrainingFeedback(rating) {
    const patternId = state.motionTraining.pattern_id;
    if (!patternId || state.motionTraining.preview) {
        el.statusText.textContent = 'Play a saved pattern before sending feedback.';
        return;
    }
    const data = await fetchJsonWithMessage(`/motion_training/${encodeURIComponent(patternId)}/feedback`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rating}),
    });
    if (data && data.status === 'success') {
        updateMotionTrainingStatus(data.motion_training);
        renderMotionPatterns(data.motion_patterns);
        if (data.pattern) setMotionTrainingDetail(data.pattern);
        el.statusText.textContent = data.motion_training.message || 'Pattern feedback saved.';
    } else {
        reportSaveFailure(el.statusText, data, 'Could not save pattern feedback.');
    }
}

async function saveEditedMotionPattern() {
    if (!state.motionTrainingEditedPattern || !state.motionTrainingDirty) return;
    const payload = editablePatternPayload();
    const data = await fetchJsonWithMessage('/motion_patterns/save_generated', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({pattern: payload}),
    });
    if (data && data.status === 'success') {
        state.motionTrainingSelectedPatternId = data.pattern.id;
        renderMotionPatterns(data.motion_patterns);
        setMotionTrainingDetail(data.pattern);
        setMotionEditStatus(`Saved ${data.pattern.name}.`, 'var(--cyan)');
        el.statusText.textContent = `Saved motion pattern: ${data.pattern.name}.`;
    } else {
        reportSaveFailure(el.statusText, data, 'Could not save motion pattern.');
    }
}

export async function refreshMotionPatterns() {
    setPatternStatus('Loading motion patterns...');
    const data = await apiCall('/motion_patterns');
    if (data) renderMotionPatterns(data);
    return data;
}

async function importMotionPatternFile(file) {
    if (!file) return;
    setPatternStatus(`Importing ${file.name}...`);
    const body = new FormData();
    body.append('pattern', file);
    try {
        const response = await fetchWithConnectionState('/import_motion_pattern', {method: 'POST', body});
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== 'success') {
            const message = data.message || `Could not import ${file.name}.`;
            setPatternStatus(message, 'var(--yellow)');
            el.statusText.textContent = message;
            return;
        }
        el.statusText.textContent = `Imported pattern: ${data.pattern.name}.`;
        await refreshMotionPatterns();
    } catch (error) {
        const message = `Import failed: ${error.message}`;
        setPatternStatus(message, 'var(--yellow)');
        el.statusText.textContent = message;
    } finally {
        el.motionPatternImportInput.value = '';
    }
}

async function openMotionTrainingWorkspace() {
    if (!el.motionTrainingDialog) return;
    el.motionTrainingDialog.classList.add('open');
    let selectedId = state.motionTrainingSelectedPatternId
        || state.motionTraining.pattern_id
        || state.motionPatterns[0]?.id
        || '';

    if (!state.motionPatterns.length) {
        const data = await refreshMotionPatterns();
        const patterns = Array.isArray(data?.patterns) ? data.patterns : state.motionPatterns;
        selectedId = state.motionTrainingSelectedPatternId
            || state.motionTraining.pattern_id
            || patterns[0]?.id
            || '';
    }

    if (selectedId) await selectMotionTrainingPattern(selectedId);
    else setMotionTrainingDetail(null);
    window.requestAnimationFrame(() => drawMotionTrainingPreview());
}

function closeMotionTrainingWorkspace() {
    if (!el.motionTrainingDialog) return;
    el.motionTrainingDialog.classList.remove('open');
}

export function resizeCanvas() {
    updateMotionObservability(state.motionObservability);
}

function observationNumber(value, fallback = 0) {
    if (value === null || value === undefined || value === '') return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function finiteObservation(value) {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function clampPercent(value, fallback = 0) {
    return Math.max(0, Math.min(100, observationNumber(value, fallback)));
}

function updateMotionMeters(diagnostics = {}) {
    const relativeSpeed = Math.round(clampPercent(diagnostics.relative_speed, 0));
    const depth = Math.round(clampPercent(diagnostics.depth, 50));
    if (el.motionSpeedMeterFill) el.motionSpeedMeterFill.style.width = `${relativeSpeed}%`;
    if (el.motionSpeedMeterValue) el.motionSpeedMeterValue.textContent = `${relativeSpeed}%`;
    if (el.motionDepthMeterFill) el.motionDepthMeterFill.style.width = `${depth}%`;
    if (el.motionDepthMeterValue) el.motionDepthMeterValue.textContent = `${depth}%`;
}

function updateMotionDiagnosticsPanel(payload = {}) {
    if (!el.motionDiagnosticsPanel) return;
    const level = payload.diagnostics_level || state.motionDiagnosticsLevel || 'compact';
    state.motionDiagnosticsLevel = level;
    if (level === 'compact') {
        el.motionDiagnosticsPanel.hidden = true;
        el.motionDiagnosticsPanel.textContent = '';
        return;
    }
    const diagnostics = payload.diagnostics || {};
    const point = latestTracePoint(payload);
    const lastCommandTime = payload.last_command_time
        ? `${Math.max(0, Date.now() / 1000 - payload.last_command_time).toFixed(1)}s ago`
        : 'none';
    const lines = [
        `Source ${payload.source || 'idle'} | backend ${formatBackendName(payload.backend || state.motionBackend)} | playback ${payload.playback_active ? 'active' : 'idle'} | last ${lastCommandTime}`,
    ];
    const traceParts = [
        `Trace ${point.label || payload.label || 'none'}`,
        formatMotionFrame(point),
        ...formatMotionTraceTiming(point),
        point.is_pass_through_final ? 'pass-through final' : '',
    ].filter(Boolean);
    if (traceParts.length) lines.push(traceParts.join(' | '));
    if (level === 'debug') {
        lines.push([
            `Device pos ${observationNumber(diagnostics.position_mm, 0).toFixed(1)}mm`,
            `relative ${Math.round(clampPercent(diagnostics.relative_speed, 0))}%`,
            `physical ${Math.round(observationNumber(diagnostics.physical_speed, 0))}`,
            `depth/range ${Math.round(clampPercent(diagnostics.depth, 50))}%/${Math.round(clampPercent(diagnostics.range, 50))}%`,
            `HAMP ${diagnostics.hamp_started ? 'started' : 'stopped'}`,
        ].join(' | '));
        const visualizer = lastCylinderDebug || {};
        const visualizerParts = [
            `Visualizer ${visualizer.source || 'unknown'}`,
            Number.isFinite(visualizer.depth) ? `depth ${visualizer.depth.toFixed(1)}%` : '',
            Number.isFinite(visualizer.clock_ms) ? `clock ${Math.round(visualizer.clock_ms)}ms` : '',
            Number.isFinite(visualizer.first_point_ms) ? `window ${Math.round(visualizer.first_point_ms)}-${Math.round(Number.isFinite(visualizer.latest_point_ms) ? visualizer.latest_point_ms : visualizer.first_point_ms)}ms` : '',
            Number.isFinite(visualizer.hsp_state_age_ms) ? `state age ${Math.round(visualizer.hsp_state_age_ms)}ms` : '',
            visualizer.play_state !== undefined && visualizer.play_state !== null ? `state ${visualizer.play_state}` : '',
        ].filter(Boolean);
        if (visualizerParts.length) lines.push(visualizerParts.join(' | '));
        const refreshParts = [
            diagnostics.hsp_state_sse_active ? 'HSP SSE active' : '',
            diagnostics.hsp_state_sse_event_type ? `SSE ${diagnostics.hsp_state_sse_event_type}` : '',
            diagnostics.handy_sse_event_type && diagnostics.handy_sse_event_type !== diagnostics.hsp_state_sse_event_type ? `device SSE ${diagnostics.handy_sse_event_type}` : '',
            Number.isFinite(Number(diagnostics.handy_sse_event_age_ms)) ? `device SSE age ${Math.round(Number(diagnostics.handy_sse_event_age_ms))}ms` : '',
            Number.isFinite(Number(diagnostics.hsp_state_sse_failures)) && Number(diagnostics.hsp_state_sse_failures) > 0 ? `SSE failures ${diagnostics.hsp_state_sse_failures}` : '',
            diagnostics.hsp_state_sse_error ? `SSE error ${diagnostics.hsp_state_sse_error}` : '',
            diagnostics.hsp_state_refresh_active ? 'HSP state refresh active' : '',
            diagnostics.hsp_state_source ? `state source ${diagnostics.hsp_state_source}` : '',
            Number.isFinite(Number(diagnostics.hsp_state_refresh_failures)) && Number(diagnostics.hsp_state_refresh_failures) > 0 ? `failures ${diagnostics.hsp_state_refresh_failures}` : '',
            diagnostics.hsp_state_refresh_error ? `error ${diagnostics.hsp_state_refresh_error}` : '',
        ].filter(Boolean);
        if (refreshParts.length) lines.push(refreshParts.join(' | '));
    }
    el.motionDiagnosticsPanel.hidden = false;
    el.motionDiagnosticsPanel.textContent = lines.join('\n');
}

function normalizedPercentRange(minValue, maxValue, fallbackMin = 0, fallbackMax = 100) {
    const min = clampPercent(minValue, fallbackMin);
    const max = clampPercent(maxValue, fallbackMax);
    return {
        min: Math.min(min, max),
        max: Math.max(min, max),
    };
}

function calibratedCylinderRange(diagnostics = {}) {
    const range = diagnostics.calibrated_range || {};
    const minValue = range.min ?? diagnostics.min_depth;
    const maxValue = range.max ?? diagnostics.max_depth;
    const calibrated = normalizedPercentRange(minValue, maxValue, 0, 100);
    if (calibrated.max - calibrated.min < 1) return {min: 0, max: 100, width: 100};
    return {...calibrated, width: calibrated.max - calibrated.min};
}

function physicalDepthPercent(depth, diagnostics = {}) {
    if (depth === null || depth === undefined) {
        return clampPercent(diagnostics.physical_depth, 50);
    }
    const calibrated = calibratedCylinderRange(diagnostics);
    return clampPercent(calibrated.min + (calibrated.width * clampPercent(depth, 50) / 100), 50);
}

function activeStrokeZone(diagnostics = {}) {
    const zone = diagnostics.stroke_zone || {};
    if (zone.min !== undefined && zone.max !== undefined) {
        const active = normalizedPercentRange(zone.min, zone.max, 0, 100);
        return {...active, width: Math.max(0, active.max - active.min)};
    }

    const slide = diagnostics.slide_bounds || {};
    if (slide.min !== undefined && slide.max !== undefined) {
        const active = normalizedPercentRange(100 - slide.max, 100 - slide.min, 0, 100);
        return {...active, width: Math.max(0, active.max - active.min)};
    }

    const center = physicalDepthPercent(diagnostics.depth, diagnostics);
    const calibrated = calibratedCylinderRange(diagnostics);
    const rangeWidth = calibrated.width * clampPercent(diagnostics.range, 50) / 100;
    const active = normalizedPercentRange(center - rangeWidth / 2, center + rangeWidth / 2, calibrated.min, calibrated.max);
    return {
        min: Math.max(calibrated.min, active.min),
        max: Math.min(calibrated.max, active.max),
        width: Math.max(0, Math.min(calibrated.max, active.max) - Math.max(calibrated.min, active.min)),
    };
}

function fullTravelMm(diagnostics = {}) {
    return Math.max(1, observationNumber(diagnostics.full_travel_mm, 110));
}

function tracePointDepthPercent(point = {}, diagnostics = {}) {
    return physicalDepthPercent(point.output_depth ?? point.depth, diagnostics);
}

function setHandyCylinderPosition(depth) {
    if (el.handyCylinderPosition) {
        const roundedDepth = Math.round(clampPercent(depth, 50) * 1000) / 1000;
        el.handyCylinderPosition.style.top = `${roundedDepth}%`;
    }
}

function setCylinderDebug(details = {}) {
    lastCylinderDebug = {
        source: details.source || 'unknown',
        depth: finiteObservation(details.depth),
        clock_ms: finiteObservation(details.clock_ms),
        first_point_ms: finiteObservation(details.first_point_ms),
        latest_point_ms: finiteObservation(details.latest_point_ms),
        hsp_state_age_ms: finiteObservation(details.hsp_state_age_ms),
        play_state: details.play_state,
    };
}

function positionBackendAnimatedDepth(payload = {}, diagnostics = {}, nowSeconds = Date.now() / 1000) {
    const trace = Array.isArray(payload.trace) ? payload.trace : [];
    if (trace.length < 2) return physicalDepthPercent(diagnostics.depth, diagnostics);

    const latest = trace[trace.length - 1] || {};
    if (observationNumber(latest.speed, diagnostics.relative_speed) <= 0 || String(latest.label || '').includes('stopped')) {
        return tracePointDepthPercent(latest, diagnostics);
    }

    const previous = trace[trace.length - 2] || {};
    const startDepth = tracePointDepthPercent(previous, diagnostics);
    const endDepth = tracePointDepthPercent(latest, diagnostics);
    const distanceMm = fullTravelMm(diagnostics) * Math.abs(endDepth - startDepth) / 100;
    const velocity = Math.max(1, observationNumber(latest.physical_speed, diagnostics.physical_speed || 1));
    const duration = Math.max(0.08, distanceMm / velocity);
    const startTime = observationNumber(latest.t, nowSeconds);
    const progress = Math.max(0, Math.min(1, (nowSeconds - startTime) / duration));
    return startDepth + (endDepth - startDepth) * progress;
}

function payloadServerTimeToBrowserTime(payload = {}, serverTime) {
    const rawTime = finiteObservation(serverTime);
    if (rawTime === null) return null;
    const snapshotTime = finiteObservation(payload.snapshot_time);
    const receivedAt = finiteObservation(payload.received_at);
    if (snapshotTime !== null && receivedAt !== null) return rawTime + (receivedAt - snapshotTime);
    return rawTime;
}

function tracePointTime(point = {}, timeKey = 't', payload = {}) {
    const rawTime = finiteObservation(point[timeKey]);
    if (rawTime === null) return null;
    return timeKey === 't' ? payloadServerTimeToBrowserTime(payload, rawTime) : rawTime;
}

function continuousTracePoints(payload = {}) {
    const trace = Array.isArray(payload.trace) ? payload.trace : [];
    return trace
        .filter(point => (
            point
            && point.continuous
            && Number.isFinite(Number(point.t))
            && Number.isFinite(Number(point.output_depth ?? point.depth))
        ))
        .slice()
        .sort((left, right) => Number(left.t) - Number(right.t));
}

function recentContinuousTracePoints(payload = {}) {
    const continuous = continuousTracePoints(payload);
    if (continuous.length <= 2) return continuous;
    const latestTime = Number(continuous.at(-1).t);
    const recent = continuous.filter(point => latestTime - Number(point.t) <= 0.9);
    return recent.length >= 2 ? recent : continuous.slice(-2);
}

function traceDepthAt(points, visualTime, diagnostics = {}, timeKey = 't', payload = {}) {
    if (!points.length) return physicalDepthPercent(diagnostics.depth, diagnostics);
    if (points.length === 1) return tracePointDepthPercent(points[0], diagnostics);
    const first = points[0];
    const firstTime = tracePointTime(first, timeKey, payload);
    if (firstTime === null || visualTime <= firstTime) return tracePointDepthPercent(first, diagnostics);

    for (let index = 1; index < points.length; index += 1) {
        const previous = points[index - 1];
        const next = points[index];
        const previousTime = tracePointTime(previous, timeKey, payload);
        const nextTime = tracePointTime(next, timeKey, payload);
        if (previousTime === null || nextTime === null) continue;
        if (visualTime <= nextTime) {
            const duration = Math.max(0.001, nextTime - previousTime);
            const progress = Math.max(0, Math.min(1, (visualTime - previousTime) / duration));
            const startDepth = tracePointDepthPercent(previous, diagnostics);
            const endDepth = tracePointDepthPercent(next, diagnostics);
            return startDepth + (endDepth - startDepth) * progress;
        }
    }

    const latest = points.at(-1);
    return tracePointDepthPercent(latest, diagnostics);
}

function hspTracePoints(payload = {}) {
    const trace = Array.isArray(payload.trace) ? payload.trace : [];
    return trace
        .filter(point => (
            point
            && Number.isFinite(Number(point.hsp_point_time_ms))
            && Number.isFinite(Number(point.output_depth ?? point.depth))
        ))
        .slice()
        .sort((left, right) => Number(left.hsp_point_time_ms) - Number(right.hsp_point_time_ms));
}

function hspStateObservedAtSeconds(payload = {}, diagnostics = {}) {
    const ageMs = finiteObservation(diagnostics.hsp_state_age_ms);
    const receivedAt = finiteObservation(payload.received_at);
    if (ageMs !== null && receivedAt !== null) return receivedAt - (ageMs / 1000);
    return finiteObservation(diagnostics.hsp_state_observed_at);
}

function hspPlayStateIsAdvancing(playState, payload = {}) {
    const numericState = finiteObservation(playState);
    if (numericState !== null) return numericState === 1;

    const stateText = String(playState ?? '').trim().toLowerCase();
    if (!stateText) return Boolean(payload.playback_active);
    if (stateText.includes('playing')) return true;
    if (
        stateText.includes('paused')
        || stateText.includes('stopped')
        || stateText.includes('starving')
        || stateText.includes('not_initialized')
        || stateText.includes('not initialized')
    ) {
        return false;
    }
    return Boolean(payload.playback_active);
}

function hspPlaybackClockMs(payload = {}, diagnostics = {}, nowSeconds = Date.now() / 1000) {
    const hspState = diagnostics.hsp_state || {};
    const currentTimeMs = finiteObservation(hspState.current_time_ms);
    if (currentTimeMs === null) return null;

    const observedAt = hspStateObservedAtSeconds(payload, diagnostics);
    const isPlaying = hspPlayStateIsAdvancing(hspState.play_state, payload);
    const playbackRate = Math.max(0, finiteObservation(hspState.playbackRate ?? hspState.playback_rate) ?? 1);
    if (!isPlaying || observedAt === null || nowSeconds <= observedAt) return Math.max(0, currentTimeMs);
    return Math.max(0, currentTimeMs + ((nowSeconds - observedAt) * 1000 * playbackRate));
}

function hspBackendAnimatedDepth(payload = {}, diagnostics = {}, nowSeconds = Date.now() / 1000) {
    if (!diagnostics.hsp_streaming) return null;
    const ageMs = finiteObservation(diagnostics.hsp_state_age_ms);
    if (ageMs !== null && ageMs > HSP_STATE_MAX_EXTRAPOLATION_AGE_MS) {
        setCylinderDebug({
            source: 'hsp-state-stale',
            hsp_state_age_ms: ageMs,
            play_state: (diagnostics.hsp_state || {}).play_state,
        });
        return null;
    }
    const clockMs = hspPlaybackClockMs(payload, diagnostics, nowSeconds);
    if (clockMs === null) return null;
    const points = hspTracePoints(payload);
    if (!points.length) return null;
    const firstPointTime = Number(points[0].hsp_point_time_ms);
    const latestPointTime = Number(points.at(-1).hsp_point_time_ms);
    if (Number.isFinite(firstPointTime) && clockMs < firstPointTime - 250) return null;
    if (Number.isFinite(latestPointTime) && clockMs > latestPointTime + 250) return null;
    const depth = traceDepthAt(points, clockMs, diagnostics, 'hsp_point_time_ms');
    setCylinderDebug({
        source: 'hsp-state',
        depth,
        clock_ms: clockMs,
        first_point_ms: firstPointTime,
        latest_point_ms: latestPointTime,
        hsp_state_age_ms: diagnostics.hsp_state_age_ms,
        play_state: (diagnostics.hsp_state || {}).play_state,
    });
    return depth;
}

function liveContinuousTraceDepth(payload = {}, diagnostics = {}, nowSeconds = Date.now() / 1000, points = null) {
    const tracePoints = points || continuousTracePoints(payload);
    if (tracePoints.length < 2) return null;
    const firstTime = tracePointTime(tracePoints[0], 't', payload);
    const latestTime = tracePointTime(tracePoints.at(-1), 't', payload);
    if (firstTime === null || latestTime === null) return null;
    if (nowSeconds < firstTime - 0.25 || nowSeconds > latestTime + 0.25) return null;
    return traceDepthAt(tracePoints, nowSeconds, diagnostics, 't', payload);
}

function continuousBackendAnimatedDepth(payload = {}, diagnostics = {}, nowSeconds = Date.now() / 1000) {
    const hspDepth = hspBackendAnimatedDepth(payload, diagnostics, nowSeconds);
    if (hspDepth !== null) return hspDepth;

    const livePoints = continuousTracePoints(payload);
    const liveDepth = liveContinuousTraceDepth(payload, diagnostics, nowSeconds, livePoints);
    if (liveDepth !== null) {
        setCylinderDebug({source: 'trace-wall-time', depth: liveDepth, hsp_state_age_ms: diagnostics.hsp_state_age_ms});
        return liveDepth;
    }

    const points = recentContinuousTracePoints(payload);
    const latest = points.at(-1);
    if (!latest) {
        const depth = physicalDepthPercent(diagnostics.depth, diagnostics);
        setCylinderDebug({source: 'diagnostic-depth', depth, hsp_state_age_ms: diagnostics.hsp_state_age_ms});
        return depth;
    }

    const lastCommandTime = observationNumber(payload.last_command_time ?? latest.t, nowSeconds);
    const latestDepth = tracePointDepthPercent(latest, diagnostics);
    if (!payload.playback_active || nowSeconds - lastCommandTime > 1.5) {
        setCylinderDebug({source: 'latest-trace-depth', depth: latestDepth, hsp_state_age_ms: diagnostics.hsp_state_age_ms});
        return latestDepth;
    }
    if (points.length < 2) {
        setCylinderDebug({source: 'latest-trace-depth', depth: latestDepth, hsp_state_age_ms: diagnostics.hsp_state_age_ms});
        return latestDepth;
    }

    const firstTime = Number(points[0].t);
    const latestTime = Number(latest.t);
    const traceDuration = Math.max(0.08, latestTime - firstTime);
    const receivedAt = observationNumber(payload.received_at, nowSeconds);
    const elapsedSinceReceipt = Math.max(0, nowSeconds - receivedAt);
    const visualTime = firstTime + Math.min(elapsedSinceReceipt, traceDuration);
    const depth = traceDepthAt(points, visualTime, diagnostics);
    setCylinderDebug({source: 'trace-receipt-time', depth, hsp_state_age_ms: diagnostics.hsp_state_age_ms});
    return depth;
}

function cylinderAnimatedDepth(payload = {}, nowSeconds = Date.now() / 1000) {
    const diagnostics = payload.diagnostics || {};
    const restingPosition = physicalDepthPercent(diagnostics.depth, diagnostics);
    const physicalSpeed = Math.max(0, observationNumber(diagnostics.physical_speed, 0));
    if (payload.backend === 'continuous') return continuousBackendAnimatedDepth(payload, diagnostics, nowSeconds);
    const isPositionBackend = payload.backend === 'position';
    if (isPositionBackend) {
        const depth = positionBackendAnimatedDepth(payload, diagnostics, nowSeconds);
        setCylinderDebug({source: 'position-plan', depth});
        return depth;
    }
    if (physicalSpeed <= 0 || !diagnostics.hamp_started) {
        setCylinderDebug({source: 'diagnostic-depth', depth: restingPosition});
        return restingPosition;
    }

    const active = activeStrokeZone(diagnostics);
    if (active.width < 2) {
        setCylinderDebug({source: 'diagnostic-depth', depth: restingPosition});
        return restingPosition;
    }

    const travelMm = Math.max(1, fullTravelMm(diagnostics) * (active.width / 100));
    const lastCommandTime = observationNumber(payload.last_command_time, nowSeconds);
    const percentPerCycle = active.width * 2;
    const percentPerSecond = physicalSpeed / fullTravelMm(diagnostics) * 100;
    const startingPosition = Math.max(active.min, Math.min(active.max, restingPosition));
    const startingOffset = startingPosition - active.min;
    const travelled = (startingOffset + Math.max(0, nowSeconds - lastCommandTime) * percentPerSecond) % percentPerCycle;
    const phase = travelled <= active.width ? travelled : percentPerCycle - travelled;
    const depth = active.min + phase;
    setCylinderDebug({source: 'hamp-estimate', depth});
    return depth;
}

function updateHandyCylinder(payload = {}) {
    setHandyCylinderPosition(cylinderAnimatedDepth(payload));
}

export function updateMotionObservability(payload = {}) {
    payload = payload || {};
    const diagnostics = payload.diagnostics || {};
    updateMotionMeters(diagnostics);
    updateMotionSequenceIndicator(payload);
    updateHandyCylinder(payload);
    updateMotionDiagnosticsPanel(payload);
    updateHandyConnectionStatusFromMotion(payload);
}

function startHandyCylinderAnimation() {
    if (state.motionCylinderAnimationStarted) return;
    state.motionCylinderAnimationStarted = true;
    const tick = () => {
        if (state.motionObservability) {
            setHandyCylinderPosition(cylinderAnimatedDepth(state.motionObservability, Date.now() / 1000));
        }
        window.requestAnimationFrame(tick);
    };
    window.requestAnimationFrame(tick);
}

function activeModeDisplayName(modeName) {
    return {
        auto: 'Legacy Auto',
        edging: 'Edge',
        milking: 'Milk',
        freestyle: 'Freestyle',
    }[modeName] || modeName || '';
}

function normalizeChatIntensityGuide(guide) {
    const normalized = String(guide || '').trim().toLowerCase().replace(/-/g, '_');
    return ['steady', 'ramp_up', 'ramp_down', 'variable'].includes(normalized) ? normalized : 'steady';
}

function chatIntensityGuideLabel(guide) {
    return {
        steady: 'Arc Steady',
        ramp_up: 'Arc Up',
        ramp_down: 'Arc Down',
        variable: 'Arc Variable',
    }[normalizeChatIntensityGuide(guide)];
}

function nextChatIntensityGuide(guide) {
    return {
        steady: 'ramp_up',
        ramp_up: 'ramp_down',
        ramp_down: 'variable',
        variable: 'steady',
    }[normalizeChatIntensityGuide(guide)];
}

export function updateChatIntensityGuideUi(guide, countDirection = 'steady') {
    const normalized = normalizeChatIntensityGuide(guide);
    state.chatIntensityGuide = normalized;
    state.chatIntensityCountDirection = countDirection || 'steady';
    const button = el.topBarIntensityGuideBtn;
    if (!button) return;
    button.textContent = chatIntensityGuideLabel(normalized);
    button.classList.remove('is-on', 'is-ramp-up', 'is-ramp-down', 'is-variable');
    if (normalized === 'ramp_up') button.classList.add('is-on', 'is-ramp-up');
    if (normalized === 'ramp_down') button.classList.add('is-on', 'is-ramp-down');
    if (normalized === 'variable') button.classList.add('is-on', 'is-variable');
    button.setAttribute('aria-pressed', normalized === 'steady' ? 'false' : 'true');
    button.setAttribute('aria-label', `Intensity arc ${normalized.replace('_', ' ')}`);
    button.title = normalized === 'steady'
        ? 'LLM intensity arc: steady'
        : `LLM intensity arc: ${normalized.replace('_', ' ')}`;
}

export function updateChatSessionTimer(elapsedSeconds, guide = state.chatIntensityGuide, countDirection = state.chatIntensityCountDirection) {
    updateChatIntensityGuideUi(guide, countDirection);
    const numericElapsed = Number(elapsedSeconds);
    if (Number.isFinite(numericElapsed)) {
        state.chatSessionElapsedSeconds = Math.max(0, Math.round(numericElapsed));
    } else {
        state.chatSessionElapsedSeconds = null;
    }
    if (state.activeModeName || !el.edgingTimer || state.chatSessionElapsedSeconds === null) return;

    const elapsed = formatClockElapsed(state.chatSessionElapsedSeconds);
    const guideLabel = chatIntensityGuideLabel(state.chatIntensityGuide).replace('Arc ', '');
    if (el.activeModeStatus) {
        el.activeModeStatus.hidden = false;
        el.activeModeStatus.classList.remove('paused');
        el.activeModeStatus.title = `Chat active for ${elapsed}; intensity guide ${guideLabel}`;
    }
    if (el.activeModeLabel) {
        el.activeModeLabel.textContent = 'Chat';
        el.activeModeLabel.title = `Chat intensity guide: ${guideLabel}`;
    }
    el.edgingTimer.textContent = elapsed;
    el.edgingTimer.title = `Chat active for ${elapsed}`;
}

export function updateActiveModeTimer(modeName, elapsedSeconds, paused = state.motionPaused) {
    if (!el.edgingTimer) return;
    const normalizedMode = modeName || '';
    const nextElapsed = normalizedMode ? Math.max(0, Math.round(Number(elapsedSeconds) || 0)) : null;
    const previousMode = state.activeModeName || '';
    const previousElapsed = state.activeModeElapsedSeconds;
    const timerStarted = Boolean(normalizedMode) && (
        normalizedMode !== previousMode
        || previousElapsed === null
        || (nextElapsed <= 1 && Number(previousElapsed) > 2)
    );

    state.activeModeName = normalizedMode;
    if (timerStarted) resetMotionSequenceLog();

    if (!normalizedMode) {
        // Hide the timer UI on stop, but keep state.activeModeElapsedSeconds
        // frozen at its last value so any sequence-log entries appended after
        // stop keep their real elapsed timecode instead of rewriting to 00:00.
        // The elapsed counter (and the log) only reset when a new mode starts.
        if (el.activeModeStatus) {
            el.activeModeStatus.hidden = true;
            el.activeModeStatus.classList.remove('paused');
            el.activeModeStatus.title = '';
        }
        if (el.activeModeLabel) {
            el.activeModeLabel.textContent = '';
            el.activeModeLabel.title = '';
        }
        el.edgingTimer.textContent = '';
        el.edgingTimer.title = '';
        return;
    }
    const label = activeModeDisplayName(normalizedMode);
    state.activeModeElapsedSeconds = nextElapsed;
    const elapsed = formatClockElapsed(state.activeModeElapsedSeconds);
    if (el.activeModeStatus) {
        el.activeModeStatus.hidden = false;
        if (paused) el.activeModeStatus.classList.add('paused');
        else el.activeModeStatus.classList.remove('paused');
        el.activeModeStatus.title = paused ? `${label} paused at ${elapsed}` : `${label} active for ${elapsed}`;
    }
    if (el.activeModeLabel) {
        el.activeModeLabel.textContent = label;
        el.activeModeLabel.title = paused ? `${label} paused` : label;
    }
    el.edgingTimer.textContent = elapsed;
    el.edgingTimer.title = paused ? `Paused at ${elapsed}` : `Active for ${elapsed}`;
}

export async function pollMotionStatus() {
    const data = await apiCall('/get_status');
    if (!data) return;
    const emoji = {
        Curious: '\u{1F914}',
        Teasing: '\u{1F609}',
        Playful: '\u{1F61C}',
        Loving: '\u2764\uFE0F',
        Excited: '\u2728',
        Passionate: '\u{1F525}',
        Seductive: '\u{1F608}',
        Anticipatory: '\u{1F440}',
        Breathless: '\u{1F975}',
        Dominant: '\u{1F451}',
        Submissive: '\u{1F647}\u200D\u2640\uFE0F',
        Vulnerable: '\u{1F633}',
        Confident: '\u{1F60F}',
        Intimate: '\u{1F970}',
        Needy: '\u{1F97A}',
        Overwhelmed: '\u{1F92F}',
        Afterglow: '\u{1F60C}',
    }[data.mood] || '';
    el.moodDisplay.textContent = `Mood: ${data.mood} ${emoji}`;
    if (el.imCloseBtn) {
        el.imCloseBtn.style.display = ['edging', 'milking', 'freestyle'].includes(data.active_mode) ? 'block' : 'none';
    }
    state.motionPaused = Boolean(data.motion_paused);
    updatePauseResumeUi(state.motionPaused);
    updateActiveModeTimer(data.active_mode, data.active_mode_elapsed_seconds, Boolean(data.active_mode_paused));
    updateChatSessionTimer(
        data.chat_elapsed_seconds,
        data.arc || data.chat_arc || data.chat_intensity_guide,
        data.chat_intensity_count_direction,
    );
    state.motionObservability = data.motion_observability || {
        backend: state.motionBackend,
        source: 'status',
        diagnostics: {
            relative_speed: data.relative_speed || 0,
            physical_speed: data.speed || 0,
            depth: data.depth || 50,
            range: data.range || 50,
        },
        trace: [],
    };
    state.motionObservability.received_at = Date.now() / 1000;
    updateMotionObservability(state.motionObservability);
    if (data.motion_training) updateMotionTrainingStatus(data.motion_training);
}

async function likeLastMove() {
    const data = await apiCall('/like_last_move', {method: 'POST'});
    if (data && data.status === 'boosted') {
        if (data.motion_patterns) renderMotionPatterns(data.motion_patterns);
        const patternText = data.pattern ? ` Pattern weight updated for ${data.pattern.name}.` : '';
        el.statusText.textContent = `Saved '${data.name}' to my memory!${patternText}`;
    } else {
        reportSaveFailure(el.statusText, data, 'Status: No active move to like.');
    }
}

async function dislikeLastMove() {
    const data = await apiCall('/dislike_last_move', {method: 'POST'});
    if (data && data.status === 'success') {
        if (data.motion_patterns) renderMotionPatterns(data.motion_patterns);
        el.statusText.textContent = data.message || 'Saved thumbs down feedback.';
    } else {
        reportSaveFailure(el.statusText, data, 'No fixed motion pattern is active to rate.');
    }
}

async function startAutoMode() {
    el.statusText.textContent = 'Starting Legacy Auto...';
    const data = await apiCall('/start_auto_mode', {method: 'POST'});
    if (data && data.status === 'auto_started') {
        el.statusText.textContent = 'Legacy Auto started.';
        if (el.imCloseBtn) el.imCloseBtn.style.display = 'none';
        updatePauseResumeUi(false);
        updateActiveModeTimer('auto', 0, false);
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start Legacy Auto.');
    }
}

async function startEdgingMode() {
    el.statusText.textContent = 'Starting edging mode...';
    const data = await apiCall('/start_edging_mode', {method: 'POST'});
    if (data && data.status === 'edging_started') {
        el.statusText.textContent = 'Edging mode started.';
        el.imCloseBtn.style.display = 'block';
        updatePauseResumeUi(false);
        updateActiveModeTimer('edging', 0, false);
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start edging mode.');
    }
}

async function startMilkingMode() {
    el.statusText.textContent = 'Starting milking mode...';
    const data = await apiCall('/start_milking_mode', {method: 'POST'});
    if (data && data.status === 'milking_started') {
        el.statusText.textContent = 'Milking mode started.';
        el.imCloseBtn.style.display = 'block';
        updatePauseResumeUi(false);
        updateActiveModeTimer('milking', 0, false);
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start milking mode.');
    }
}

async function saveLlmEdgePermissions() {
    const [autospeakMin, autospeakMax] = readAutospeakTimingPair();
    const data = await apiCall('/set_llm_edge_permissions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            allow_llm_edge_in_freestyle: Boolean(el.allowLlmEdgeFreestyleCheckbox?.checked),
            allow_llm_edge_in_chat: Boolean(el.allowLlmEdgeChatCheckbox?.checked),
            allow_llm_mode_actions_in_chat: Boolean(el.allowLlmModeActionsChatCheckbox?.checked),
            autospeak_enabled: Boolean(state.autospeakEnabled),
            autospeak_min_seconds: autospeakMin,
            autospeak_max_seconds: autospeakMax,
        }),
    });
    if (data && data.status === 'success') {
        populateMotionSettings(data);
        if (el.llmEdgePermissionsStatus) el.llmEdgePermissionsStatus.textContent = 'LLM permissions saved.';
        el.statusText.textContent = 'LLM permissions saved.';
    } else {
        reportSaveFailure(el.llmEdgePermissionsStatus || el.statusText, data, 'Could not save LLM permissions.');
    }
}

async function saveAutospeakToggle(enabled) {
    const previousEnabled = state.autospeakEnabled;
    updateAutospeakToggleUi(enabled);
    const data = await apiCall('/set_llm_edge_permissions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({autospeak_enabled: Boolean(enabled)}),
    });
    if (data && data.status === 'success') {
        populateMotionSettings(data);
        el.statusText.textContent = state.autospeakEnabled ? 'Autospeak enabled.' : 'Autospeak disabled.';
    } else {
        updateAutospeakToggleUi(previousEnabled);
        reportSaveFailure(el.statusText, data, 'Could not save Autospeak setting.');
    }
}

async function saveChatIntensityGuide(guide) {
    const previousGuide = state.chatIntensityGuide;
    const normalizedGuide = normalizeChatIntensityGuide(guide);
    updateChatIntensityGuideUi(normalizedGuide);
    const data = await apiCall('/set_chat_intensity_guide', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({guide: normalizedGuide}),
    });
    if (data && data.status === 'success') {
        updateChatSessionTimer(
            data.chat_elapsed_seconds,
            data.arc || data.chat_arc || data.chat_intensity_guide,
            data.chat_intensity_count_direction,
        );
        el.statusText.textContent = `Intensity arc set to ${chatIntensityGuideLabel(state.chatIntensityGuide).replace('Arc ', '')}.`;
    } else {
        updateChatIntensityGuideUi(previousGuide);
        reportSaveFailure(el.statusText, data, 'Could not update intensity arc.');
    }
}

async function startFreestyleMode() {
    el.statusText.textContent = 'Starting Freestyle...';
    const data = await apiCall('/start_freestyle_mode', {method: 'POST'});
    if (data && data.status === 'freestyle_started') {
        el.statusText.textContent = 'Freestyle started.';
        el.imCloseBtn.style.display = 'block';
        updatePauseResumeUi(false);
        updateActiveModeTimer('freestyle', 0, false);
    } else {
        reportSaveFailure(el.statusText, data, 'Could not start Freestyle.');
    }
}

export function initMotionControls({sendUserMessage}) {
    configureMotionPatternList({renderMotionPatterns, setMotionTrainingDetail});
    configureMotionFeedbackControls({renderMotionPatterns, renderMotionStyleOptions});
    configureMotionProgramList({openMotionProgramWindow});
    configureMotionProgramPlayer({renderMotionPatterns, updateMotionTrainingStatus});
    bindMotionProgramControls();
    bindMotionProgramPlayerControls();
    D.getElementById('like-this-move-btn').addEventListener('click', likeLastMove);
    D.getElementById('dislike-this-move-btn')?.addEventListener('click', dislikeLastMove);
    el.edgingModeBtn.addEventListener('click', startEdgingMode);
    el.freestyleModeBtn?.addEventListener('click', startFreestyleMode);
    el.toggleMemoryBtn?.addEventListener('click', toggleLongTermMemory);
    el.motionSpeedMinSlider.addEventListener('input', normalizeMotionSpeedLimits);
    el.motionSpeedMaxSlider.addEventListener('input', normalizeMotionSpeedLimits);
    el.saveMotionBackendBtn.addEventListener('click', saveMotionBackend);
    el.motionBackendSelect.addEventListener('change', () => updateMotionBackendUi(el.motionBackendSelect.value));
    el.saveMotionStyleBtn?.addEventListener('click', saveMotionStyle);
    el.resetMotionPreferencesBtn?.addEventListener('click', resetMotionPreferences);
    el.motionStyleSelect?.addEventListener('change', () => updateMotionStyleUi(el.motionStyleSelect.value));
    el.saveMotionReverseDirectionBtn?.addEventListener('click', saveMotionReverseDirection);
    el.motionDirectionNormalRadio?.addEventListener('change', () => updateMotionReverseDirectionUi(false));
    el.motionDirectionReverseRadio?.addEventListener('change', () => updateMotionReverseDirectionUi(true));
    D.getElementById('save-motion-speed-limits').addEventListener('click', saveMotionSpeedLimits);
    D.getElementById('save-timings-btn').addEventListener('click', saveModeTimings);
    el.autospeakMinSecondsInput?.addEventListener('change', readAutospeakTimingPair);
    el.autospeakMaxSecondsInput?.addEventListener('change', readAutospeakTimingPair);
    el.saveLlmEdgePermissionsBtn?.addEventListener('click', saveLlmEdgePermissions);
    el.topBarAutospeakToggleBtn?.addEventListener('click', async () => {
        await saveAutospeakToggle(!state.autospeakEnabled);
    });
    el.topBarIntensityGuideBtn?.addEventListener('click', async () => {
        await saveChatIntensityGuide(nextChatIntensityGuide(state.chatIntensityGuide));
    });
    el.refreshMotionPatternsBtn.addEventListener('click', refreshMotionPatterns);
    el.exportMotionLibraryBtn?.addEventListener('click', () => {
        window.location.href = '/motion_library/export';
    });
    if (el.motionFeedbackAutoDisableCheckbox) {
        el.motionFeedbackAutoDisableCheckbox.addEventListener('change', saveMotionFeedbackOptions);
    }
    if (el.motionPatternLibraryFreestyleCheckbox) {
        el.motionPatternLibraryFreestyleCheckbox.addEventListener('change', saveMotionFeedbackOptions);
    }
    if (el.motionPatternLibraryChatCheckbox) {
        el.motionPatternLibraryChatCheckbox.addEventListener('change', saveMotionFeedbackOptions);
    }
    el.importMotionPatternBtn.addEventListener('click', () => el.motionPatternImportInput.click());
    el.motionPatternImportInput.addEventListener('change', event => importMotionPatternFile(event.target.files[0]));
    if (el.openMotionTrainingBtn) el.openMotionTrainingBtn.addEventListener('click', openMotionTrainingWorkspace);
    if (el.closeMotionTrainingBtn) el.closeMotionTrainingBtn.addEventListener('click', closeMotionTrainingWorkspace);
    if (el.motionTrainingDialog) {
        el.motionTrainingDialog.addEventListener('click', event => {
            if (event.target === el.motionTrainingDialog) closeMotionTrainingWorkspace();
        });
    }
    bindMotionPatternStudioControls();
    bindMotionPauseControls({
        sendUserMessage,
        updateActiveModeTimer,
        closeMotionTrainingWorkspace,
    });
    window.addEventListener('resize', drawOpenMotionTrainingPreview);
    D.addEventListener?.('visibilitychange', () => {
        if (!D.hidden) pollMotionStatus();
    });
    el.motionTransformSmoothBtn?.addEventListener('click', smoothEditedPattern);
    el.motionTransformSimplifyBtn?.addEventListener('click', simplifyEditedPattern);
    el.motionTransformHarshenBtn?.addEventListener('click', harshenEditedPattern);
    el.motionTransformDurationDownBtn?.addEventListener('click', () => setEditedPatternDuration(0.85, 'Shortened the temporary copy.'));
    el.motionTransformDurationUpBtn?.addEventListener('click', () => setEditedPatternDuration(1.18, 'Lengthened the temporary copy.'));
    el.motionTransformTempoDownBtn?.addEventListener('click', () => setEditedPatternTempo(0.85, 'Lowered the temporary copy tempo.'));
    el.motionTransformTempoUpBtn?.addEventListener('click', () => setEditedPatternTempo(1.18, 'Raised the temporary copy tempo.'));
    D.querySelectorAll('[data-range-step-target]').forEach(button => {
        button.addEventListener('click', () => stepMotionTrainingRangeInput(button));
    });
    el.motionTransformRangeBtn?.addEventListener('click', remapEditedPatternRange);
    el.motionTransformResetBtn?.addEventListener('click', resetEditedPattern);
    el.playMotionTrainingPreviewBtn?.addEventListener('click', playEditedMotionTrainingPreview);
    el.motionStudioPlayCropBtn?.addEventListener('click', playStudioCropPreview);
    el.motionStudioSaveProgramBtn?.addEventListener('click', saveStudioSourceProgram);
    el.saveMotionTrainingPatternBtn?.addEventListener('click', saveEditedMotionPattern);
    el.stopMotionTrainingBtn.addEventListener('click', stopMotionTraining);
    el.motionTrainingFeedbackUp.addEventListener('click', () => sendMotionTrainingFeedback('thumbs_up'));
    el.motionTrainingFeedbackNeutral.addEventListener('click', () => sendMotionTrainingFeedback('neutral'));
    el.motionTrainingFeedbackDown.addEventListener('click', () => sendMotionTrainingFeedback('thumbs_down'));
    el.settingsTabs.forEach(tab => {
        if (tab.dataset.settingsTab === 'motion') {
            tab.addEventListener('click', refreshMotionPatterns);
            tab.addEventListener('click', refreshMotionPrograms);
        }
    });
    D.getElementById('start-auto-btn').addEventListener('click', startAutoMode);
    D.getElementById('milking-mode-btn').addEventListener('click', startMilkingMode);
    updateMotionTrainingStatus();
    updateMotionTrainingEditButtons();
    startHandyCylinderAnimation();
    refreshMotionPatterns();
    refreshMotionPrograms();
}
