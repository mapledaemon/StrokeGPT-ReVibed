// Behavioral coverage for the sidebar Handy visualizer. The cylinder's lighter
// oval is a static track; only the purple horizontal slider line should move
// from the active backend's commanded motion output.

import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import {
    pollMotionStatus,
    updateMotionObservability,
} from '../../static/js/motion-control.js';
import { state } from '../../static/js/context.js';


function jsonResponse(httpStatus, body) {
    const factory = () => ({
        ok: httpStatus >= 200 && httpStatus < 300,
        status: httpStatus,
        headers: {
            get(name) {
                return name && name.toLowerCase() === 'content-type'
                    ? 'application/json'
                    : null;
            },
        },
        async json() { return body; },
        async blob() { return null; },
        clone() { return factory(); },
    });
    return factory();
}

function continuousPayload(overrides = {}) {
    return {
        backend: 'continuous',
        source: 'unit test',
        label: 'milk continuous',
        playback_active: true,
        last_command_time: 2000,
        diagnostics: {
            relative_speed: 50,
            physical_speed: 60,
            depth: 50,
            physical_depth: 50,
            range: 60,
            calibrated_range: {min: 0, max: 100},
            full_travel_mm: 110,
            hamp_started: false,
        },
        trace: [
            {t: 1000.00, speed: 50, physical_speed: 60, depth: 12, range: 60, label: 'milk continuous', continuous: true, program_range: {min: 8, max: 92}},
            {t: 1000.16, speed: 50, physical_speed: 60, depth: 88, range: 60, label: 'milk continuous', continuous: true, program_range: {min: 8, max: 92}},
        ],
        ...overrides,
    };
}

function primeStaticTrack() {
    const range = getStubElement('handy-cylinder-range');
    range.style.top = '8%';
    range.style.height = '84%';
    return range;
}

describe('Handy visualizer tracking', () => {
    let originalFetch;
    let originalDateNow;

    beforeEach(() => {
        originalFetch = globalThis.fetch;
        originalDateNow = Date.now;
        [
            'handy-cylinder-range',
            'handy-cylinder-position',
            'motion-speed-meter-fill',
            'motion-speed-meter-value',
            'motion-depth-meter-fill',
            'motion-depth-meter-value',
            'motion-sequence-indicator',
            'motion-diagnostics-panel',
            'handy-key-status',
            'sidebar-handy-key-status',
            'handy-key-input',
            'sidebar-handy-key-input',
            'active-mode-status',
            'active-mode-label',
            'edging-timer',
            'mood-display',
            'im-close-btn',
        ].forEach(resetStubElement);
        state.motionDiagnosticsLevel = 'compact';
        state.motionObservability = null;
        state.myHandyKey = '';
        state.activeModeName = '';
        state.activeModeElapsedSeconds = null;
        state.connectionLost = false;
        primeStaticTrack();
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        Date.now = originalDateNow;
    });

    it('tracks continuous sampled output between status polls', async () => {
        Date.now = () => 2_000_000;
        globalThis.fetch = async () => jsonResponse(200, {
            mood: 'Curious',
            active_mode: 'milking',
            active_mode_elapsed_seconds: 4,
            active_mode_paused: false,
            motion_paused: false,
            motion_observability: continuousPayload(),
        });

        await pollMotionStatus();

        const position = getStubElement('handy-cylinder-position');
        const range = getStubElement('handy-cylinder-range');
        assert.equal(state.motionObservability.received_at, 2000);
        assert.equal(range.style.top, '8%');
        assert.equal(range.style.height, '84%');
        assert.equal(position.style.top, '12%');

        Date.now = () => 2_000_160;
        updateMotionObservability(state.motionObservability);

        assert.equal(position.style.top, '88%');
        assert.equal(range.style.top, '8%');
        assert.equal(range.style.height, '84%');
    });

    it('does not replay stale continuous trace windows as live motion', () => {
        Date.now = () => 5_000_000;
        const payload = continuousPayload({
            received_at: 5000,
            last_command_time: 4990,
        });

        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '88%');
        assert.equal(getStubElement('handy-cylinder-range').style.top, '8%');
        assert.equal(getStubElement('handy-cylinder-range').style.height, '84%');
    });

    it('tracks HSP from reported firmware time and output depth', () => {
        Date.now = () => 10_000;
        const payload = continuousPayload({
            received_at: 10,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hamp_started: false,
                hsp_streaming: true,
                hsp_state_observed_at: 10,
                hsp_state_age_ms: 0,
                hsp_state: {
                    play_state: 'playing',
                    current_time_ms: 1000,
                    playback_rate: 1,
                },
            },
            trace: [
                {
                    t: 9990,
                    hsp_point_time_ms: 1000,
                    depth: 85,
                    output_depth: 15,
                    continuous: true,
                    continuous_schema: 'hsp',
                    program_range: {min: 8, max: 92},
                },
                {
                    t: 9991,
                    hsp_point_time_ms: 1100,
                    depth: 55,
                    output_depth: 45,
                    continuous: true,
                    continuous_schema: 'hsp',
                    program_range: {min: 8, max: 92},
                },
            ],
        });

        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '15%');

        Date.now = () => 10_050;
        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '30%');
    });

    it('does not extrapolate stale HSP state beyond the trace clock', () => {
        Date.now = () => 50_050;
        const payload = continuousPayload({
            received_at: 50,
            snapshot_time: 150,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hamp_started: false,
                hsp_streaming: true,
                hsp_state_age_ms: 1500,
                hsp_state: {
                    play_state: 'playing',
                    current_time_ms: 5000,
                    playback_rate: 1,
                },
            },
            trace: [
                {t: 150.00, hsp_point_time_ms: 1000, output_depth: 20, continuous: true, continuous_schema: 'hsp'},
                {t: 150.10, hsp_point_time_ms: 1100, output_depth: 80, continuous: true, continuous_schema: 'hsp'},
            ],
        });

        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '50%');
    });

    it('treats Handy enum-style HSP playing states as advancing', () => {
        Date.now = () => 20_000;
        const payload = continuousPayload({
            received_at: 20,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hsp_streaming: true,
                hsp_state_age_ms: 0,
                hsp_state: {
                    play_state: 'HSP_STATE_PLAYING',
                    current_time_ms: 1000,
                    playback_rate: 1,
                },
            },
            trace: [
                {t: 19990, hsp_point_time_ms: 1000, depth: 20, output_depth: 20, continuous: true, continuous_schema: 'hsp'},
                {t: 19991, hsp_point_time_ms: 1100, depth: 80, output_depth: 80, continuous: true, continuous_schema: 'hsp'},
            ],
        });

        Date.now = () => 20_050;
        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '50%');
    });

    it('accepts camelCase HSP playbackRate while extrapolating firmware time', () => {
        Date.now = () => 25_000;
        const payload = continuousPayload({
            received_at: 25,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hsp_streaming: true,
                hsp_state_age_ms: 0,
                hsp_state: {
                    play_state: 'playing',
                    current_time_ms: 1000,
                    playbackRate: 2,
                },
            },
            trace: [
                {t: 24990, hsp_point_time_ms: 1000, depth: 20, output_depth: 20, continuous: true, continuous_schema: 'hsp'},
                {t: 24991, hsp_point_time_ms: 1100, depth: 80, output_depth: 80, continuous: true, continuous_schema: 'hsp'},
            ],
        });

        Date.now = () => 25_050;
        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '80%');
    });

    it('shows the active visualizer clock source in debug diagnostics', () => {
        Date.now = () => 26_000;
        state.motionDiagnosticsLevel = 'debug';
        const payload = continuousPayload({
            diagnostics_level: 'debug',
            received_at: 26,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hsp_streaming: true,
                hsp_state_age_ms: 120,
                hsp_state: {
                    play_state: 'HSP_STATE_PLAYING',
                    current_time_ms: 1000,
                    playback_rate: 1,
                },
            },
            trace: [
                {t: 25990, hsp_point_time_ms: 1000, depth: 20, output_depth: 20, continuous: true, continuous_schema: 'hsp'},
                {t: 25991, hsp_point_time_ms: 1100, depth: 80, output_depth: 80, continuous: true, continuous_schema: 'hsp'},
            ],
        });

        Date.now = () => 26_050;
        updateMotionObservability(payload);

        const debugText = getStubElement('motion-diagnostics-panel').textContent;
        assert.match(debugText, /Visualizer hsp-state/);
        assert.match(debugText, /clock 1170ms/);
        assert.match(debugText, /state age 120ms/);
    });

    it('falls back to planned continuous animation when HSP clock is outside the trace window', () => {
        Date.now = () => 30_000;
        const payload = continuousPayload({
            received_at: 30,
            snapshot_time: 30,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hsp_streaming: true,
                hsp_state_age_ms: 0,
                hsp_state: {
                    play_state: 'playing',
                    current_time_ms: 6000,
                    playback_rate: 1,
                },
            },
            trace: [
                {t: 30.00, hsp_point_time_ms: 1000, depth: 20, output_depth: 20, continuous: true, continuous_schema: 'hsp'},
                {t: 30.10, hsp_point_time_ms: 1100, depth: 80, output_depth: 80, continuous: true, continuous_schema: 'hsp'},
            ],
        });

        Date.now = () => 30_050;
        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '50%');
    });

    it('uses scheduled HSP wall times when firmware time is before the visible trace window', () => {
        Date.now = () => 40_050;
        const payload = continuousPayload({
            received_at: 40,
            snapshot_time: 140,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 60,
                depth: 50,
                physical_depth: 50,
                range: 60,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 110,
                hsp_streaming: true,
                hsp_state_age_ms: 0,
                hsp_state: {
                    play_state: 'playing',
                    current_time_ms: 1000,
                    playback_rate: 1,
                },
            },
            trace: [
                {t: 140.00, hsp_point_time_ms: 5000, depth: 20, output_depth: 20, continuous: true, continuous_schema: 'hsp'},
                {t: 140.10, hsp_point_time_ms: 5100, depth: 80, output_depth: 80, continuous: true, continuous_schema: 'hsp'},
            ],
        });

        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '50%');

        Date.now = () => 40_100;
        updateMotionObservability(payload);

        assert.equal(getStubElement('handy-cylinder-position').style.top, '80%');
    });

    it('keeps the static track fixed during finite position playback', () => {
        Date.now = () => 3_000_000;

        const payload = {
            backend: 'position',
            playback_active: true,
            last_command_time: 3000,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 50,
                depth: 30,
                physical_depth: 30,
                range: 40,
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 100,
            },
            trace: [
                {t: 2999.90, depth: 20, speed: 50, physical_speed: 50, frame_index: 0, frame_count: 2, program_range: {min: 20, max: 70}},
                {t: 3000.00, depth: 70, speed: 50, physical_speed: 50, frame_index: 1, frame_count: 2, program_range: {min: 20, max: 70}},
            ],
        };
        updateMotionObservability(payload);

        const range = getStubElement('handy-cylinder-range');
        assert.equal(range.style.top, '8%');
        assert.equal(range.style.height, '84%');
        assert.equal(getStubElement('handy-cylinder-position').style.top, '20%');

        Date.now = () => 3_001_000;
        updateMotionObservability(payload);

        assert.equal(range.style.top, '8%');
        assert.equal(range.style.height, '84%');
        assert.equal(getStubElement('handy-cylinder-position').style.top, '70%');
    });

    it('maps HAMP legacy motion to a phase estimate without moving the static track', () => {
        Date.now = () => 4_000_500;

        updateMotionObservability({
            backend: 'hamp',
            playback_active: true,
            last_command_time: 4000,
            diagnostics: {
                relative_speed: 50,
                physical_speed: 55,
                depth: 50,
                physical_depth: 50,
                range: 50,
                stroke_zone: {min: 25, max: 75},
                calibrated_range: {min: 0, max: 100},
                full_travel_mm: 100,
                hamp_started: true,
            },
            trace: [],
        });

        const range = getStubElement('handy-cylinder-range');
        assert.equal(range.style.top, '8%');
        assert.equal(range.style.height, '84%');
        assert.notEqual(getStubElement('handy-cylinder-position').style.top, '50%');
    });

    it('mirrors Handy connection status below the visualizer', () => {
        state.myHandyKey = 'saved-key';

        updateMotionObservability({
            backend: 'continuous',
            diagnostics: {
                relative_speed: 0,
                depth: 50,
                last_command: {
                    path: 'hdsp/xava',
                    ok: false,
                    status_code: 503,
                    error: 'device offline',
                },
            },
        });

        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Device offline');
        assert.equal(getStubElement('handy-key-status').textContent, 'Device offline');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--red-hover)');
        assert.equal(getStubElement('sidebar-handy-key-status').title, 'Handy hdsp/xava 503 failed: device offline');

        updateMotionObservability({
            backend: 'continuous',
            diagnostics: {
                relative_speed: 0,
                depth: 50,
                last_command: {
                    path: 'hamp/velocity',
                    ok: true,
                    status_code: 204,
                },
            },
        });

        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Command OK');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--green)');
        assert.equal(
            getStubElement('sidebar-handy-key-status').title,
            'Last Handy hamp/velocity command succeeded; no live device status event yet.',
        );
    });

    it('prefers live Handy device status over stale successful commands', () => {
        state.myHandyKey = 'saved-key';

        updateMotionObservability({
            backend: 'continuous',
            diagnostics: {
                relative_speed: 0,
                depth: 50,
                device_connection_status: 'offline',
                device_connection_message: 'Device disconnected',
                last_command: {
                    path: 'hsp/add',
                    ok: true,
                    status_code: 200,
                },
            },
        });

        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Device offline');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--red-hover)');
        assert.equal(getStubElement('sidebar-handy-key-status').title, 'Device disconnected');

        updateMotionObservability({
            backend: 'continuous',
            diagnostics: {
                relative_speed: 0,
                depth: 50,
                device_connection_status: 'online',
                device_connection_message: 'Device connected',
                last_command: {
                    path: 'hsp/add',
                    ok: true,
                    status_code: 200,
                },
            },
        });

        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Device online');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--green)');
        assert.equal(getStubElement('sidebar-handy-key-status').title, 'Device connected');
    });
});
