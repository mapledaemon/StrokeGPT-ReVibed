import { D, clampNumber, el, state } from '../context.js';
import {
    clonePattern,
    formatPatternDuration,
    formatPatternMetadata,
    normalizedActions,
    patternDisplayName,
    updatePatternStats,
} from './pattern-list.js';

export const STUDIO_MAX_ACTIONS = 2000;
export const STUDIO_MAX_DURATION_MS = 300000;
export const STUDIO_TIMELINE_MAX_ZOOM = 16;
const DEFAULT_DRAW_DURATION_MS = 8000;
const MIN_CROP_DURATION_MS = 100;

export function patternTempoScale(pattern) {
    return clampNumber(pattern?.style?.tempo_scale, 0.25, 4, 1);
}

function filenameStem(filename = 'pattern') {
    return String(filename || 'pattern')
        .replace(/^.*[\\/]/, '')
        .replace(/\.(strokegpt-pattern\.json|funscript|json)$/i, '')
        .trim() || 'pattern';
}

function titleFromPayload(payload, filename = 'pattern') {
    const metadata = payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
    return String(
        payload?.name
        || payload?.title
        || metadata.title
        || metadata.name
        || filenameStem(filename),
    ).trim() || filenameStem(filename);
}

function sourceDurationMs(pattern) {
    const actions = normalizedActions(pattern?.actions);
    return actions.length > 1 ? actions[actions.length - 1].at - actions[0].at : 0;
}

function msToSeconds(ms) {
    return Math.round((Number(ms) || 0) / 100) / 10;
}

function secondsToMs(seconds, maxMs = STUDIO_MAX_DURATION_MS) {
    const maxSeconds = Math.max(0, maxMs / 1000);
    return Math.round(clampNumber(seconds, 0, maxSeconds, 0) * 1000);
}

function mixChannel(start, end, amount) {
    return Math.round(start + ((end - start) * amount));
}

export function segmentIntensity(left, right) {
    const leftPos = clampNumber(left?.pos, 0, 100, 50);
    const rightPos = clampNumber(right?.pos, 0, 100, 50);
    const leftAt = Number(left?.at) || 0;
    const rightAt = Number(right?.at) || leftAt;
    const seconds = Math.max(0.05, Math.abs(rightAt - leftAt) / 1000);
    const speed = Math.abs(rightPos - leftPos) / seconds;
    return clampNumber(speed / 180, 0, 1, 0);
}

export function timelineIntensityColor(intensity, alpha = 0.96) {
    const amount = clampNumber(intensity, 0, 1, 0);
    const opacity = clampNumber(alpha, 0, 1, 0.96);
    const low = [127, 183, 163];
    const mid = [216, 182, 106];
    const high = [255, 85, 85];
    const start = amount < 0.5 ? low : mid;
    const end = amount < 0.5 ? mid : high;
    const scaled = amount < 0.5 ? amount * 2 : (amount - 0.5) * 2;
    return `rgba(${mixChannel(start[0], end[0], scaled)}, ${mixChannel(start[1], end[1], scaled)}, ${mixChannel(start[2], end[2], scaled)}, ${opacity})`;
}

function actionAt(actions, at) {
    if (!actions.length) return {at, pos: 50};
    if (at <= actions[0].at) return {at, pos: actions[0].pos};
    const last = actions[actions.length - 1];
    if (at >= last.at) return {at, pos: last.pos};
    for (let i = 1; i < actions.length; i++) {
        const right = actions[i];
        if (right.at < at) continue;
        const left = actions[i - 1];
        const span = Math.max(1, right.at - left.at);
        const amount = (at - left.at) / span;
        return {
            at,
            pos: left.pos + ((right.pos - left.pos) * amount),
        };
    }
    return {at, pos: last.pos};
}

function downsampleActions(actions, maxActions = STUDIO_MAX_ACTIONS) {
    if (actions.length <= maxActions) return actions;
    if (maxActions < 2) return actions.slice(0, 2);
    const selected = [];
    const used = new Set();
    for (let i = 0; i < maxActions; i++) {
        const sourceIndex = Math.round((i / (maxActions - 1)) * (actions.length - 1));
        if (!used.has(sourceIndex)) {
            selected.push(actions[sourceIndex]);
            used.add(sourceIndex);
        }
    }
    const last = actions[actions.length - 1];
    if (selected[selected.length - 1] !== last) selected[selected.length - 1] = last;
    return selected;
}

function studioTimelineZoom() {
    return clampNumber(state.motionStudioTimelineZoom, 1, STUDIO_TIMELINE_MAX_ZOOM, 1);
}

function studioTimelineViewWindow(pattern = state.motionStudioSourcePattern) {
    const duration = sourceDurationMs(pattern);
    if (duration <= 0) {
        state.motionStudioTimelineOffsetMs = 0;
        return {duration: 0, viewStart: 0, viewEnd: 0, viewDuration: 0, zoom: 1};
    }
    const zoom = studioTimelineZoom();
    const viewDuration = Math.max(1, duration / zoom);
    const maxOffset = Math.max(0, duration - viewDuration);
    const viewStart = clampNumber(state.motionStudioTimelineOffsetMs, 0, maxOffset, 0);
    state.motionStudioTimelineOffsetMs = viewStart;
    return {
        duration,
        viewStart,
        viewEnd: Math.min(duration, viewStart + viewDuration),
        viewDuration,
        zoom,
    };
}

function timelinePercentForMs(ms, view) {
    if (!view?.viewDuration) return 0;
    return clampNumber(((ms - view.viewStart) / view.viewDuration) * 100, 0, 100, 0);
}

function timelineMsForPercent(percent, view) {
    if (!view?.viewDuration) return 0;
    return Math.round(view.viewStart + (clampNumber(percent, 0, 1, 0) * view.viewDuration));
}

function resetStudioTimelineView() {
    state.motionStudioTimelineZoom = 1;
    state.motionStudioTimelineOffsetMs = 0;
}

export function patternFromImportPayload(payload, filename = 'pattern.json') {
    if (!payload || typeof payload !== 'object' || !Array.isArray(payload.actions)) {
        throw new Error('Pattern file must contain an actions array.');
    }
    const actions = normalizedActions(payload.actions);
    if (actions.length < 2) {
        throw new Error('Pattern file must contain at least two usable actions.');
    }
    const name = titleFromPayload(payload, filename);
    return updatePatternStats({
        schema_version: 1,
        kind: 'actions',
        id: payload.id || name,
        name,
        description: `Imported from ${String(filename || 'pattern file')}.`,
        source: 'imported',
        enabled: true,
        style: payload.style || {},
        actions: actions.map(action => ({at: action.at - actions[0].at, pos: action.pos})),
        tags: ['studio', filename.toLowerCase().endsWith('.funscript') ? 'funscript' : 'imported'],
    });
}

export function cropPatternToWindow(pattern, startMs, endMs, {maxActions = STUDIO_MAX_ACTIONS} = {}) {
    const actions = normalizedActions(pattern?.actions);
    if (actions.length < 2) throw new Error('Select or import a pattern with at least two actions.');
    const sourceStart = actions[0].at;
    const sourceEnd = actions[actions.length - 1].at;
    const lower = Math.max(sourceStart, Math.min(sourceEnd - 1, Math.round(Number(startMs) || 0)));
    const upper = Math.max(lower + 1, Math.min(sourceEnd, Math.round(Number(endMs) || sourceEnd)));
    const cropped = [
        actionAt(actions, lower),
        ...actions.filter(action => action.at > lower && action.at < upper),
        actionAt(actions, upper),
    ].map(action => ({
        at: action.at - lower,
        pos: action.pos,
    }));
    const sampled = downsampleActions(normalizedActions(cropped), maxActions);
    return updatePatternStats({
        schema_version: 1,
        kind: 'actions',
        id: `${pattern.id || pattern.name || 'pattern'} crop`,
        name: `${patternDisplayName(pattern)} crop`,
        description: `Cropped from ${patternDisplayName(pattern)}.`,
        source: 'trained',
        enabled: true,
        style: pattern.style || {},
        actions: sampled,
        tags: ['studio', 'crop'],
    });
}

export function createBlankStudioPattern(durationMs = DEFAULT_DRAW_DURATION_MS) {
    const duration = Math.round(clampNumber(durationMs, 500, STUDIO_MAX_DURATION_MS, DEFAULT_DRAW_DURATION_MS));
    return updatePatternStats({
        schema_version: 1,
        kind: 'actions',
        id: 'drawn pattern',
        name: 'Drawn Pattern',
        description: 'Created by drawing in Motion Pattern Studio.',
        source: 'trained',
        enabled: true,
        style: {},
        actions: [
            {at: 0, pos: 50},
            {at: duration, pos: 50},
        ],
        tags: ['studio', 'drawn'],
    });
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
    const drawFlowActive = state.motionStudioFlow === 'draw';
    if (el.motionStudioDrawToggleBtn) {
        el.motionStudioDrawToggleBtn.disabled = !hasEditable || !drawFlowActive;
        el.motionStudioDrawToggleBtn.textContent = state.motionStudioDrawingEnabled ? 'Draw On' : 'Draw Off';
        el.motionStudioDrawToggleBtn.classList.toggle('active', Boolean(state.motionStudioDrawingEnabled));
    }
    if (el.motionStudioClearDrawingBtn) el.motionStudioClearDrawingBtn.disabled = !hasEditable || !drawFlowActive;
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

function setStudioEditedPattern(pattern, message, {dirty = true, sourcePattern = null} = {}) {
    const cleanPattern = updatePatternStats(clonePattern(pattern));
    state.motionTrainingOriginalPattern = sourcePattern ? updatePatternStats(clonePattern(sourcePattern)) : null;
    state.motionTrainingEditedPattern = cleanPattern;
    state.motionTrainingPreviewPattern = cleanPattern;
    state.motionTrainingDirty = Boolean(dirty);
    state.motionTrainingSelectedPatternId = '';
    if (el.motionTrainingSaveNameInput && cleanPattern) el.motionTrainingSaveNameInput.value = patternDisplayName(cleanPattern);
    syncRangeInputsFromPattern(cleanPattern);
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

export function drawPatternPreviewCanvas(canvas, pattern, emptyText, lineColor = '#7fb7a3', pointColor = '#d8b66a', options = {}) {
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

    if (options.cropStartMs !== undefined && options.cropEndMs !== undefined) {
        const cropStart = clampNumber(options.cropStartMs, start, end, start);
        const cropEnd = clampNumber(options.cropEndMs, cropStart, end, end);
        const left = pad + ((cropStart - start) / duration) * (width - pad * 2);
        const right = pad + ((cropEnd - start) / duration) * (width - pad * 2);
        previewCtx.fillStyle = 'rgba(193, 18, 31, 0.22)';
        previewCtx.fillRect(pad, pad, Math.max(0, left - pad), height - pad * 2);
        previewCtx.fillRect(right, pad, Math.max(0, width - pad - right), height - pad * 2);
        previewCtx.strokeStyle = 'rgba(216, 182, 106, 0.9)';
        previewCtx.lineWidth = 2;
        previewCtx.beginPath();
        previewCtx.moveTo(left, pad);
        previewCtx.lineTo(left, height - pad);
        previewCtx.moveTo(right, pad);
        previewCtx.lineTo(right, height - pad);
        previewCtx.stroke();
    }

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
    const sourcePattern = state.motionStudioSourcePattern || state.motionTrainingOriginalPattern;
    const sourceEmptyText = state.motionStudioSourcePattern
        ? 'Imported source appears here.'
        : 'Select a pattern to preview.';
    drawPatternPreviewCanvas(
        el.motionTrainingOriginalPreviewCanvas,
        sourcePattern,
        sourceEmptyText,
        '#7d89a6',
        '#a9b0c6',
        state.motionStudioSourcePattern
            ? {
                cropStartMs: state.motionStudioCropStartMs,
                cropEndMs: state.motionStudioCropEndMs,
            }
            : {},
    );
    drawPatternPreviewCanvas(
        el.motionTrainingPreviewCanvas,
        pattern,
        state.motionTrainingOriginalPattern ? 'Edited preview appears here.' : 'Select a pattern to preview.',
    );
    drawStudioCropTimeline();
    updateStudioTimelineHandles();
}

export function setMotionTrainingDetail(pattern) {
    closeStudioFlow();
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

function setStudioStatus(message, color = 'var(--comment)') {
    if (!el.motionStudioSourceStatus) return;
    el.motionStudioSourceStatus.textContent = message;
    el.motionStudioSourceStatus.style.color = color;
}

function showStudioFlow(flow) {
    state.motionStudioFlow = flow || '';
    const active = Boolean(state.motionStudioFlow);
    if (el.motionStudioPanel) el.motionStudioPanel.hidden = !active;
    if (el.motionStudioDrawControls) el.motionStudioDrawControls.hidden = state.motionStudioFlow !== 'draw';
    if (el.motionStudioCropPanel) el.motionStudioCropPanel.hidden = state.motionStudioFlow !== 'import';
    updateMotionTrainingEditButtons();
}

function clearStudioImportSource() {
    state.motionStudioSourcePattern = null;
    state.motionStudioCropStartMs = 0;
    state.motionStudioCropEndMs = 0;
    state.motionStudioCropDragHandle = '';
    resetStudioTimelineView();
    syncCropControlsFromState();
}

function closeStudioFlow() {
    state.motionStudioFlow = '';
    state.motionStudioDrawingEnabled = false;
    state.motionStudioDrawingActive = false;
    state.motionStudioDrawBuffer = [];
    if (el.motionStudioPanel) el.motionStudioPanel.hidden = true;
    if (el.motionStudioDrawControls) el.motionStudioDrawControls.hidden = true;
    if (el.motionStudioCropPanel) el.motionStudioCropPanel.hidden = true;
    clearStudioImportSource();
    updateMotionTrainingEditButtons();
}

function setCropControlsEnabled(enabled) {
    [
        el.motionStudioCropStartInput,
        el.motionStudioCropEndInput,
        el.motionStudioPlayCropBtn,
        el.motionStudioApplyCropBtn,
        el.motionStudioCropStartHandle,
        el.motionStudioCropEndHandle,
    ].forEach(control => {
        if (control) control.disabled = !enabled;
    });
    if (el.motionStudioCropTimeline) {
        if (enabled) el.motionStudioCropTimeline.classList.remove('disabled');
        else el.motionStudioCropTimeline.classList.add('disabled');
    }
}

function setTimelineControlsEnabled(enabled) {
    [
        el.motionStudioZoomOutBtn,
        el.motionStudioZoomSlider,
        el.motionStudioZoomInBtn,
        el.motionStudioFitBtn,
        el.motionStudioPanSlider,
    ].forEach(control => {
        if (control) control.disabled = !enabled;
    });
}

function syncStudioTimelineControlsFromState() {
    const view = studioTimelineViewWindow();
    const enabled = view.duration > 0;
    setTimelineControlsEnabled(enabled);
    if (el.motionStudioZoomSlider) {
        el.motionStudioZoomSlider.min = '1';
        el.motionStudioZoomSlider.max = String(STUDIO_TIMELINE_MAX_ZOOM);
        el.motionStudioZoomSlider.step = '0.25';
        el.motionStudioZoomSlider.value = String(view.zoom);
    }
    if (el.motionStudioZoomOutBtn) el.motionStudioZoomOutBtn.disabled = !enabled || view.zoom <= 1;
    if (el.motionStudioZoomInBtn) el.motionStudioZoomInBtn.disabled = !enabled || view.zoom >= STUDIO_TIMELINE_MAX_ZOOM;
    if (el.motionStudioFitBtn) el.motionStudioFitBtn.disabled = !enabled || (view.zoom <= 1 && view.viewStart <= 0);
    if (el.motionStudioZoomValue) el.motionStudioZoomValue.textContent = `${view.zoom.toFixed(2).replace(/\.?0+$/, '')}x`;
    const maxOffset = Math.max(0, view.duration - view.viewDuration);
    if (el.motionStudioPanSlider) {
        el.motionStudioPanSlider.min = '0';
        el.motionStudioPanSlider.max = String(msToSeconds(maxOffset));
        el.motionStudioPanSlider.step = '0.1';
        el.motionStudioPanSlider.value = String(msToSeconds(view.viewStart));
        el.motionStudioPanSlider.disabled = !enabled || view.zoom <= 1;
    }
    if (el.motionStudioWindowValue) {
        el.motionStudioWindowValue.textContent = enabled
            ? `${msToSeconds(view.viewStart)}-${msToSeconds(view.viewEnd)}s`
            : '0-0s';
    }
}

function setStudioTimelineOffsetMs(offsetMs) {
    const duration = sourceDurationMs(state.motionStudioSourcePattern);
    const currentZoom = studioTimelineZoom();
    const viewDuration = duration > 0 ? Math.max(1, duration / currentZoom) : 0;
    const maxOffset = Math.max(0, duration - viewDuration);
    state.motionStudioTimelineOffsetMs = clampNumber(offsetMs, 0, maxOffset, 0);
    syncStudioTimelineControlsFromState();
    updateStudioTimelineHandles();
    drawStudioCropTimeline();
}

function setStudioTimelineZoom(zoom, anchorMs = null) {
    const source = state.motionStudioSourcePattern;
    const duration = sourceDurationMs(source);
    if (!source || duration <= 0) return;
    const before = studioTimelineViewWindow(source);
    const anchor = anchorMs === null
        ? before.viewStart + (before.viewDuration / 2)
        : clampNumber(anchorMs, before.viewStart, before.viewEnd, before.viewStart);
    const anchorRatio = before.viewDuration > 0 ? (anchor - before.viewStart) / before.viewDuration : 0.5;
    state.motionStudioTimelineZoom = clampNumber(zoom, 1, STUDIO_TIMELINE_MAX_ZOOM, 1);
    const afterViewDuration = Math.max(1, duration / studioTimelineZoom());
    state.motionStudioTimelineOffsetMs = clampNumber(
        anchor - (afterViewDuration * anchorRatio),
        0,
        Math.max(0, duration - afterViewDuration),
        0,
    );
    syncStudioTimelineControlsFromState();
    updateStudioTimelineHandles();
    drawStudioCropTimeline();
}

function updateStudioTimelineHandles() {
    const source = state.motionStudioSourcePattern;
    const view = studioTimelineViewWindow(source);
    const enabled = Boolean(source && view.duration > 0);
    const visibleStart = enabled ? Math.max(state.motionStudioCropStartMs, view.viewStart) : 0;
    const visibleEnd = enabled ? Math.min(state.motionStudioCropEndMs, view.viewEnd) : 0;
    const startPercent = enabled ? timelinePercentForMs(visibleStart, view) : 0;
    const endPercent = enabled ? timelinePercentForMs(visibleEnd, view) : 100;
    const hasVisibleSelection = enabled && visibleEnd > visibleStart;
    if (el.motionStudioCropSelection) {
        el.motionStudioCropSelection.hidden = !hasVisibleSelection;
        el.motionStudioCropSelection.style.left = `${startPercent}%`;
        el.motionStudioCropSelection.style.width = `${Math.max(0, endPercent - startPercent)}%`;
    }
    [
        [el.motionStudioCropStartHandle, state.motionStudioCropStartMs, 'start'],
        [el.motionStudioCropEndHandle, state.motionStudioCropEndMs, 'end'],
    ].forEach(([handle, ms, label]) => {
        if (!handle) return;
        const visible = enabled && ms >= view.viewStart && ms <= view.viewEnd;
        handle.hidden = !visible;
        const percent = visible ? timelinePercentForMs(ms, view) : 0;
        handle.style.left = `${percent}%`;
        handle.setAttribute('aria-valuemin', '0');
        handle.setAttribute('aria-valuemax', String(msToSeconds(view.duration)));
        handle.setAttribute('aria-valuenow', String(msToSeconds(ms)));
        handle.setAttribute('aria-valuetext', `${label} ${msToSeconds(ms)} seconds`);
    });
}

function drawStudioCropTimeline() {
    const canvas = el.motionStudioCropCanvas;
    if (!canvas) return;
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return;

    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(360, Math.round(bounds.width || canvas.width || 720));
    const height = Math.max(86, Math.round(bounds.height || canvas.height || 96));
    if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
    }

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#101217';
    ctx.fillRect(0, 0, width, height);
    ctx.strokeStyle = 'rgba(232, 230, 223, 0.12)';
    ctx.lineWidth = 1;

    const padX = 14;
    const padY = 12;
    for (let i = 0; i <= 8; i++) {
        const x = padX + (i / 8) * (width - padX * 2);
        ctx.beginPath();
        ctx.moveTo(x, padY);
        ctx.lineTo(x, height - padY);
        ctx.stroke();
    }
    [0, 25, 50, 75, 100].forEach(position => {
        const y = padY + ((100 - position) / 100) * (height - padY * 2);
        ctx.beginPath();
        ctx.moveTo(padX, y);
        ctx.lineTo(width - padX, y);
        ctx.stroke();
    });

    const actions = normalizedActions(state.motionStudioSourcePattern?.actions);
    if (actions.length < 2) {
        ctx.fillStyle = 'rgba(232, 230, 223, 0.62)';
        ctx.font = '12px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Import a funscript to trim a timeline slice.', width / 2, height / 2 + 4);
        ctx.textAlign = 'left';
        return;
    }

    const view = studioTimelineViewWindow();
    const start = view.viewStart;
    const end = view.viewEnd;
    const duration = Math.max(1, view.viewDuration);
    const visibleActions = [
        actionAt(actions, start),
        ...actions.filter(action => action.at > start && action.at < end),
        actionAt(actions, end),
    ];
    const xFor = action => padX + ((action.at - start) / duration) * (width - padX * 2);
    const yFor = action => padY + ((100 - clampNumber(action.pos, 0, 100, 50)) / 100) * (height - padY * 2);

    ctx.lineWidth = 2.5;
    for (let i = 1; i < visibleActions.length; i++) {
        const left = visibleActions[i - 1];
        const right = visibleActions[i];
        const intensity = segmentIntensity(left, right);
        ctx.strokeStyle = timelineIntensityColor(intensity);
        ctx.beginPath();
        ctx.moveTo(xFor(left), yFor(left));
        ctx.lineTo(xFor(right), yFor(right));
        ctx.stroke();
        ctx.fillStyle = timelineIntensityColor(intensity, 0.28);
        ctx.fillRect(xFor(left), height - padY + 2, Math.max(1, xFor(right) - xFor(left)), 4);
    }

    ctx.fillStyle = 'rgba(216, 182, 106, 0.7)';
    const stride = Math.max(1, Math.ceil(visibleActions.length / 180));
    visibleActions.forEach((action, index) => {
        if (index % stride !== 0 && index !== visibleActions.length - 1) return;
        ctx.beginPath();
        ctx.arc(xFor(action), yFor(action), 2, 0, Math.PI * 2);
        ctx.fill();
    });
    ctx.fillStyle = 'rgba(232, 230, 223, 0.62)';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(`${msToSeconds(start)}s`, padX, height - 3);
    ctx.textAlign = 'right';
    ctx.fillText(`${msToSeconds(end)}s`, width - padX, height - 3);
    ctx.textAlign = 'left';
}

function clampStudioCropWindow(startMs, endMs, duration, changed = '') {
    const sourceDuration = Math.max(1, Math.round(Number(duration) || 1));
    const minimum = Math.min(MIN_CROP_DURATION_MS, sourceDuration);
    let start = Math.max(0, Math.min(sourceDuration - minimum, Math.round(Number(startMs) || 0)));
    let end = Math.max(start + minimum, Math.min(sourceDuration, Math.round(Number(endMs) || sourceDuration)));
    if (end - start > STUDIO_MAX_DURATION_MS) {
        if (changed.includes('start')) {
            end = Math.min(sourceDuration, start + STUDIO_MAX_DURATION_MS);
        } else {
            start = Math.max(0, end - STUDIO_MAX_DURATION_MS);
        }
    }
    if (changed.includes('start') && start >= end) {
        end = Math.min(sourceDuration, start + minimum);
    }
    if (changed.includes('end') && end <= start) {
        start = Math.max(0, end - minimum);
    }
    return {start, end};
}

function syncCropControlsFromState() {
    const source = state.motionStudioSourcePattern;
    const duration = sourceDurationMs(source);
    const maxSeconds = msToSeconds(duration);
    const startSeconds = msToSeconds(state.motionStudioCropStartMs);
    const endSeconds = msToSeconds(state.motionStudioCropEndMs || duration);
    [el.motionStudioCropStartInput, el.motionStudioCropEndInput].forEach(control => {
        if (!control) return;
        control.max = String(maxSeconds);
    });
    if (el.motionStudioCropStartInput) el.motionStudioCropStartInput.value = String(startSeconds);
    if (el.motionStudioCropEndInput) el.motionStudioCropEndInput.value = String(endSeconds);
    if (el.motionStudioCropDuration) {
        el.motionStudioCropDuration.textContent = duration > 0
            ? `${maxSeconds}s source | ${msToSeconds(Math.max(0, state.motionStudioCropEndMs - state.motionStudioCropStartMs))}s selected`
            : 'No source loaded';
    }
    syncStudioTimelineControlsFromState();
    updateStudioTimelineHandles();
    drawStudioCropTimeline();
    setCropControlsEnabled(Boolean(source && duration > 0));
}

function updateStudioCropFromValues(startMs, endMs, changed = '') {
    const source = state.motionStudioSourcePattern;
    if (!source) return;
    const duration = sourceDurationMs(source);
    const {start, end} = clampStudioCropWindow(startMs, endMs, duration, changed);
    state.motionStudioCropStartMs = start;
    state.motionStudioCropEndMs = end;
    syncCropControlsFromState();
    drawMotionTrainingPreview();
}

function updateStudioCropFromControls(changed = '') {
    const source = state.motionStudioSourcePattern;
    if (!source) return;
    const duration = sourceDurationMs(source);
    const start = secondsToMs(el.motionStudioCropStartInput?.value, duration);
    const end = secondsToMs(el.motionStudioCropEndInput?.value, duration);
    updateStudioCropFromValues(start, end, changed);
}

function resetStudioCropWindow(pattern) {
    const duration = sourceDurationMs(pattern);
    state.motionStudioCropStartMs = 0;
    state.motionStudioCropEndMs = Math.min(duration, STUDIO_MAX_DURATION_MS);
    resetStudioTimelineView();
    syncCropControlsFromState();
}

export function studioCropPreviewPayload() {
    if (!state.motionStudioSourcePattern) return;
    const cropped = cropPatternToWindow(
        state.motionStudioSourcePattern,
        state.motionStudioCropStartMs,
        state.motionStudioCropEndMs,
    );
    const start = msToSeconds(state.motionStudioCropStartMs);
    const end = msToSeconds(state.motionStudioCropEndMs);
    const sourceName = patternDisplayName(state.motionStudioSourcePattern);
    return {
        ...cropped,
        id: `${state.motionStudioSourcePattern.id || sourceName} ${start}-${end}s crop-preview`,
        name: `${sourceName} ${start}-${end}s crop`,
        description: `Cropped ${start}-${end}s from ${sourceName}.`,
    };
}

function applyStudioCrop() {
    if (!state.motionStudioSourcePattern) return;
    try {
        const cropped = studioCropPreviewPayload();
        setStudioEditedPattern(
            cropped,
            `Loaded ${formatPatternDuration(cropped.duration_ms)} crop as an unsaved pattern.`,
            {dirty: true, sourcePattern: state.motionStudioSourcePattern},
        );
    } catch (error) {
        setStudioStatus(error.message || 'Could not crop imported pattern.', 'var(--yellow)');
    }
}

async function importStudioPatternFile(file) {
    if (!file) return;
    try {
        clearStudioImportSource();
        showStudioFlow('import');
        state.motionStudioDrawingEnabled = false;
        setStudioStatus(`Reading ${file.name}...`);
        const payload = JSON.parse(await file.text());
        const pattern = patternFromImportPayload(payload, file.name);
        state.motionStudioSourcePattern = pattern;
        resetStudioCropWindow(pattern);
        const actionNote = pattern.action_count > STUDIO_MAX_ACTIONS
            ? ` Crop before saving; saved patterns are capped at ${STUDIO_MAX_ACTIONS} actions.`
            : '';
        setStudioStatus(
            `Loaded ${patternDisplayName(pattern)}: ${formatPatternDuration(pattern.duration_ms)}, ${pattern.action_count} actions.${actionNote}`,
            'var(--cyan)',
        );
        setStudioEditedPattern(
            cropPatternToWindow(pattern, 0, Math.min(pattern.duration_ms, STUDIO_MAX_DURATION_MS)),
            'Imported source loaded. Adjust the crop window, then use the crop as an unsaved pattern.',
            {dirty: true, sourcePattern: pattern},
        );
    } catch (error) {
        setStudioStatus(error.message || `Could not import ${file.name}.`, 'var(--yellow)');
    } finally {
        if (el.motionStudioImportInput) el.motionStudioImportInput.value = '';
    }
}

function startNewDrawnPattern() {
    clearStudioImportSource();
    showStudioFlow('draw');
    state.motionStudioDrawingEnabled = true;
    const pattern = createBlankStudioPattern();
    setStudioEditedPattern(pattern, 'Draw mode is on. Drag across the Edited graph to create a pattern.', {dirty: true});
    setStudioStatus('Drawing a new unsaved pattern. Drag across the Edited graph, then save it.', 'var(--cyan)');
}

function clearStudioDrawing() {
    if (!state.motionTrainingEditedPattern) return;
    setEditedPatternActions(createBlankStudioPattern(state.motionTrainingEditedPattern.duration_ms || DEFAULT_DRAW_DURATION_MS).actions, 'Cleared the drawing.');
}

function canvasActionFromEvent(canvas, event) {
    const pattern = state.motionTrainingEditedPattern || createBlankStudioPattern();
    const actions = normalizedActions(pattern.actions);
    const duration = actions.length > 1 ? actions[actions.length - 1].at - actions[0].at : DEFAULT_DRAW_DURATION_MS;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, rect.width || canvas.width || 1);
    const height = Math.max(1, rect.height || canvas.height || 1);
    const x = clampNumber((event.clientX ?? 0) - rect.left, 0, width, 0);
    const y = clampNumber((event.clientY ?? 0) - rect.top, 0, height, 0);
    return {
        at: Math.round((x / width) * duration),
        pos: clampNumber(100 - ((y / height) * 100), 0, 100, 50),
    };
}

function pushDrawAction(action) {
    const buffer = state.motionStudioDrawBuffer || [];
    const last = buffer[buffer.length - 1];
    if (last && Math.abs(last.at - action.at) < 35 && Math.abs(last.pos - action.pos) < 1) return;
    buffer.push(action);
    state.motionStudioDrawBuffer = buffer;
}

function finishStudioDrawing() {
    state.motionStudioDrawingActive = false;
    const buffer = normalizedActions(state.motionStudioDrawBuffer);
    state.motionStudioDrawBuffer = [];
    if (buffer.length < 2 || !state.motionTrainingEditedPattern) return;
    const duration = Math.max(
        DEFAULT_DRAW_DURATION_MS,
        state.motionTrainingEditedPattern.duration_ms || DEFAULT_DRAW_DURATION_MS,
        buffer[buffer.length - 1].at,
    );
    const actions = [...buffer];
    if (actions[0].at > 0) actions.unshift({at: 0, pos: actions[0].pos});
    if (actions[actions.length - 1].at < duration) {
        actions.push({at: duration, pos: actions[actions.length - 1].pos});
    }
    setEditedPatternActions(actions, `Drew ${actions.length} points on the temporary pattern.`);
}

function handleStudioCanvasPointer(event) {
    if (!state.motionStudioDrawingEnabled || !state.motionTrainingEditedPattern || !el.motionTrainingPreviewCanvas) return;
    event.preventDefault?.();
    if (event.type === 'pointerdown') {
        state.motionStudioDrawingActive = true;
        state.motionStudioDrawBuffer = [];
        el.motionTrainingPreviewCanvas.setPointerCapture?.(event.pointerId);
    }
    if (!state.motionStudioDrawingActive) return;
    pushDrawAction(canvasActionFromEvent(el.motionTrainingPreviewCanvas, event));
    if (event.type === 'pointerup' || event.type === 'pointercancel' || event.type === 'pointerleave') {
        finishStudioDrawing();
    }
}

function cropTimelineMsFromEvent(event) {
    const source = state.motionStudioSourcePattern;
    const view = studioTimelineViewWindow(source);
    if (!source || view.duration <= 0 || !el.motionStudioCropTimeline) return 0;
    const rect = el.motionStudioCropTimeline.getBoundingClientRect();
    const width = Math.max(1, rect.width || el.motionStudioCropTimeline.clientWidth || el.motionStudioCropTimeline.offsetWidth || 1);
    const x = clampNumber((event.clientX ?? 0) - rect.left, 0, width, 0);
    return timelineMsForPercent(x / width, view);
}

function updateStudioCropFromTimeline(handleName, event) {
    if (!state.motionStudioSourcePattern) return;
    const targetMs = cropTimelineMsFromEvent(event);
    if (handleName === 'start') {
        updateStudioCropFromValues(targetMs, state.motionStudioCropEndMs, 'start');
    } else {
        updateStudioCropFromValues(state.motionStudioCropStartMs, targetMs, 'end');
    }
}

function startStudioCropHandleDrag(handleName, event) {
    if (!state.motionStudioSourcePattern) return;
    event.preventDefault?.();
    state.motionStudioCropDragHandle = handleName;
    event.currentTarget?.setPointerCapture?.(event.pointerId);
    updateStudioCropFromTimeline(handleName, event);
}

function handleStudioCropTimelinePointerDown(event) {
    if (!state.motionStudioSourcePattern || event.target === el.motionStudioCropStartHandle || event.target === el.motionStudioCropEndHandle) return;
    event.preventDefault?.();
    const targetMs = cropTimelineMsFromEvent(event);
    const startDistance = Math.abs(targetMs - state.motionStudioCropStartMs);
    const endDistance = Math.abs(targetMs - state.motionStudioCropEndMs);
    const handleName = startDistance <= endDistance ? 'start' : 'end';
    state.motionStudioCropDragHandle = handleName;
    updateStudioCropFromTimeline(handleName, event);
}

function handleStudioCropPointerMove(event) {
    if (!state.motionStudioCropDragHandle) return;
    event.preventDefault?.();
    updateStudioCropFromTimeline(state.motionStudioCropDragHandle, event);
}

function finishStudioCropDrag() {
    state.motionStudioCropDragHandle = '';
}

function handleStudioCropHandleKeydown(handleName, event) {
    if (!state.motionStudioSourcePattern) return;
    const duration = sourceDurationMs(state.motionStudioSourcePattern);
    const step = event.shiftKey ? 1000 : 100;
    let delta = 0;
    if (event.key === 'ArrowLeft') delta = -step;
    else if (event.key === 'ArrowRight') delta = step;
    else if (event.key === 'Home') {
        event.preventDefault?.();
        if (handleName === 'start') updateStudioCropFromValues(0, state.motionStudioCropEndMs, 'start');
        else updateStudioCropFromValues(state.motionStudioCropStartMs, MIN_CROP_DURATION_MS, 'end');
        return;
    } else if (event.key === 'End') {
        event.preventDefault?.();
        if (handleName === 'start') updateStudioCropFromValues(Math.max(0, duration - MIN_CROP_DURATION_MS), state.motionStudioCropEndMs, 'start');
        else updateStudioCropFromValues(state.motionStudioCropStartMs, duration, 'end');
        return;
    } else {
        return;
    }
    event.preventDefault?.();
    if (handleName === 'start') {
        updateStudioCropFromValues(state.motionStudioCropStartMs + delta, state.motionStudioCropEndMs, 'start');
    } else {
        updateStudioCropFromValues(state.motionStudioCropStartMs, state.motionStudioCropEndMs + delta, 'end');
    }
}

function timelineAnchorMsFromEvent(event) {
    const source = state.motionStudioSourcePattern;
    const view = studioTimelineViewWindow(source);
    if (!source || view.duration <= 0 || !el.motionStudioCropTimeline) return null;
    const rect = el.motionStudioCropTimeline.getBoundingClientRect();
    const width = Math.max(1, rect.width || el.motionStudioCropTimeline.clientWidth || el.motionStudioCropTimeline.offsetWidth || 1);
    const x = clampNumber((event.clientX ?? 0) - rect.left, 0, width, 0);
    return timelineMsForPercent(x / width, view);
}

function handleStudioTimelineWheel(event) {
    if (!state.motionStudioSourcePattern) return;
    event.preventDefault?.();
    const anchor = timelineAnchorMsFromEvent(event);
    const direction = (event.deltaY || 0) > 0 ? -1 : 1;
    const factor = direction > 0 ? 1.25 : 0.8;
    setStudioTimelineZoom(studioTimelineZoom() * factor, anchor);
}

export function bindMotionPatternStudioControls() {
    el.motionStudioNewPatternBtn?.addEventListener('click', startNewDrawnPattern);
    el.motionStudioImportBtn?.addEventListener('click', () => el.motionStudioImportInput?.click());
    el.motionStudioImportInput?.addEventListener('change', event => importStudioPatternFile(event.target.files?.[0]));
    el.motionStudioApplyCropBtn?.addEventListener('click', applyStudioCrop);
    el.motionStudioDrawToggleBtn?.addEventListener('click', () => {
        state.motionStudioDrawingEnabled = !state.motionStudioDrawingEnabled;
        updateMotionTrainingEditButtons();
        setStudioStatus(
            state.motionStudioDrawingEnabled
                ? 'Draw mode is on. Drag across the Edited graph to replace the temporary pattern.'
                : 'Draw mode is off.',
            state.motionStudioDrawingEnabled ? 'var(--cyan)' : 'var(--comment)',
        );
    });
    el.motionStudioClearDrawingBtn?.addEventListener('click', clearStudioDrawing);
    el.motionStudioZoomSlider?.addEventListener('input', event => {
        setStudioTimelineZoom(Number(event.target?.value) || 1);
    });
    el.motionStudioZoomOutBtn?.addEventListener('click', () => {
        setStudioTimelineZoom(studioTimelineZoom() / 1.25);
    });
    el.motionStudioZoomInBtn?.addEventListener('click', () => {
        setStudioTimelineZoom(studioTimelineZoom() * 1.25);
    });
    el.motionStudioFitBtn?.addEventListener('click', () => {
        resetStudioTimelineView();
        syncCropControlsFromState();
    });
    el.motionStudioPanSlider?.addEventListener('input', event => {
        setStudioTimelineOffsetMs(Math.round((Number(event.target?.value) || 0) * 1000));
    });
    [
        [el.motionStudioCropStartInput, 'start-input'],
        [el.motionStudioCropEndInput, 'end-input'],
    ].forEach(([control, name]) => {
        control?.addEventListener('input', () => updateStudioCropFromControls(name));
    });
    el.motionStudioCropStartHandle?.addEventListener('pointerdown', event => startStudioCropHandleDrag('start', event));
    el.motionStudioCropEndHandle?.addEventListener('pointerdown', event => startStudioCropHandleDrag('end', event));
    el.motionStudioCropStartHandle?.addEventListener('keydown', event => handleStudioCropHandleKeydown('start', event));
    el.motionStudioCropEndHandle?.addEventListener('keydown', event => handleStudioCropHandleKeydown('end', event));
    el.motionStudioCropTimeline?.addEventListener('pointerdown', handleStudioCropTimelinePointerDown);
    el.motionStudioCropTimeline?.addEventListener('wheel', handleStudioTimelineWheel, {passive: false});
    D.addEventListener?.('pointermove', handleStudioCropPointerMove);
    ['pointerup', 'pointercancel'].forEach(eventName => {
        D.addEventListener?.(eventName, finishStudioCropDrag);
    });
    ['pointerdown', 'pointermove', 'pointerup', 'pointercancel', 'pointerleave'].forEach(eventName => {
        el.motionTrainingPreviewCanvas?.addEventListener(eventName, handleStudioCanvasPointer);
    });
    syncCropControlsFromState();
    updateMotionTrainingEditButtons();
}

export function drawOpenMotionTrainingPreview() {
    if (el.motionTrainingDialog?.classList.contains('open')) drawMotionTrainingPreview();
}
