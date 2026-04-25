import { D, el, state } from '../context.js';

const MOTION_SEQUENCE_LOG_LIMIT = 40;

let motionSequenceLogInitialized = false;
let lastMotionSequenceLogKey = '';

function observationNumber(value, fallback = 0) {
    if (value === null || value === undefined || value === '') return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function clampPercent(value, fallback = 0) {
    return Math.max(0, Math.min(100, observationNumber(value, fallback)));
}

export function formatClockElapsed(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainingSeconds = total % 60;
    const twoDigit = value => String(value).padStart(2, '0');
    if (hours > 0) {
        return `${hours}:${twoDigit(minutes)}:${twoDigit(remainingSeconds)}`;
    }
    return `${twoDigit(minutes)}:${twoDigit(remainingSeconds)}`;
}

export function latestTracePoint(payload = {}) {
    const trace = Array.isArray(payload.trace) ? payload.trace : [];
    return trace.length ? trace[trace.length - 1] || {} : {};
}

function recentMotionLabels(payload = {}, limit = 4) {
    const trace = Array.isArray(payload.trace) ? payload.trace : [];
    const labels = [];
    const seen = new Set();
    for (let index = trace.length - 1; index >= 0 && labels.length < limit; index--) {
        const point = trace[index] || {};
        const label = String(point.label || point.source || '').trim();
        if (!label) continue;
        const key = label.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        labels.unshift(label);
    }
    if (!labels.length) {
        const fallback = String(payload.label || payload.source || '').trim();
        if (fallback) labels.push(fallback);
    }
    return labels;
}

export function formatBackendName(backend) {
    return backend === 'position' ? 'Position' : 'HAMP';
}

export function formatMotionTraceTiming(point = {}) {
    const parts = [];
    if (point.batch_gap_ms !== undefined) parts.push(`batch ${observationNumber(point.batch_gap_ms, 0).toFixed(1)}ms`);
    if (point.gap_ms !== undefined) parts.push(`gap ${observationNumber(point.gap_ms, 0).toFixed(1)}ms`);
    if (point.command_ms !== undefined) parts.push(`cmd ${observationNumber(point.command_ms, 0).toFixed(1)}ms`);
    return parts;
}

export function formatMotionFrame(point = {}) {
    if (point.frame_index === undefined || point.frame_count === undefined) return '';
    return `frame ${Number(point.frame_index) + 1}/${Number(point.frame_count)}`;
}

export function formatMotionSequenceText(payload = {}, level = 'compact') {
    const diagnostics = payload.diagnostics || {};
    const point = latestTracePoint(payload);
    const labels = recentMotionLabels(payload);
    const sequence = labels.join(' -> ') || 'Idle';
    if (level === 'compact') return sequence;

    const speed = Math.round(clampPercent(point.speed ?? diagnostics.relative_speed, 0));
    const depth = Math.round(clampPercent(point.depth ?? diagnostics.depth, 50));
    const range = Math.round(clampPercent(point.range ?? diagnostics.range, 50));
    const parts = [
        sequence,
        `${speed}% spd`,
        `${depth}% d / ${range}% r`,
        formatBackendName(payload.backend || state.motionBackend),
    ];
    if (level === 'status') parts.push(...formatMotionTraceTiming(point).slice(0, 2));
    if (level === 'debug') {
        const frame = formatMotionFrame(point);
        if (frame) parts.push(frame);
        parts.push(...formatMotionTraceTiming(point));
        if (point.is_pass_through_final) parts.push('pass-through final');
        parts.push(payload.playback_active ? 'playback active' : 'playback idle');
    }
    return parts.filter(Boolean).join(' | ');
}

function motionSequenceLogTime() {
    return formatClockElapsed(state.activeModeElapsedSeconds ?? 0);
}

function motionSequenceLogKey(text, payload = {}, level = 'compact') {
    const point = latestTracePoint(payload);
    return [
        level,
        text,
        payload.source || '',
        payload.backend || state.motionBackend || '',
        payload.playback_active ? 'active' : 'idle',
        point.label || '',
        point.frame_index ?? '',
        point.frame_count ?? '',
        point.t ?? point.time ?? '',
    ].join('|');
}

function appendMotionSequenceLogEntry(text, payload = {}, level = 'compact') {
    if (!el.motionSequenceIndicator) return;
    const value = String(text || 'Idle').trim() || 'Idle';
    const key = motionSequenceLogKey(value, payload, level);
    if (key === lastMotionSequenceLogKey) return;
    lastMotionSequenceLogKey = key;

    if (!motionSequenceLogInitialized) {
        el.motionSequenceIndicator.replaceChildren();
        motionSequenceLogInitialized = true;
    }

    const entry = D.createElement('div');
    entry.className = 'motion-sequence-entry';
    if (value === 'Idle') entry.classList.add('is-idle');

    const time = D.createElement('span');
    time.className = 'motion-sequence-time';
    time.textContent = motionSequenceLogTime();

    const message = D.createElement('span');
    message.className = 'motion-sequence-text';
    message.textContent = value;

    entry.append(time, message);
    el.motionSequenceIndicator.appendChild(entry);
    while (el.motionSequenceIndicator.children.length > MOTION_SEQUENCE_LOG_LIMIT) {
        el.motionSequenceIndicator.removeChild(el.motionSequenceIndicator.firstElementChild);
    }
    el.motionSequenceIndicator.scrollTop = el.motionSequenceIndicator.scrollHeight;
}

export function updateMotionSequenceIndicator(payload = {}) {
    if (!el.motionSequenceIndicator) return;
    const level = payload.diagnostics_level || state.motionDiagnosticsLevel || 'compact';
    state.motionDiagnosticsLevel = level;
    const source = String(payload.source || '').trim();
    const sequence = formatMotionSequenceText(payload, level);
    appendMotionSequenceLogEntry(sequence, payload, level);
    el.motionSequenceIndicator.title = source && source !== sequence
        ? `${source}: ${sequence}`
        : sequence;
}

export function resetMotionSequenceLog() {
    lastMotionSequenceLogKey = '';
    motionSequenceLogInitialized = false;
    if (el.motionSequenceIndicator) el.motionSequenceIndicator.textContent = 'Idle';
}
