import { afterEach, beforeEach, describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { resetStubElement } from './_harness.mjs';
import {
    bindMotionProgramPlayerControls,
    configureMotionProgramPlayer,
    openMotionProgramWindow,
    playSelectedMotionProgram,
    programSectionActions,
    programSectionBounds,
    programTimelineViewWindow,
    saveSelectedProgramSectionAsPattern,
    setMotionProgramTab,
} from '../../static/js/motion/program-player.js';
import { D, el, state } from '../../static/js/context.js';


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
        clone() { return factory(); },
    });
    return factory();
}


const program = {
    id: 'long-wave',
    name: 'Long Wave',
    source: 'imported',
    duration_ms: 60_000,
    action_count: 4,
    actions: [
        {at: 0, pos: 20},
        {at: 10_000, pos: 90},
        {at: 30_000, pos: 10},
        {at: 60_000, pos: 80},
    ],
};


describe('motion program player', () => {
    let originalFetch;

    beforeEach(() => {
        for (const id of [
            'motion-program-dialog',
            'motion-program-dialog-title',
            'motion-program-dialog-meta',
            'motion-program-player-status',
            'motion-program-playback-tab-btn',
            'motion-program-section-tab-btn',
            'motion-program-playback-panel',
            'motion-program-section-panel',
            'motion-program-range-timeline',
            'motion-program-timeline-canvas',
            'motion-program-section-selection',
            'motion-program-section-start-handle',
            'motion-program-section-end-handle',
            'motion-program-section-start',
            'motion-program-section-end',
            'motion-program-section-duration',
            'motion-program-section-name',
            'status-text',
        ]) resetStubElement(id);
        state.connectionLost = false;
        state.motionProgramSelected = null;
        state.motionProgramSectionStartMs = 0;
        state.motionProgramSectionEndMs = 0;
        state.motionProgramSectionDragHandle = '';
        state.motionProgramTimelineZoom = 1;
        state.motionProgramTimelineOffsetMs = 0;
        state.motionProgramActiveTab = 'playback';
        configureMotionProgramPlayer({renderMotionPatterns: null, updateMotionTrainingStatus: null});
        originalFetch = globalThis.fetch;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
    });

    it('clamps default and manual section bounds', () => {
        assert.deepEqual(programSectionBounds(program, undefined, undefined), {
            startMs: 0,
            endMs: 30_000,
            durationMs: 30_000,
        });
        assert.deepEqual(programSectionBounds(program, 59_980, 59_990), {
            startMs: 59_900,
            endMs: 60_000,
            durationMs: 100,
        });
    });

    it('builds a trimmed section preview with interpolated endpoints', () => {
        const actions = programSectionActions(program, 5_000, 20_000);

        assert.deepEqual(actions.map(action => action.at), [0, 5000, 15000]);
        assert.equal(actions[0].pos, 55);
        assert.equal(actions[1].pos, 90);
        assert.equal(actions[2].pos, 50);
    });

    it('opens a Program detail in the tabbed player window', async () => {
        globalThis.fetch = async endpoint => {
            assert.equal(endpoint, '/motion_programs/long-wave');
            return jsonResponse(200, {status: 'success', program});
        };

        const data = await openMotionProgramWindow('long-wave');

        assert.equal(data.status, 'success');
        assert.equal(state.motionProgramSelected.id, 'long-wave');
        assert.equal(el.motionProgramDialog.classList.contains('open'), true);
        assert.equal(el.motionProgramDialogTitle.textContent, 'Long Wave');
        assert.match(el.motionProgramDialogMeta.textContent, /1m duration/);
        assert.equal(el.motionProgramSectionEndInput.value, '30');
        assert.match(el.motionProgramSectionDuration.textContent, /30s selected/);

        setMotionProgramTab('section');
        assert.equal(el.motionProgramSectionTabBtn.getAttribute('aria-selected'), 'true');
        assert.equal(el.motionProgramSectionPanel.hidden, false);
        assert.equal(el.motionProgramSectionStartHandle.disabled, false);
        assert.equal(el.motionProgramSectionEndHandle.style.left, '50%');
    });

    it('updates the selected range from timeline pointer and keyboard input', () => {
        bindMotionProgramPlayerControls();
        state.motionProgramSelected = program;
        state.motionProgramSectionStartMs = 0;
        state.motionProgramSectionEndMs = 30_000;
        el.motionProgramRangeTimeline.getBoundingClientRect = () => ({left: 0, right: 600, width: 600, top: 0, bottom: 190, height: 190});

        el.motionProgramRangeTimeline.dispatchEvent('pointerdown', {
            target: el.motionProgramRangeTimeline,
            clientX: 450,
            preventDefault() {},
        });

        assert.equal(state.motionProgramSectionDragHandle, 'end');
        assert.equal(state.motionProgramSectionStartMs, 0);
        assert.equal(state.motionProgramSectionEndMs, 45_000);
        assert.equal(el.motionProgramSectionEndInput.value, '45');
        assert.equal(el.motionProgramSectionEndHandle.style.left, '75%');

        D.dispatchEvent({type: 'pointermove', clientX: 300, preventDefault() {}});
        assert.equal(state.motionProgramSectionEndMs, 30_000);

        D.dispatchEvent({type: 'pointerup'});
        assert.equal(state.motionProgramSectionDragHandle, '');

        el.motionProgramSectionStartHandle.dispatchEvent('keydown', {
            key: 'ArrowRight',
            shiftKey: true,
            preventDefault() {},
        });

        assert.equal(state.motionProgramSectionStartMs, 1_000);
        assert.equal(el.motionProgramSectionStartInput.value, '1');
        assert.equal(el.motionProgramSectionStartHandle.getAttribute('aria-valuenow'), '1');
    });

    it('zooms the Program timeline around the wheel cursor', () => {
        bindMotionProgramPlayerControls();
        state.motionProgramSelected = program;
        state.motionProgramSectionStartMs = 0;
        state.motionProgramSectionEndMs = 30_000;
        el.motionProgramRangeTimeline.getBoundingClientRect = () => ({left: 0, right: 600, width: 600, top: 0, bottom: 190, height: 190});

        let prevented = false;
        el.motionProgramRangeTimeline.dispatchEvent('wheel', {
            clientX: 300,
            deltaY: -100,
            preventDefault() { prevented = true; },
        });

        assert.equal(prevented, true);
        assert.equal(state.motionProgramTimelineZoom, 1.25);
        assert.equal(state.motionProgramTimelineOffsetMs, 6_000);
        assert.deepEqual(programTimelineViewWindow(program), {
            duration: 60_000,
            zoom: 1.25,
            viewStart: 6_000,
            viewEnd: 54_000,
            viewDuration: 48_000,
        });

        el.motionProgramRangeTimeline.dispatchEvent('pointerdown', {
            target: el.motionProgramRangeTimeline,
            clientX: 600,
            preventDefault() {},
        });
        assert.equal(state.motionProgramSectionEndMs, 54_000);
        assert.equal(el.motionProgramSectionEndHandle.style.left, '100%');
        assert.equal(el.motionProgramSectionSelection.style.left, '0%');
        assert.equal(el.motionProgramSectionSelection.style.width, '100%');

        el.motionProgramRangeTimeline.dispatchEvent('wheel', {
            clientX: 300,
            deltaY: 100,
            preventDefault() {},
        });
        assert.equal(state.motionProgramTimelineZoom, 1);
        assert.equal(state.motionProgramTimelineOffsetMs, 0);
    });

    it('plays the selected Program section through the Program route', async () => {
        const updates = [];
        const calls = [];
        state.motionProgramSelected = program;
        state.motionProgramSectionStartMs = 10_000;
        state.motionProgramSectionEndMs = 30_000;
        configureMotionProgramPlayer({updateMotionTrainingStatus: status => updates.push(status)});
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, options});
            return jsonResponse(200, {
                status: 'started',
                motion_training: {state: 'starting', message: 'Starting Long Wave section.', preview: true},
            });
        };

        const data = await playSelectedMotionProgram({full: false});

        assert.equal(data.status, 'started');
        assert.equal(calls[0].endpoint, '/motion_programs/long-wave/play');
        assert.equal(calls[0].options.method, 'POST');
        assert.deepEqual(JSON.parse(calls[0].options.body), {start_ms: 10000, end_ms: 30000});
        assert.equal(updates.length, 1);
        assert.equal(el.statusText.textContent, 'Starting Long Wave section.');
    });

    it('saves the selected Program section as a short pattern', async () => {
        const rendered = [];
        const calls = [];
        state.motionProgramSelected = program;
        state.motionProgramSectionStartMs = 10_000;
        state.motionProgramSectionEndMs = 30_000;
        el.motionProgramSectionNameInput.value = 'Wave Clip';
        configureMotionProgramPlayer({renderMotionPatterns: catalog => rendered.push(catalog)});
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, options});
            return jsonResponse(200, {
                status: 'success',
                message: 'Saved section as pattern: Wave Clip.',
                motion_patterns: {patterns: [{id: 'wave-clip'}], errors: []},
            });
        };

        const data = await saveSelectedProgramSectionAsPattern();

        assert.equal(data.status, 'success');
        assert.equal(calls[0].endpoint, '/motion_programs/long-wave/sections/save_pattern');
        assert.deepEqual(JSON.parse(calls[0].options.body), {
            start_ms: 10000,
            end_ms: 30000,
            name: 'Wave Clip',
        });
        assert.equal(rendered.length, 1);
        assert.equal(el.motionProgramSectionNameInput.value, '');
    });
});
