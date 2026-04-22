import { D, apiCall, clampNumber, ctx, el, setSliderValue, state } from './context.js';

function normalizeMotionSpeedLimits() {
    const a = parseInt(el.motionSpeedMinSlider.value, 10);
    const b = parseInt(el.motionSpeedMaxSlider.value, 10);
    state.motionMinSpeed = Math.min(a, b);
    state.motionMaxSpeed = Math.max(a, b);
    el.motionSpeedMinVal.textContent = `${state.motionMinSpeed}%`;
    el.motionSpeedMaxVal.textContent = `${state.motionMaxSpeed}%`;
}

export function populateMotionSettings(data = {}) {
    const timings = data.timings || {};
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

function formatPatternDuration(durationMs) {
    const duration = Math.max(0, Number(durationMs) || 0);
    if (duration >= 1000) return `${(duration / 1000).toFixed(duration >= 10_000 ? 0 : 1)}s`;
    return `${Math.round(duration)}ms`;
}

function setPatternStatus(message, color = 'var(--comment)') {
    if (!el.motionPatternStatus) return;
    el.motionPatternStatus.textContent = message;
    el.motionPatternStatus.style.color = color;
}

function patternDisplayName(pattern) {
    return pattern.name || pattern.id || 'Unnamed pattern';
}

function formatPatternMetadata(pattern) {
    const feedback = pattern.feedback || {};
    return [
        pattern.source || 'unknown',
        `${formatPatternDuration(pattern.duration_ms)} duration`,
        `${pattern.action_count || 0} actions`,
        pattern.readonly ? 'read-only' : 'editable file',
        `feedback ${feedback.thumbs_up || 0}/${feedback.neutral || 0}/${feedback.thumbs_down || 0}`,
    ].join(' | ');
}

function createPatternText(pattern, {includeDescription = true} = {}) {
    const text = D.createElement('div');
    text.className = 'motion-pattern-text';

    const name = D.createElement('div');
    name.className = 'motion-pattern-name';
    name.textContent = patternDisplayName(pattern);

    const meta = D.createElement('div');
    meta.className = 'motion-pattern-meta';
    meta.textContent = formatPatternMetadata(pattern);

    text.append(name, meta);
    if (includeDescription && pattern.description) {
        const description = D.createElement('div');
        description.className = 'motion-pattern-description';
        description.textContent = pattern.description;
        text.appendChild(description);
    }
    return text;
}

function createPatternExportButton(pattern) {
    const exportButton = D.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'my-button motion-pattern-export';
    exportButton.textContent = 'Export';
    exportButton.addEventListener('click', event => {
        event.stopPropagation();
        window.location.href = `/motion_patterns/${encodeURIComponent(pattern.id)}/export`;
    });
    return exportButton;
}

function patternById(patternId) {
    return state.motionPatterns.find(pattern => pattern.id === patternId);
}

function clonePattern(pattern) {
    return pattern ? JSON.parse(JSON.stringify(pattern)) : null;
}

function normalizedActions(actions) {
    return (Array.isArray(actions) ? actions : [])
        .map(action => ({
            at: Math.max(0, Math.round(Number(action.at) || 0)),
            pos: clampNumber(action.pos, 0, 100, 50),
        }))
        .filter(action => Number.isFinite(action.at) && Number.isFinite(action.pos))
        .sort((a, b) => a.at - b.at)
        .filter((action, index, all) => index === all.length - 1 || action.at !== all[index + 1].at);
}

function updatePatternStats(pattern) {
    if (!pattern) return null;
    const actions = normalizedActions(pattern?.actions);
    const duration = actions.length > 1 ? actions[actions.length - 1].at - actions[0].at : 0;
    return {
        ...pattern,
        actions,
        action_count: actions.length,
        duration_ms: Math.max(0, duration),
    };
}

function patternTempoScale(pattern) {
    return clampNumber(pattern?.style?.tempo_scale, 0.25, 4, 1);
}

function updateMotionTrainingTimingReadouts(pattern) {
    if (el.motionTrainingDurationValue) el.motionTrainingDurationValue.textContent = formatPatternDuration(pattern?.duration_ms);
    if (el.motionTrainingTempoValue) el.motionTrainingTempoValue.textContent = `${patternTempoScale(pattern).toFixed(2)}x`;
}

function syncRangeInputsFromPattern(pattern) {
    const actions = normalizedActions(pattern?.actions);
    if (!actions.length || !el.motionTrainingRangeMinInput || !el.motionTrainingRangeMaxInput) return;
    const positions = actions.map(action => action.pos);
    el.motionTrainingRangeMinInput.value = Math.round(Math.min(...positions));
    el.motionTrainingRangeMaxInput.value = Math.round(Math.max(...positions));
}

function stepMotionTrainingRangeInput(button) {
    const input = D.getElementById(button?.dataset?.rangeStepTarget || '');
    if (!input) return;
    const step = clampNumber(button.dataset.rangeStep, -10, 10, 1);
    const current = clampNumber(input.value, 0, 100, 0);
    input.value = Math.round(clampNumber(current + step, 0, 100, current));
    input.focus();
}

function setMotionEditStatus(message, color = 'var(--comment)') {
    if (!el.motionTrainingEditStatus) return;
    el.motionTrainingEditStatus.textContent = message;
    el.motionTrainingEditStatus.style.color = color;
}

function updateMotionTrainingEditButtons() {
    const hasEditable = Boolean(state.motionTrainingEditedPattern);
    const dirty = Boolean(state.motionTrainingDirty);
    [
        el.motionTransformSmoothBtn,
        el.motionTransformHarshenBtn,
        el.motionTransformDurationDownBtn,
        el.motionTransformDurationUpBtn,
        el.motionTransformTempoDownBtn,
        el.motionTransformTempoUpBtn,
        el.motionTransformRangeBtn,
        el.playMotionTrainingPreviewBtn,
    ].forEach(button => {
        if (button) button.disabled = !hasEditable;
    });
    if (el.motionTransformResetBtn) el.motionTransformResetBtn.disabled = !hasEditable || !dirty;
    if (el.saveMotionTrainingPatternBtn) el.saveMotionTrainingPatternBtn.disabled = !hasEditable || !dirty;
    if (el.motionTrainingSaveNameInput) el.motionTrainingSaveNameInput.disabled = !hasEditable;
}

function editablePatternPayload() {
    const pattern = updatePatternStats(state.motionTrainingEditedPattern);
    const originalName = patternDisplayName(state.motionTrainingOriginalPattern || pattern);
    const name = (el.motionTrainingSaveNameInput?.value || '').trim() || `${originalName} (edited)`;
    return {
        schema_version: 1,
        kind: 'actions',
        id: name,
        name,
        description: `Edited from ${originalName}.`,
        source: 'trained',
        enabled: true,
        style: pattern.style || {},
        actions: normalizedActions(pattern.actions),
        tags: ['training', 'edited'],
    };
}

function refreshMotionTrainingDetail(message = '') {
    const pattern = updatePatternStats(state.motionTrainingEditedPattern);
    state.motionTrainingEditedPattern = pattern;
    state.motionTrainingPreviewPattern = pattern;

    if (!pattern) {
        if (el.motionTrainingPatternTitle) el.motionTrainingPatternTitle.textContent = 'No pattern selected';
        if (el.motionTrainingPatternMeta) el.motionTrainingPatternMeta.textContent = 'Select a pattern to preview its shape.';
        setMotionEditStatus('Select a pattern to edit a temporary copy.');
        updateMotionTrainingTimingReadouts(null);
        drawMotionTrainingPreview(null);
        updateMotionTrainingEditButtons();
        return;
    }

    if (el.motionTrainingPatternTitle) {
        el.motionTrainingPatternTitle.textContent = state.motionTrainingDirty
            ? `${patternDisplayName(pattern)} (edited preview)`
            : patternDisplayName(pattern);
    }
    if (el.motionTrainingPatternMeta) {
        const suffix = state.motionTrainingDirty ? 'unsaved edited copy' : 'editable temporary copy';
        el.motionTrainingPatternMeta.textContent = `${formatPatternMetadata(pattern)} | tempo ${patternTempoScale(pattern).toFixed(2)}x | ${suffix}`;
    }
    if (message) setMotionEditStatus(message, state.motionTrainingDirty ? 'var(--cyan)' : 'var(--comment)');
    updateMotionTrainingTimingReadouts(pattern);
    drawMotionTrainingPreview(pattern);
    updateMotionTrainingEditButtons();
}

function setEditedPatternActions(actions, message) {
    if (!state.motionTrainingEditedPattern) return;
    state.motionTrainingEditedPattern = updatePatternStats({
        ...state.motionTrainingEditedPattern,
        actions: normalizedActions(actions),
    });
    state.motionTrainingDirty = true;
    refreshMotionTrainingDetail(message);
}

function interpolatePosition(a, b, amount) {
    const eased = (1 - Math.cos(Math.PI * amount)) / 2;
    return a + ((b - a) * eased);
}

function smoothEditedPattern() {
    const actions = normalizedActions(state.motionTrainingEditedPattern?.actions);
    if (actions.length < 2) return;
    const dense = [];
    actions.forEach((action, index) => {
        if (index === 0) dense.push(action);
        const previous = actions[index - 1];
        if (!previous) return;
        const gap = action.at - previous.at;
        const inserts = Math.min(8, Math.max(0, Math.floor(gap / 140)));
        for (let step = 1; step <= inserts; step++) {
            const amount = step / (inserts + 1);
            dense.push({
                at: Math.round(previous.at + gap * amount),
                pos: interpolatePosition(previous.pos, action.pos, amount),
            });
        }
        dense.push(action);
    });
    const smoothed = dense.map((action, index) => {
        if (index === 0 || index === dense.length - 1) return action;
        const before = dense[index - 1].pos;
        const after = dense[index + 1].pos;
        return {...action, pos: (before * 0.25) + (action.pos * 0.5) + (after * 0.25)};
    });
    setEditedPatternActions(smoothed, 'Smoothed the temporary copy.');
}

function harshenEditedPattern() {
    const actions = normalizedActions(state.motionTrainingEditedPattern?.actions);
    if (actions.length < 2) return;
    const positions = actions.map(action => action.pos);
    const center = (Math.min(...positions) + Math.max(...positions)) / 2;
    const sharpened = actions.map(action => ({
        ...action,
        pos: clampNumber(center + ((action.pos - center) * 1.22), 0, 100, action.pos),
    }));
    setEditedPatternActions(sharpened, 'Harshened the temporary copy.');
}

function setEditedPatternTempo(multiplier, message) {
    if (!state.motionTrainingEditedPattern) return;
    const tempoScale = clampNumber(patternTempoScale(state.motionTrainingEditedPattern) * multiplier, 0.25, 4, 1);
    state.motionTrainingEditedPattern = updatePatternStats({
        ...state.motionTrainingEditedPattern,
        style: {
            ...(state.motionTrainingEditedPattern.style || {}),
            tempo_scale: tempoScale,
        },
    });
    state.motionTrainingDirty = true;
    refreshMotionTrainingDetail(`${message} Tempo ${tempoScale.toFixed(2)}x.`);
}

function setEditedPatternDuration(scale, message) {
    const actions = normalizedActions(state.motionTrainingEditedPattern?.actions);
    if (actions.length < 2) return;
    const start = actions[0].at;
    const currentDuration = Math.max(1, actions[actions.length - 1].at - start);
    const targetDuration = clampNumber(currentDuration * scale, 120, 300000, currentDuration);
    const effectiveScale = targetDuration / currentDuration;
    const scaled = actions.map((action, index) => ({
        ...action,
        at: index === 0 ? 0 : Math.max(index, Math.round((action.at - start) * effectiveScale)),
    }));
    const tempoScale = clampNumber(patternTempoScale(state.motionTrainingEditedPattern) / effectiveScale, 0.25, 4, 1);
    state.motionTrainingEditedPattern = updatePatternStats({
        ...state.motionTrainingEditedPattern,
        actions: normalizedActions(scaled),
        style: {
            ...(state.motionTrainingEditedPattern.style || {}),
            tempo_scale: tempoScale,
        },
    });
    state.motionTrainingDirty = true;
    const duration = formatPatternDuration(state.motionTrainingEditedPattern.duration_ms);
    refreshMotionTrainingDetail(`${message} Duration ${duration}; tempo ${tempoScale.toFixed(2)}x.`);
}

function remapEditedPatternRange() {
    const actions = normalizedActions(state.motionTrainingEditedPattern?.actions);
    if (actions.length < 2) return;
    const inputMin = clampNumber(el.motionTrainingRangeMinInput?.value, 0, 100, 0);
    const inputMax = clampNumber(el.motionTrainingRangeMaxInput?.value, 0, 100, 100);
    const targetMin = Math.min(inputMin, inputMax);
    const targetMax = Math.max(inputMin, inputMax);
    const positions = actions.map(action => action.pos);
    const sourceMin = Math.min(...positions);
    const sourceMax = Math.max(...positions);
    const sourceSpan = Math.max(1, sourceMax - sourceMin);
    const targetSpan = Math.max(1, targetMax - targetMin);
    const remapped = actions.map(action => ({
        ...action,
        pos: targetMin + (((action.pos - sourceMin) / sourceSpan) * targetSpan),
    }));
    setEditedPatternActions(remapped, `Remapped the temporary copy to ${Math.round(targetMin)}-${Math.round(targetMax)}%.`);
}

function resetEditedPattern() {
    if (!state.motionTrainingOriginalPattern) return;
    state.motionTrainingEditedPattern = updatePatternStats(clonePattern(state.motionTrainingOriginalPattern));
    state.motionTrainingDirty = false;
    syncRangeInputsFromPattern(state.motionTrainingEditedPattern);
    refreshMotionTrainingDetail('Reset to the selected pattern.');
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

function drawMotionTrainingPreview(pattern = state.motionTrainingPreviewPattern) {
    const canvas = el.motionTrainingPreviewCanvas;
    if (!canvas) return;
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(320, Math.round(bounds.width || canvas.width || 640));
    const height = Math.max(180, Math.round(bounds.height || canvas.height || 260));
    if (canvas.width !== width || canvas.height !== height) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;

    const previewCtx = canvas.getContext('2d');
    const pad = 34;
    previewCtx.clearRect(0, 0, width, height);
    previewCtx.fillStyle = '#101217';
    previewCtx.fillRect(0, 0, width, height);

    previewCtx.strokeStyle = 'rgba(232, 230, 223, 0.12)';
    previewCtx.lineWidth = 1;
    previewCtx.font = '11px Inter, sans-serif';
    previewCtx.fillStyle = 'rgba(232, 230, 223, 0.62)';
    [0, 25, 50, 75, 100].forEach(position => {
        const y = pad + ((100 - position) / 100) * (height - pad * 2);
        previewCtx.beginPath();
        previewCtx.moveTo(pad, y);
        previewCtx.lineTo(width - pad, y);
        previewCtx.stroke();
        previewCtx.fillText(`${position}`, 7, y + 4);
    });
    for (let i = 0; i <= 4; i++) {
        const x = pad + (i / 4) * (width - pad * 2);
        previewCtx.beginPath();
        previewCtx.moveTo(x, pad);
        previewCtx.lineTo(x, height - pad);
        previewCtx.stroke();
    }

    const actions = Array.isArray(pattern?.actions)
        ? pattern.actions
            .map(action => ({at: Number(action.at), pos: Number(action.pos)}))
            .filter(action => Number.isFinite(action.at) && Number.isFinite(action.pos))
            .sort((a, b) => a.at - b.at)
        : [];

    if (!actions.length) {
        previewCtx.fillStyle = 'rgba(232, 230, 223, 0.72)';
        previewCtx.textAlign = 'center';
        previewCtx.fillText('Select a pattern to preview its position curve.', width / 2, height / 2);
        previewCtx.textAlign = 'left';
        return;
    }

    const start = actions[0].at;
    const end = actions[actions.length - 1].at;
    const duration = Math.max(1, end - start);
    const xFor = action => pad + ((action.at - start) / duration) * (width - pad * 2);
    const yFor = action => pad + ((100 - clampNumber(action.pos, 0, 100, 50)) / 100) * (height - pad * 2);

    previewCtx.strokeStyle = '#7fb7a3';
    previewCtx.lineWidth = 2.5;
    previewCtx.beginPath();
    actions.forEach((action, index) => {
        const x = xFor(action);
        const y = yFor(action);
        if (index === 0) previewCtx.moveTo(x, y);
        else previewCtx.lineTo(x, y);
    });
    previewCtx.stroke();

    previewCtx.fillStyle = '#d8b66a';
    actions.forEach(action => {
        previewCtx.beginPath();
        previewCtx.arc(xFor(action), yFor(action), 3, 0, Math.PI * 2);
        previewCtx.fill();
    });

    previewCtx.fillStyle = 'rgba(232, 230, 223, 0.7)';
    previewCtx.fillText('tip', width - pad + 6, pad + 4);
    previewCtx.fillText('base', width - pad + 6, height - pad + 4);
}

function setMotionTrainingDetail(pattern) {
    state.motionTrainingOriginalPattern = updatePatternStats(clonePattern(pattern));
    state.motionTrainingEditedPattern = updatePatternStats(clonePattern(pattern));
    state.motionTrainingPreviewPattern = state.motionTrainingEditedPattern || null;
    state.motionTrainingDirty = false;
    if (!el.motionTrainingPatternTitle || !el.motionTrainingPatternMeta) {
        drawMotionTrainingPreview(state.motionTrainingPreviewPattern);
        updateMotionTrainingEditButtons();
        return;
    }
    if (!pattern) {
        el.motionTrainingPatternTitle.textContent = 'No pattern selected';
        el.motionTrainingPatternMeta.textContent = 'Select a pattern to preview its shape.';
        if (el.motionTrainingSaveNameInput) el.motionTrainingSaveNameInput.value = '';
        setMotionEditStatus('Select a pattern to edit a temporary copy.');
        updateMotionTrainingTimingReadouts(null);
        drawMotionTrainingPreview(null);
        updateMotionTrainingEditButtons();
        return;
    }
    if (el.motionTrainingSaveNameInput) el.motionTrainingSaveNameInput.value = `${patternDisplayName(pattern)} (edited)`;
    syncRangeInputsFromPattern(state.motionTrainingEditedPattern);
    refreshMotionTrainingDetail('Editing a temporary copy.');
}

function setMotionTrainingLoadingDetail(pattern) {
    if (!pattern || !el.motionTrainingPatternTitle || !el.motionTrainingPatternMeta) return;
    el.motionTrainingPatternTitle.textContent = patternDisplayName(pattern);
    el.motionTrainingPatternMeta.textContent = `${formatPatternMetadata(pattern)} | loading preview...`;
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

function renderCompactMotionPatternList(patterns) {
    if (!el.motionPatternList) return;
    el.motionPatternList.replaceChildren();

    if (!patterns.length) {
        return;
    }

    patterns.forEach(pattern => {
        const row = D.createElement('div');
        row.className = 'motion-pattern-row';

        const main = D.createElement('label');
        main.className = 'motion-pattern-main';

        const checkbox = D.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = Boolean(pattern.enabled);
        checkbox.dataset.patternId = pattern.id;
        checkbox.addEventListener('change', async () => {
            checkbox.disabled = true;
            await setMotionPatternEnabled(pattern.id, checkbox.checked);
            checkbox.disabled = false;
        });

        const text = createPatternText(pattern);

        const actions = D.createElement('div');
        actions.className = 'motion-pattern-row-actions';

        actions.append(createPatternExportButton(pattern));
        main.append(checkbox, text);
        row.append(main, actions);
        el.motionPatternList.appendChild(row);
    });
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

        actions.append(playButton, createPatternExportButton(pattern));
        row.append(main, actions);
        el.motionTrainingPatternList.appendChild(row);
    });
}

export function renderMotionPatterns(catalog = {}) {
    const patterns = Array.isArray(catalog.patterns) ? catalog.patterns : [];
    state.motionPatterns = patterns;
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

async function setMotionPatternEnabled(patternId, enabled) {
    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}/enabled`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled}),
    });
    if (data && data.status === 'success') {
        renderMotionPatterns(data.motion_patterns);
        el.statusText.textContent = `${data.pattern.name} pattern ${data.pattern.enabled ? 'enabled' : 'disabled'}.`;
    }
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

function drawOpenMotionTrainingPreview() {
    if (el.motionTrainingDialog?.classList.contains('open')) drawMotionTrainingPreview();
}

export function resizeCanvas() {
    const bounds = el.rhythmCanvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    el.rhythmCanvas.width = Math.round(bounds.width);
    el.rhythmCanvas.height = Math.round(bounds.height);
}

export function drawHandyVisualizer(speed, depth) {
    const width = el.rhythmCanvas.width;
    const height = el.rhythmCanvas.height;
    if (width === 0 || height === 0) return;
    const barHeight = (height / 2) - 4;
    ctx.clearRect(0, 0, width, height);
    ctx.font = '12px sans-serif';
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
    ctx.fillText(`Depth: ${depth}%`, 5, height - (barHeight / 2) + 5);
}

export function startEdgingTimer() {
    if (state.edgingTimerInterval) clearInterval(state.edgingTimerInterval);
    el.edgingTimer.style.display = 'block';
    let seconds = 0;
    state.edgingTimerInterval = setInterval(() => {
        seconds++;
        const min = Math.floor(seconds / 60).toString().padStart(2, '0');
        const sec = (seconds % 60).toString().padStart(2, '0');
        el.edgingTimer.textContent = `${min}:${sec}`;
    }, 1000);
}

export function stopEdgingTimer() {
    clearInterval(state.edgingTimerInterval);
    state.edgingTimerInterval = null;
    el.edgingTimer.style.display = 'none';
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
    drawHandyVisualizer(data.speed || 0, data.depth || 0);
    if (data.motion_training) updateMotionTrainingStatus(data.motion_training);
}

async function likeLastMove() {
    const data = await apiCall('/like_last_move', {method: 'POST'});
    if (data && data.status === 'boosted') {
        el.statusText.textContent = `Saved '${data.name}' to my memory!`;
    } else {
        el.statusText.textContent = 'Status: No active move to like.';
    }
}

export function initMotionControls({sendUserMessage}) {
    D.getElementById('like-this-move-btn').addEventListener('click', likeLastMove);
    const stopButtons = [D.getElementById('stop-auto-btn'), D.getElementById('emergency-stop-all-btn')];
    stopButtons.forEach(btn => btn.addEventListener('click', () => {
        el.imCloseBtn.style.display = 'none';
        stopEdgingTimer();
        if (btn.id === 'emergency-stop-all-btn') sendUserMessage('stop');
        else apiCall('/stop_auto_mode', {method: 'POST'});
    }));
    el.edgingModeBtn.addEventListener('click', () => {
        apiCall('/start_edging_mode', {method: 'POST'});
        el.imCloseBtn.style.display = 'block';
        startEdgingTimer();
    });
    el.imCloseBtn.addEventListener('click', () => {
        apiCall('/signal_edge', {method: 'POST'});
        el.imCloseBtn.style.transform = 'scale(0.95)';
        setTimeout(() => { el.imCloseBtn.style.transform = ''; }, 100);
    });
    el.motionSpeedMinSlider.addEventListener('input', normalizeMotionSpeedLimits);
    el.motionSpeedMaxSlider.addEventListener('input', normalizeMotionSpeedLimits);
    D.getElementById('save-motion-speed-limits').addEventListener('click', saveMotionSpeedLimits);
    D.getElementById('save-timings-btn').addEventListener('click', saveModeTimings);
    el.refreshMotionPatternsBtn.addEventListener('click', refreshMotionPatterns);
    el.importMotionPatternBtn.addEventListener('click', () => el.motionPatternImportInput.click());
    el.motionPatternImportInput.addEventListener('change', event => importMotionPatternFile(event.target.files[0]));
    if (el.openMotionTrainingBtn) el.openMotionTrainingBtn.addEventListener('click', openMotionTrainingWorkspace);
    if (el.closeMotionTrainingBtn) el.closeMotionTrainingBtn.addEventListener('click', closeMotionTrainingWorkspace);
    if (el.motionTrainingDialog) {
        el.motionTrainingDialog.addEventListener('click', event => {
            if (event.target === el.motionTrainingDialog) closeMotionTrainingWorkspace();
        });
    }
    D.addEventListener('keydown', event => {
        if (event.key === 'Escape' && el.motionTrainingDialog?.classList.contains('open')) closeMotionTrainingWorkspace();
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
    D.getElementById('milking-mode-btn').addEventListener('click', () => apiCall('/start_milking_mode', {method: 'POST'}));
    updateMotionTrainingStatus();
    updateMotionTrainingEditButtons();
    refreshMotionPatterns();
}
