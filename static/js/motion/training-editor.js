import { D, clampNumber, el, state } from '../context.js';
import {
    clonePattern,
    formatPatternDuration,
    formatPatternMetadata,
    normalizedActions,
    patternDisplayName,
    updatePatternStats,
} from './pattern-list.js';

export function patternTempoScale(pattern) {
    return clampNumber(pattern?.style?.tempo_scale, 0.25, 4, 1);
}

export function updateMotionTrainingTimingReadouts(pattern) {
    if (el.motionTrainingDurationValue) el.motionTrainingDurationValue.textContent = formatPatternDuration(pattern?.duration_ms);
    if (el.motionTrainingTempoValue) el.motionTrainingTempoValue.textContent = `${patternTempoScale(pattern).toFixed(2)}x`;
}

export function syncRangeInputsFromPattern(pattern) {
    const actions = normalizedActions(pattern?.actions);
    if (!actions.length || !el.motionTrainingRangeMinInput || !el.motionTrainingRangeMaxInput) return;
    const positions = actions.map(action => action.pos);
    el.motionTrainingRangeMinInput.value = Math.round(Math.min(...positions));
    el.motionTrainingRangeMaxInput.value = Math.round(Math.max(...positions));
}

export function stepMotionTrainingRangeInput(button) {
    const input = D.getElementById(button?.dataset?.rangeStepTarget || '');
    if (!input) return;
    const step = clampNumber(button.dataset.rangeStep, -10, 10, 1);
    const current = clampNumber(input.value, 0, 100, 0);
    input.value = Math.round(clampNumber(current + step, 0, 100, current));
    input.focus();
}

export function setMotionEditStatus(message, color = 'var(--comment)') {
    if (!el.motionTrainingEditStatus) return;
    el.motionTrainingEditStatus.textContent = message;
    el.motionTrainingEditStatus.style.color = color;
}

export function updateMotionTrainingEditButtons() {
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

export function editablePatternPayload() {
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

export function refreshMotionTrainingDetail(message = '') {
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

export function smoothEditedPattern() {
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

export function harshenEditedPattern() {
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

export function setEditedPatternTempo(multiplier, message) {
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

export function setEditedPatternDuration(scale, message) {
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

export function remapEditedPatternRange() {
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

export function resetEditedPattern() {
    if (!state.motionTrainingOriginalPattern) return;
    state.motionTrainingEditedPattern = updatePatternStats(clonePattern(state.motionTrainingOriginalPattern));
    state.motionTrainingDirty = false;
    syncRangeInputsFromPattern(state.motionTrainingEditedPattern);
    refreshMotionTrainingDetail('Reset to the selected pattern.');
}

export function drawPatternPreviewCanvas(canvas, pattern, emptyText, lineColor = '#7fb7a3', pointColor = '#d8b66a') {
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
        previewCtx.fillText(emptyText, width / 2, height / 2);
        previewCtx.textAlign = 'left';
        return;
    }

    const start = actions[0].at;
    const end = actions[actions.length - 1].at;
    const duration = Math.max(1, end - start);
    const xFor = action => pad + ((action.at - start) / duration) * (width - pad * 2);
    const yFor = action => pad + ((100 - clampNumber(action.pos, 0, 100, 50)) / 100) * (height - pad * 2);

    previewCtx.strokeStyle = lineColor;
    previewCtx.lineWidth = 2.5;
    previewCtx.beginPath();
    actions.forEach((action, index) => {
        const x = xFor(action);
        const y = yFor(action);
        if (index === 0) previewCtx.moveTo(x, y);
        else previewCtx.lineTo(x, y);
    });
    previewCtx.stroke();

    previewCtx.fillStyle = pointColor;
    actions.forEach(action => {
        previewCtx.beginPath();
        previewCtx.arc(xFor(action), yFor(action), 3, 0, Math.PI * 2);
        previewCtx.fill();
    });

    previewCtx.fillStyle = 'rgba(232, 230, 223, 0.7)';
    previewCtx.fillText('tip', width - pad + 6, pad + 4);
    previewCtx.fillText('base', width - pad + 6, height - pad + 4);
}

export function drawMotionTrainingPreview(pattern = state.motionTrainingPreviewPattern) {
    drawPatternPreviewCanvas(
        el.motionTrainingOriginalPreviewCanvas,
        state.motionTrainingOriginalPattern,
        'Select a pattern to preview.',
        '#7d89a6',
        '#a9b0c6',
    );
    drawPatternPreviewCanvas(
        el.motionTrainingPreviewCanvas,
        pattern,
        state.motionTrainingOriginalPattern ? 'Edited preview appears here.' : 'Select a pattern to preview.',
    );
}

export function setMotionTrainingDetail(pattern) {
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

export function setMotionTrainingLoadingDetail(pattern) {
    if (!pattern || !el.motionTrainingPatternTitle || !el.motionTrainingPatternMeta) return;
    el.motionTrainingPatternTitle.textContent = patternDisplayName(pattern);
    el.motionTrainingPatternMeta.textContent = `${formatPatternMetadata(pattern)} | loading preview...`;
}

export function drawOpenMotionTrainingPreview() {
    if (el.motionTrainingDialog?.classList.contains('open')) drawMotionTrainingPreview();
}
