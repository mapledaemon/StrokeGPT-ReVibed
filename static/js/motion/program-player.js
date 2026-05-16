import { D, clampNumber, el, fetchWithConnectionState, reportSaveFailure, setStatusMessage, state } from '../context.js';
import { formatPatternDuration, normalizedActions } from './pattern-list.js';
import { formatProgramDuration, formatProgramMetadata } from './program-list.js';
import { segmentIntensity, timelineIntensityColor } from './training-editor.js';


const PROGRAM_SECTION_MIN_DURATION_MS = 100;


let renderMotionPatternsCallback = null;
let updateMotionTrainingStatusCallback = null;
let programPlayerControlsBound = false;


export function configureMotionProgramPlayer({renderMotionPatterns, updateMotionTrainingStatus} = {}) {
    renderMotionPatternsCallback = renderMotionPatterns || null;
    updateMotionTrainingStatusCallback = updateMotionTrainingStatus || null;
}


function selectedProgram() {
    return state.motionProgramSelected;
}


function programDisplayName(program) {
    return program?.name || program?.id || 'Program';
}


function programDurationMs(program) {
    const explicit = Number(program?.duration_ms);
    if (Number.isFinite(explicit) && explicit > 0) return explicit;
    const actions = normalizedActions(program?.actions);
    return actions.length > 1 ? actions[actions.length - 1].at - actions[0].at : 0;
}


function msToSeconds(ms) {
    return Math.round((Number(ms) || 0) / 100) / 10;
}


function secondsToMs(seconds) {
    return Math.round((Number(seconds) || 0) * 1000);
}


function programActionAt(actions, at) {
    if (!actions.length) return {at, pos: 50};
    if (at <= actions[0].at) return {at, pos: actions[0].pos};
    const last = actions[actions.length - 1];
    if (at >= last.at) return {at, pos: last.pos};
    for (let index = 1; index < actions.length; index++) {
        const right = actions[index];
        if (right.at < at) continue;
        const left = actions[index - 1];
        const span = Math.max(1, right.at - left.at);
        const amount = (at - left.at) / span;
        return {at, pos: left.pos + ((right.pos - left.pos) * amount)};
    }
    return {at, pos: last.pos};
}


export function programSectionBounds(program, startMs, endMs, minDurationMs = PROGRAM_SECTION_MIN_DURATION_MS) {
    const duration = Math.max(0, programDurationMs(program));
    if (duration <= 0) return {startMs: 0, endMs: 0, durationMs: 0};
    const minimum = Math.max(1, Number(minDurationMs) || 100);
    let start = Math.round(Number(startMs));
    let end = Math.round(Number(endMs));
    if (!Number.isFinite(start)) start = 0;
    if (!Number.isFinite(end)) end = Math.min(duration, 30_000);
    start = Math.max(0, Math.min(Math.max(0, duration - minimum), start));
    end = Math.max(start + minimum, Math.min(duration, end));
    if (end > duration) {
        end = duration;
        start = Math.max(0, end - minimum);
    }
    return {startMs: start, endMs: end, durationMs: end - start};
}


export function programSectionActions(program, startMs, endMs) {
    const actions = normalizedActions(program?.actions);
    if (actions.length < 2) return [];
    const bounds = programSectionBounds(program, startMs, endMs);
    if (bounds.durationMs <= 0) return [];
    return normalizedActions([
        programActionAt(actions, bounds.startMs),
        ...actions.filter(action => action.at > bounds.startMs && action.at < bounds.endMs),
        programActionAt(actions, bounds.endMs),
    ].map(action => ({at: action.at - bounds.startMs, pos: action.pos})));
}


function currentSectionBounds() {
    return programSectionBounds(
        selectedProgram(),
        state.motionProgramSectionStartMs,
        state.motionProgramSectionEndMs,
    );
}


function setProgramSectionRange(startMs, endMs, changed = '') {
    const program = selectedProgram();
    const duration = programDurationMs(program);
    if (!program || duration <= 0) return;
    let start = Math.round(Number(startMs));
    let end = Math.round(Number(endMs));
    if (!Number.isFinite(start)) start = state.motionProgramSectionStartMs;
    if (!Number.isFinite(end)) end = state.motionProgramSectionEndMs || duration;

    if (changed === 'start') {
        end = clampNumber(end, Math.min(duration, PROGRAM_SECTION_MIN_DURATION_MS), duration, duration);
        start = clampNumber(start, 0, Math.max(0, end - PROGRAM_SECTION_MIN_DURATION_MS), 0);
    } else if (changed === 'end') {
        start = clampNumber(start, 0, Math.max(0, duration - PROGRAM_SECTION_MIN_DURATION_MS), 0);
        end = clampNumber(end, Math.min(duration, start + PROGRAM_SECTION_MIN_DURATION_MS), duration, duration);
    } else {
        const bounds = programSectionBounds(program, start, end);
        start = bounds.startMs;
        end = bounds.endMs;
    }

    state.motionProgramSectionStartMs = start;
    state.motionProgramSectionEndMs = end;
    syncSectionInputs();
    drawTimeline();
}


function sectionStatusText(bounds) {
    return `${formatPatternDuration(bounds.durationMs)} selected (${msToSeconds(bounds.startMs)}-${msToSeconds(bounds.endMs)}s)`;
}


function setProgramPlayerStatus(message, tone = 'neutral') {
    setStatusMessage(el.motionProgramPlayerStatus || el.motionProgramStatus || el.statusText, message, tone);
}


async function requestProgramJson(endpoint, options = {}, statusEl = el.motionProgramPlayerStatus) {
    try {
        const response = await fetchWithConnectionState(endpoint, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status === 'error') {
            reportSaveFailure(statusEl || el.statusText, data, data.message || `Request failed: ${response.status}`);
            return data;
        }
        return data;
    } catch {
        return undefined;
    }
}


export function setMotionProgramTab(tabName = 'playback') {
    const active = tabName === 'section' ? 'section' : 'playback';
    state.motionProgramActiveTab = active;
    const playbackActive = active === 'playback';
    const sectionActive = active === 'section';

    for (const [button, isActive] of [
        [el.motionProgramPlaybackTabBtn, playbackActive],
        [el.motionProgramSectionTabBtn, sectionActive],
    ]) {
        if (!button) continue;
        if (isActive) button.classList.add('active');
        else button.classList.remove('active');
        button.setAttribute('aria-selected', isActive ? 'true' : 'false');
    }
    for (const [panel, isActive] of [
        [el.motionProgramPlaybackPanel, playbackActive],
        [el.motionProgramSectionPanel, sectionActive],
    ]) {
        if (!panel) continue;
        if (isActive) panel.classList.add('active');
        else panel.classList.remove('active');
        panel.hidden = !isActive;
    }
}


function programTimelineMsFromEvent(event) {
    const program = selectedProgram();
    const duration = programDurationMs(program);
    if (!program || duration <= 0 || !el.motionProgramRangeTimeline) return 0;
    const rect = el.motionProgramRangeTimeline.getBoundingClientRect?.() || {};
    const width = Math.max(1, rect.width || el.motionProgramRangeTimeline.clientWidth || el.motionProgramRangeTimeline.offsetWidth || 1);
    const x = clampNumber((event.clientX ?? 0) - (rect.left || 0), 0, width, 0);
    return Math.round((x / width) * duration);
}


function updateProgramSectionFromTimeline(handleName, event) {
    const targetMs = programTimelineMsFromEvent(event);
    if (handleName === 'start') {
        setProgramSectionRange(targetMs, state.motionProgramSectionEndMs, 'start');
    } else {
        setProgramSectionRange(state.motionProgramSectionStartMs, targetMs, 'end');
    }
}


function startProgramSectionHandleDrag(handleName, event) {
    if (!selectedProgram()) return;
    event.preventDefault?.();
    state.motionProgramSectionDragHandle = handleName;
    event.currentTarget?.setPointerCapture?.(event.pointerId);
    updateProgramSectionFromTimeline(handleName, event);
}


function handleProgramRangeTimelinePointerDown(event) {
    if (!selectedProgram() || event.target === el.motionProgramSectionStartHandle || event.target === el.motionProgramSectionEndHandle) return;
    event.preventDefault?.();
    const targetMs = programTimelineMsFromEvent(event);
    const startDistance = Math.abs(targetMs - state.motionProgramSectionStartMs);
    const endDistance = Math.abs(targetMs - state.motionProgramSectionEndMs);
    const handleName = startDistance <= endDistance ? 'start' : 'end';
    state.motionProgramSectionDragHandle = handleName;
    updateProgramSectionFromTimeline(handleName, event);
}


function handleProgramRangePointerMove(event) {
    if (!state.motionProgramSectionDragHandle) return;
    event.preventDefault?.();
    updateProgramSectionFromTimeline(state.motionProgramSectionDragHandle, event);
}


function finishProgramRangeDrag() {
    state.motionProgramSectionDragHandle = '';
}


function handleProgramSectionHandleKeydown(handleName, event) {
    const program = selectedProgram();
    const duration = programDurationMs(program);
    if (!program || duration <= 0) return;
    const step = event.shiftKey ? 1000 : 100;
    let delta = 0;
    if (event.key === 'ArrowLeft') delta = -step;
    else if (event.key === 'ArrowRight') delta = step;
    else if (event.key === 'Home') {
        event.preventDefault?.();
        if (handleName === 'start') setProgramSectionRange(0, state.motionProgramSectionEndMs, 'start');
        else setProgramSectionRange(state.motionProgramSectionStartMs, PROGRAM_SECTION_MIN_DURATION_MS, 'end');
        return;
    } else if (event.key === 'End') {
        event.preventDefault?.();
        if (handleName === 'start') setProgramSectionRange(Math.max(0, duration - PROGRAM_SECTION_MIN_DURATION_MS), state.motionProgramSectionEndMs, 'start');
        else setProgramSectionRange(state.motionProgramSectionStartMs, duration, 'end');
        return;
    } else {
        return;
    }
    event.preventDefault?.();
    if (handleName === 'start') {
        setProgramSectionRange(state.motionProgramSectionStartMs + delta, state.motionProgramSectionEndMs, 'start');
    } else {
        setProgramSectionRange(state.motionProgramSectionStartMs, state.motionProgramSectionEndMs + delta, 'end');
    }
}


function syncSectionInputs() {
    const program = selectedProgram();
    const duration = programDurationMs(program);
    const bounds = currentSectionBounds();
    state.motionProgramSectionStartMs = bounds.startMs;
    state.motionProgramSectionEndMs = bounds.endMs;
    const maxSeconds = msToSeconds(duration);
    if (el.motionProgramSectionStartInput) {
        el.motionProgramSectionStartInput.max = String(maxSeconds);
        el.motionProgramSectionStartInput.value = String(msToSeconds(bounds.startMs));
    }
    if (el.motionProgramSectionEndInput) {
        el.motionProgramSectionEndInput.max = String(maxSeconds);
        el.motionProgramSectionEndInput.value = String(msToSeconds(bounds.endMs));
    }
    if (el.motionProgramSectionDuration) {
        el.motionProgramSectionDuration.textContent = sectionStatusText(bounds);
    }
    if (el.motionProgramSectionNameInput && !el.motionProgramSectionNameInput.value.trim()) {
        el.motionProgramSectionNameInput.placeholder = `${programDisplayName(program)} section`;
    }
    updateProgramTimelineHandles();
}


function updateProgramTimelineHandles() {
    const program = selectedProgram();
    const duration = programDurationMs(program);
    const enabled = Boolean(program && duration > 0);
    const bounds = currentSectionBounds();
    const startPercent = enabled ? (bounds.startMs / duration) * 100 : 0;
    const endPercent = enabled ? (bounds.endMs / duration) * 100 : 100;
    if (el.motionProgramSectionSelection) {
        el.motionProgramSectionSelection.hidden = !enabled;
        el.motionProgramSectionSelection.style.left = `${startPercent}%`;
        el.motionProgramSectionSelection.style.width = `${Math.max(0, endPercent - startPercent)}%`;
    }
    [
        [el.motionProgramSectionStartHandle, bounds.startMs, 'start'],
        [el.motionProgramSectionEndHandle, bounds.endMs, 'end'],
    ].forEach(([handle, ms, label]) => {
        if (!handle) return;
        handle.hidden = !enabled;
        handle.disabled = !enabled;
        const percent = enabled ? (ms / duration) * 100 : 0;
        handle.style.left = `${percent}%`;
        handle.setAttribute('aria-valuemin', '0');
        handle.setAttribute('aria-valuemax', String(msToSeconds(duration)));
        handle.setAttribute('aria-valuenow', String(msToSeconds(ms)));
        handle.setAttribute('aria-valuetext', `${label} ${msToSeconds(ms)} seconds`);
    });
    if (el.motionProgramRangeTimeline) {
        if (enabled) el.motionProgramRangeTimeline.classList.remove('disabled');
        else el.motionProgramRangeTimeline.classList.add('disabled');
    }
}


function drawTimeline() {
    const canvas = el.motionProgramTimelineCanvas;
    const program = selectedProgram();
    if (!canvas || !program) return;
    const context = canvas.getContext?.('2d');
    if (!context) return;
    const boundsRect = canvas.getBoundingClientRect?.() || {};
    const width = Math.max(360, Math.round(boundsRect.width || canvas.clientWidth || canvas.width || 720));
    const height = Math.max(120, Math.round(boundsRect.height || canvas.clientHeight || canvas.height || 190));
    canvas.width = width;
    canvas.height = height;

    context.clearRect(0, 0, width, height);
    context.fillStyle = '#101217';
    context.fillRect(0, 0, width, height);

    const actions = normalizedActions(program.actions);
    const duration = programDurationMs(program);
    if (actions.length < 2 || duration <= 0) {
        context.fillStyle = '#66707f';
        context.fillText('No timeline actions loaded.', 20, 28);
        return;
    }

    const padX = 16;
    const padY = 16;
    context.strokeStyle = 'rgba(232, 230, 223, 0.12)';
    context.lineWidth = 1;
    for (let i = 0; i <= 8; i++) {
        const x = padX + (i / 8) * (width - padX * 2);
        context.beginPath();
        context.moveTo(x, padY);
        context.lineTo(x, height - padY);
        context.stroke();
    }
    [0, 25, 50, 75, 100].forEach(position => {
        const y = padY + ((100 - position) / 100) * (height - padY * 2);
        context.beginPath();
        context.moveTo(padX, y);
        context.lineTo(width - padX, y);
        context.stroke();
    });

    const pad = padX;
    const innerWidth = Math.max(1, width - pad * 2);
    const innerHeight = Math.max(1, height - padY * 2);
    const bounds = currentSectionBounds();
    const selectionX = pad + (bounds.startMs / duration) * innerWidth;
    const selectionWidth = Math.max(2, (bounds.durationMs / duration) * innerWidth);

    context.strokeStyle = '#2d333d';
    context.lineWidth = 1;
    context.strokeRect(pad, padY, innerWidth, innerHeight);

    const maxPoints = Math.min(actions.length, 1400);
    const visibleActions = [];
    for (let index = 0; index < maxPoints; index++) {
        const sourceIndex = Math.round((index / Math.max(1, maxPoints - 1)) * (actions.length - 1));
        const action = actions[sourceIndex];
        if (!visibleActions.length || visibleActions[visibleActions.length - 1].at !== action.at) visibleActions.push(action);
    }
    if (visibleActions[0]?.at !== actions[0].at) visibleActions.unshift(actions[0]);
    if (visibleActions[visibleActions.length - 1]?.at !== actions[actions.length - 1].at) visibleActions.push(actions[actions.length - 1]);

    const xFor = action => pad + (action.at / duration) * innerWidth;
    const yFor = action => padY + ((100 - clampNumber(action.pos, 0, 100, 50)) / 100) * innerHeight;
    context.lineWidth = 2.5;
    for (let index = 1; index < visibleActions.length; index++) {
        const left = visibleActions[index - 1];
        const right = visibleActions[index];
        const intensity = segmentIntensity(left, right);
        context.strokeStyle = timelineIntensityColor(intensity);
        context.beginPath();
        context.moveTo(xFor(left), yFor(left));
        context.lineTo(xFor(right), yFor(right));
        context.stroke();
        context.fillStyle = timelineIntensityColor(intensity, 0.28);
        context.fillRect(xFor(left), height - padY + 2, Math.max(1, xFor(right) - xFor(left)), 4);
    }

    context.fillStyle = 'rgba(127, 183, 163, 0.12)';
    context.fillRect(selectionX, padY, selectionWidth, innerHeight);
    context.strokeStyle = 'rgba(216, 182, 106, 0.95)';
    context.lineWidth = 2;
    [selectionX, selectionX + selectionWidth].forEach(x => {
        context.beginPath();
        context.moveTo(x, padY);
        context.lineTo(x, height - padY);
        context.stroke();
    });

    context.fillStyle = 'rgba(216, 182, 106, 0.72)';
    const pointStride = Math.max(1, Math.ceil(visibleActions.length / 180));
    visibleActions.forEach((action, index) => {
        if (index % pointStride !== 0 && index !== visibleActions.length - 1) return;
        const x = pad + (action.at / duration) * innerWidth;
        const y = padY + ((100 - action.pos) / 100) * innerHeight;
        context.beginPath();
        context.arc(x, y, 2, 0, Math.PI * 2);
        context.fill();
    });

    context.fillStyle = '#66707f';
    context.font = '11px Inter, sans-serif';
    context.fillText(`0s`, pad, height - 8);
    context.textAlign = 'right';
    context.fillText(formatProgramDuration(duration), width - pad, height - 8);
    context.textAlign = 'left';
    updateProgramTimelineHandles();
}


export function renderMotionProgramWindow(program) {
    state.motionProgramSelected = program || null;
    if (!program) {
        setProgramPlayerStatus('No Program loaded.', 'neutral');
        return;
    }
    const duration = programDurationMs(program);
    if (!state.motionProgramSectionEndMs || state.motionProgramSectionEndMs > duration) {
        state.motionProgramSectionStartMs = 0;
        state.motionProgramSectionEndMs = Math.min(duration, 30_000);
    }
    if (el.motionProgramDialogTitle) el.motionProgramDialogTitle.textContent = programDisplayName(program);
    if (el.motionProgramDialogMeta) el.motionProgramDialogMeta.textContent = formatProgramMetadata(program);
    syncSectionInputs();
    setProgramPlayerStatus(`Loaded ${programDisplayName(program)}.`, 'success');
    setMotionProgramTab(state.motionProgramActiveTab);
    drawTimeline();
}


export async function openMotionProgramWindow(programId) {
    const cleanId = String(programId || '').trim();
    if (!cleanId) return null;
    if (el.motionProgramDialog) el.motionProgramDialog.classList.add('open');
    setProgramPlayerStatus('Loading Program...', 'neutral');
    const data = await requestProgramJson(`/motion_programs/${encodeURIComponent(cleanId)}`);
    if (data && data.status === 'success' && data.program) {
        state.motionProgramSectionStartMs = 0;
        state.motionProgramSectionEndMs = Math.min(programDurationMs(data.program), 30_000);
        renderMotionProgramWindow(data.program);
    }
    return data;
}


export function closeMotionProgramWindow() {
    el.motionProgramDialog?.classList.remove('open');
}


function sectionRequestBody() {
    const bounds = currentSectionBounds();
    return {start_ms: bounds.startMs, end_ms: bounds.endMs};
}


export async function playSelectedMotionProgram({full = false} = {}) {
    const program = selectedProgram();
    if (!program?.id) {
        setProgramPlayerStatus('Open a Program before playback.', 'warning');
        return null;
    }
    const body = full ? {} : sectionRequestBody();
    setProgramPlayerStatus(full ? 'Starting full Program...' : 'Starting Program section...', 'neutral');
    const data = await requestProgramJson(`/motion_programs/${encodeURIComponent(program.id)}/play`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    if (data && data.motion_training) {
        updateMotionTrainingStatusCallback?.(data.motion_training);
        setProgramPlayerStatus(data.motion_training.message || 'Program playback started.', 'success');
        setStatusMessage(el.statusText, data.motion_training.message || 'Program playback started.', 'success');
    }
    return data;
}


export async function stopMotionProgramPlayback() {
    const data = await requestProgramJson('/motion_training/stop', {method: 'POST'});
    if (data && data.motion_training) {
        updateMotionTrainingStatusCallback?.(data.motion_training);
        setProgramPlayerStatus(data.motion_training.message || 'Program playback stopped.', 'neutral');
    }
    return data;
}


export async function saveSelectedProgramSectionAsPattern() {
    const program = selectedProgram();
    if (!program?.id) {
        setProgramPlayerStatus('Open a Program before saving a section.', 'warning');
        return null;
    }
    const body = sectionRequestBody();
    body.name = el.motionProgramSectionNameInput?.value?.trim?.() || '';
    setProgramPlayerStatus('Saving Program section as pattern...', 'neutral');
    const data = await requestProgramJson(`/motion_programs/${encodeURIComponent(program.id)}/sections/save_pattern`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    if (data && data.status === 'success') {
        if (data.motion_patterns) renderMotionPatternsCallback?.(data.motion_patterns);
        setProgramPlayerStatus(data.message || 'Saved section as pattern.', 'success');
        setStatusMessage(el.statusText, data.message || 'Saved section as pattern.', 'success');
        if (el.motionProgramSectionNameInput) el.motionProgramSectionNameInput.value = '';
    }
    return data;
}


function updateSectionFromInputs() {
    state.motionProgramSectionStartMs = secondsToMs(el.motionProgramSectionStartInput?.value);
    state.motionProgramSectionEndMs = secondsToMs(el.motionProgramSectionEndInput?.value);
    syncSectionInputs();
    drawTimeline();
}


export function bindMotionProgramPlayerControls() {
    if (programPlayerControlsBound) return;
    programPlayerControlsBound = true;
    el.closeMotionProgramBtn?.addEventListener('click', closeMotionProgramWindow);
    el.motionProgramDialog?.addEventListener('click', event => {
        if (event.target === el.motionProgramDialog) closeMotionProgramWindow();
    });
    el.motionProgramPlaybackTabBtn?.addEventListener('click', () => setMotionProgramTab('playback'));
    el.motionProgramSectionTabBtn?.addEventListener('click', () => setMotionProgramTab('section'));
    el.playMotionProgramFullBtn?.addEventListener('click', () => playSelectedMotionProgram({full: true}));
    el.playMotionProgramSectionBtn?.addEventListener('click', () => playSelectedMotionProgram({full: false}));
    el.stopMotionProgramPlaybackBtn?.addEventListener('click', stopMotionProgramPlayback);
    el.saveMotionProgramSectionPatternBtn?.addEventListener('click', saveSelectedProgramSectionAsPattern);
    el.motionProgramSectionStartInput?.addEventListener('change', updateSectionFromInputs);
    el.motionProgramSectionEndInput?.addEventListener('change', updateSectionFromInputs);
    el.motionProgramSectionStartInput?.addEventListener('input', updateSectionFromInputs);
    el.motionProgramSectionEndInput?.addEventListener('input', updateSectionFromInputs);
    el.motionProgramSectionStartHandle?.addEventListener('pointerdown', event => startProgramSectionHandleDrag('start', event));
    el.motionProgramSectionEndHandle?.addEventListener('pointerdown', event => startProgramSectionHandleDrag('end', event));
    el.motionProgramSectionStartHandle?.addEventListener('keydown', event => handleProgramSectionHandleKeydown('start', event));
    el.motionProgramSectionEndHandle?.addEventListener('keydown', event => handleProgramSectionHandleKeydown('end', event));
    el.motionProgramRangeTimeline?.addEventListener('pointerdown', handleProgramRangeTimelinePointerDown);
    D.addEventListener?.('pointermove', handleProgramRangePointerMove);
    ['pointerup', 'pointercancel'].forEach(eventName => {
        D.addEventListener?.(eventName, finishProgramRangeDrag);
    });
    window.addEventListener('resize', () => {
        if (el.motionProgramDialog?.classList.contains('open')) drawTimeline();
    });
}
