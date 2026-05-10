// Behavioral coverage for the sidebar Handy visualizer. The cylinder should
// map its green band to the active program/slide range and estimate the purple
// position line from the active backend's commanded motion output.

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

describe('Handy visualizer tracking', () => {
    let originalFetch;
    let originalDateNow;

    beforeEach(() => {
        originalFetch = globalThis.fetch;
        originalDateNow = Date.now;
        [
            'handy-cylinder-position',
            'motion-speed-meter-fill',
            'motion-speed-meter-value',
            'motion-depth-meter-fill',
            'motion-depth-meter-value',
            'motion-sequence-indicator',
            'motion-diagnostics-panel',
            'edging-timer',
            'mood-display',
            'im-close-btn',
        ].forEach(resetStubElement);
        state.motionDiagnosticsLevel = 'compact';
        state.motionObservability = null;
        state.activeModeName = '';
        state.activeModeElapsedSeconds = null;
        state.connectionLost = false;
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

    it('maps finite position playback to its program range', () => {
        Date.now = () => 3_000_000;

        updateMotionObservability({
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
        });

        const range = getStubElement('handy-cylinder-range');
        assert.equal(range.style.top, '20%');
        assert.equal(range.style.height, '50%');
    });

    it('maps HAMP legacy motion to the active slide window and phase estimate', () => {
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
        assert.equal(range.style.top, '25%');
        assert.equal(range.style.height, '50%');
        assert.notEqual(getStubElement('handy-cylinder-position').style.top, '50%');
    });
});
