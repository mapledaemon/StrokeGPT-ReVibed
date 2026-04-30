import { D, apiCall, clampNumber, el, setSliderValue, state } from './context.js';
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
    createPatternExportButton,
    createPatternFeedbackResetButton,
    createPatternText,
    formatPatternDuration,
    formatPatternMetadata,
    normalizedActions,
    patternById,
    patternDisplayName,
    patternHasFeedbackState,
    renderCompactMotionPatternList,
    setPatternStatus,
    updatePatternStats,
} from './motion/pattern-list.js';
import {
    configureMotionFeedbackControls,
    renderMotionFeedbackHistory,
    saveMotionFeedbackOptions,
} from './motion/feedback-controls.js';
import {
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
    smoothEditedPattern,
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
    setMotionPatternWeight,
    setPatternStatus,
    updatePatternStats,
} from './motion/pattern-list.js';
// Compatibility shim - do not extend. New code imports from './motion/feedback-controls.js'.
export {
    configureMotionFeedbackControls,
    renderMotionFeedbackHistory,
    saveMotionFeedbackOptions,
} from './motion/feedback-controls.js';
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
    smoothEditedPattern,
    stepMotionTrainingRangeInput,
    syncRangeInputsFromPattern,
    updateMotionTrainingEditButtons,
    updateMotionTrainingTimingReadouts,
} from './motion/training-editor.js';

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
        id: 'hamp',
        label: 'HAMP continuous',
        description: 'Recommended default for smooth ongoing app motion.',
        experimental: false,
    };
}

function updateMotionBackendUi(backendId) {
    state.motionBackend = backendId === 'position' ? 'position' : 'hamp';
    if (el.motionBackendSelect) el.motionBackendSelect.value = state.motionBackend;
    const details = motionBackendDetails(state.motionBackend);
    const suffix = details.experimental ? ' (experimental)' : '';
    if (el.motionBackendStatus) {
        el.motionBackendStatus.textContent = `Current backend: ${details.label}${suffix}. ${details.description || ''}`.trim();
    }
    if (el.appMotionBackendBadge) {
        el.appMotionBackendBadge.textContent = `App motion: ${details.label}${suffix}`;
    }
}

function renderMotionBackendOptions(options = [], currentBackend = 'hamp') {
    state.motionBackends = options.length ? options : [
        {
            id: 'hamp',
            label: 'HAMP continuous',
            description: 'Recommended default for smooth ongoing app motion.',
            experimental: false,
        },
        {
            id: 'position',
            label: 'Flexible position/script',
            description: 'Experimental path for pattern fidelity and spatial scripts.',
            experimental: true,
        },
    ];
    if (el.motionBackendSelect) {
        el.motionBackendSelect.replaceChildren();
        state.motionBackends.forEach(backend => {
            const option = D.createElement('option');
            option.value = backend.id;
            option.textContent = `${backend.label}${backend.experimental ? ' (experimental)' : backend.id === 'hamp' ? ' (recommended)' : ''}`;
            el.motionBackendSelect.appendChild(option);
        });
    }
    updateMotionBackendUi(currentBackend);
}

function updateMemoryToggleUi(enabled) {
    state.useLongTermMemory = Boolean(enabled);
    if (!el.toggleMemoryBtn) return;
    el.toggleMemoryBtn.textContent = `Memories: ${state.useLongTermMemory ? 'ON' : 'OFF'}`;
    el.toggleMemoryBtn.setAttribute('aria-pressed', state.useLongTermMemory ? 'true' : 'false');
}

export function populateMotionSettings(data = {}) {
    const timings = data.timings || {};
    state.motionDiagnosticsLevel = data.motion_diagnostics_level || state.motionDiagnosticsLevel || 'compact';
    state.motionFeedbackAutoDisable = data.motion_feedback_auto_disable ?? state.motionFeedbackAutoDisable ?? false;
    state.allowLlmEdgeInFreestyle = data.allow_llm_edge_in_freestyle ?? state.allowLlmEdgeInFreestyle ?? true;
    state.allowLlmEdgeInChat = data.allow_llm_edge_in_chat ?? state.allowLlmEdgeInChat ?? true;
    if (el.motionFeedbackAutoDisableCheckbox) {
        el.motionFeedbackAutoDisableCheckbox.checked = Boolean(state.motionFeedbackAutoDisable);
    }
    if (el.allowLlmEdgeFreestyleCheckbox) {
        el.allowLlmEdgeFreestyleCheckbox.checked = Boolean(state.allowLlmEdgeInFreestyle);
    }
    if (el.allowLlmEdgeChatCheckbox) {
        el.allowLlmEdgeChatCheckbox.checked = Boolean(state.allowLlmEdgeInChat);
    }
    if (el.llmEdgePermissionsStatus) {
        el.llmEdgePermissionsStatus.textContent = `Freestyle edge: ${state.allowLlmEdgeInFreestyle ? 'allowed' : 'blocked'}. Chat edge: ${state.allowLlmEdgeInChat ? 'allowed' : 'blocked'}.`;
    }
    updateMemoryToggleUi(data.use_long_term_memory ?? state.useLongTermMemory);
    renderMotionBackendOptions(data.motion_backends || state.motionBackends, data.motion_backend || state.motionBackend);
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
}

async function saveMotionBackend() {
    const motionBackend = el.motionBackendSelect?.value || 'hamp';
    const data = await apiCall('/set_motion_backend', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({motion_backend: motionBackend}),
    });
    if (data && data.status === 'success') {
        updateMotionBackendUi(data.motion_backend);
        el.statusText.textContent = `Motion backend saved: ${motionBackendDetails(data.motion_backend).label}.`;
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
    }
}

async function toggleLongTermMemory() {
    const data = await apiCall('/toggle_memory', {method: 'POST'});
    if (data && data.status === 'success') {
        updateMemoryToggleUi(data.use_long_term_memory);
        el.statusText.textContent = `Long-term memories ${data.use_long_term_memory ? 'enabled' : 'disabled'}.`;
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
        const response = await fetch(endpoint, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            const message = data.message || `Request failed: ${response.status}`;
            el.statusText.textContent = message;
            return data;
        }
        return data;
    } catch (error) {
        el.statusText.textContent = `Request failed: ${error.message}`;
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
        main.appendChild(createPatternText(pattern));

        const actions = D.createElement('div');
        actions.className = 'motion-pattern-row-actions';

        const playButton = D.createElement('button');
        playButton.type = 'button';
        playButton.className = 'my-button motion-pattern-play';
        playButton.textContent = 'Play';
        playButton.addEventListener('click', event => {
            event.stopPropagation();
            startMotionTraining(pattern.id);
        });

        actions.append(playButton);
        if (patternHasFeedbackState(pattern)) actions.append(createPatternFeedbackResetButton(pattern));
        actions.append(createPatternExportButton(pattern));
        row.append(main, actions);
        el.motionTrainingPatternList.appendChild(row);
    });
}

export function renderMotionPatterns(catalog = {}) {
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
    }
}

async function stopMotionTraining() {
    const data = await apiCall('/motion_training/stop', {method: 'POST'});
    if (data && data.motion_training) {
        updateMotionTrainingStatus(data.motion_training);
        el.statusText.textContent = data.motion_training.message || 'Motion training stopped.';
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
        const response = await fetch('/import_motion_pattern', {method: 'POST', body});
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

function setHandyCylinderPosition(depth) {
    if (el.handyCylinderPosition) {
        el.handyCylinderPosition.style.top = `${clampPercent(depth, 50)}%`;
    }
}

function positionBackendAnimatedDepth(payload = {}, diagnostics = {}, nowSeconds = Date.now() / 1000) {
    const trace = Array.isArray(payload.trace) ? payload.trace : [];
    if (trace.length < 2) return physicalDepthPercent(diagnostics.depth, diagnostics);

    const latest = trace[trace.length - 1] || {};
    if (observationNumber(latest.speed, diagnostics.relative_speed) <= 0 || String(latest.label || '').includes('stopped')) {
        return physicalDepthPercent(latest.depth ?? diagnostics.depth, diagnostics);
    }

    const previous = trace[trace.length - 2] || {};
    const startDepth = physicalDepthPercent(previous.depth, diagnostics);
    const endDepth = physicalDepthPercent(latest.depth, diagnostics);
    const distanceMm = fullTravelMm(diagnostics) * Math.abs(endDepth - startDepth) / 100;
    const velocity = Math.max(1, observationNumber(latest.physical_speed, diagnostics.physical_speed || 1));
    const duration = Math.max(0.08, distanceMm / velocity);
    const startTime = observationNumber(latest.t, nowSeconds);
    const progress = Math.max(0, Math.min(1, (nowSeconds - startTime) / duration));
    return startDepth + (endDepth - startDepth) * progress;
}

function cylinderAnimatedDepth(payload = {}, nowSeconds = Date.now() / 1000) {
    const diagnostics = payload.diagnostics || {};
    const restingPosition = physicalDepthPercent(diagnostics.depth, diagnostics);
    const physicalSpeed = Math.max(0, observationNumber(diagnostics.physical_speed, 0));
    const isPositionBackend = payload.backend === 'position';
    if (isPositionBackend) return positionBackendAnimatedDepth(payload, diagnostics, nowSeconds);
    if (physicalSpeed <= 0 || !diagnostics.hamp_started) return restingPosition;

    const active = activeStrokeZone(diagnostics);
    if (active.width < 2) return restingPosition;

    const travelMm = Math.max(1, fullTravelMm(diagnostics) * (active.width / 100));
    const lastCommandTime = observationNumber(payload.last_command_time, nowSeconds);
    const percentPerCycle = active.width * 2;
    const percentPerSecond = physicalSpeed / fullTravelMm(diagnostics) * 100;
    const startingPosition = Math.max(active.min, Math.min(active.max, restingPosition));
    const startingOffset = startingPosition - active.min;
    const travelled = (startingOffset + Math.max(0, nowSeconds - lastCommandTime) * percentPerSecond) % percentPerCycle;
    const phase = travelled <= active.width ? travelled : percentPerCycle - travelled;
    return active.min + phase;
}

function updateHandyCylinder(payload = {}) {
    setHandyCylinderPosition(cylinderAnimatedDepth(payload));
}

export function updateMotionObservability(payload = {}) {
    payload = payload || {};
    const diagnostics = payload.diagnostics || {};
    updateMotionMeters(diagnostics);
    updateMotionSequenceIndicator(payload);
    updateMotionDiagnosticsPanel(payload);
    updateHandyCylinder(payload);
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
        auto: 'Auto',
        edging: 'Edge',
        milking: 'Milk',
        freestyle: 'Freestyle',
    }[modeName] || modeName || '';
}

function updateActiveModeTimer(modeName, elapsedSeconds, paused = state.motionPaused) {
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
        el.edgingTimer.style.display = 'none';
        el.edgingTimer.textContent = '';
        el.edgingTimer.title = '';
        return;
    }
    const label = activeModeDisplayName(normalizedMode);
    state.activeModeElapsedSeconds = nextElapsed;
    const elapsed = formatClockElapsed(state.activeModeElapsedSeconds);
    el.edgingTimer.style.display = 'block';
    el.edgingTimer.textContent = `${label} ${elapsed}${paused ? ' paused' : ''}`;
    el.edgingTimer.title = paused ? `${label} paused at ${elapsed}` : `${label} active for ${elapsed}`;
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
        el.statusText.textContent = 'Status: No active move to like.';
    }
}

async function dislikeLastMove() {
    const data = await apiCall('/dislike_last_move', {method: 'POST'});
    if (data && data.status === 'success') {
        if (data.motion_patterns) renderMotionPatterns(data.motion_patterns);
        el.statusText.textContent = data.message || 'Saved thumbs down feedback.';
    } else {
        el.statusText.textContent = data?.message || 'No fixed motion pattern is active to rate.';
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
    }
}

async function saveLlmEdgePermissions() {
    const data = await apiCall('/set_llm_edge_permissions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            allow_llm_edge_in_freestyle: Boolean(el.allowLlmEdgeFreestyleCheckbox?.checked),
            allow_llm_edge_in_chat: Boolean(el.allowLlmEdgeChatCheckbox?.checked),
        }),
    });
    if (data && data.status === 'success') {
        populateMotionSettings(data);
        if (el.llmEdgePermissionsStatus) el.llmEdgePermissionsStatus.textContent = 'LLM edge permissions saved.';
        el.statusText.textContent = 'LLM edge permissions saved.';
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
    }
}

export function initMotionControls({sendUserMessage}) {
    configureMotionPatternList({renderMotionPatterns, setMotionTrainingDetail});
    configureMotionFeedbackControls({renderMotionPatterns});
    D.getElementById('like-this-move-btn').addEventListener('click', likeLastMove);
    D.getElementById('dislike-this-move-btn')?.addEventListener('click', dislikeLastMove);
    el.edgingModeBtn.addEventListener('click', startEdgingMode);
    el.freestyleModeBtn?.addEventListener('click', startFreestyleMode);
    el.toggleMemoryBtn?.addEventListener('click', toggleLongTermMemory);
    el.motionSpeedMinSlider.addEventListener('input', normalizeMotionSpeedLimits);
    el.motionSpeedMaxSlider.addEventListener('input', normalizeMotionSpeedLimits);
    el.saveMotionBackendBtn.addEventListener('click', saveMotionBackend);
    el.motionBackendSelect.addEventListener('change', () => updateMotionBackendUi(el.motionBackendSelect.value));
    D.getElementById('save-motion-speed-limits').addEventListener('click', saveMotionSpeedLimits);
    D.getElementById('save-timings-btn').addEventListener('click', saveModeTimings);
    el.saveLlmEdgePermissionsBtn?.addEventListener('click', saveLlmEdgePermissions);
    el.refreshMotionPatternsBtn.addEventListener('click', refreshMotionPatterns);
    if (el.motionFeedbackAutoDisableCheckbox) {
        el.motionFeedbackAutoDisableCheckbox.addEventListener('change', saveMotionFeedbackOptions);
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
    bindMotionPauseControls({
        sendUserMessage,
        updateActiveModeTimer,
        closeMotionTrainingWorkspace,
    });
    window.addEventListener('resize', drawOpenMotionTrainingPreview);
    el.motionTransformSmoothBtn?.addEventListener('click', smoothEditedPattern);
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
    el.saveMotionTrainingPatternBtn?.addEventListener('click', saveEditedMotionPattern);
    el.stopMotionTrainingBtn.addEventListener('click', stopMotionTraining);
    el.motionTrainingFeedbackUp.addEventListener('click', () => sendMotionTrainingFeedback('thumbs_up'));
    el.motionTrainingFeedbackNeutral.addEventListener('click', () => sendMotionTrainingFeedback('neutral'));
    el.motionTrainingFeedbackDown.addEventListener('click', () => sendMotionTrainingFeedback('thumbs_down'));
    el.settingsTabs.forEach(tab => {
        if (tab.dataset.settingsTab === 'motion') tab.addEventListener('click', refreshMotionPatterns);
    });
    D.getElementById('start-auto-btn').addEventListener('click', () => sendUserMessage('take over'));
    D.getElementById('milking-mode-btn').addEventListener('click', startMilkingMode);
    updateMotionTrainingStatus();
    updateMotionTrainingEditButtons();
    startHandyCylinderAnimation();
    refreshMotionPatterns();
}
