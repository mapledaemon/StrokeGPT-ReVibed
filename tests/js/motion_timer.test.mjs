// Backlog #13 proof-of-runner test.
//
// Spec (ROADMAP "Frontend Test Runner For Behavioral JavaScript Tests"):
// "Add a small initial proof: a behavioral test for `updateActiveModeTimer`
// that drives stop -> idle -> new-mode transitions through the function and
// asserts the sequence-log DOM holds frozen timecodes after stop and resets
// to `00:00` only on the mode-start transition.
//
// This test imports the real production ES modules, drives the actual
// updateActiveModeTimer + updateMotionSequenceIndicator code paths, and
// inspects the DOM that the production code mutates. It replaces the older
// source-text assertions for this bug; the behavior matters more than the
// exact branch shape inside motion-control.js.

import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { updateActiveModeTimer } from '../../static/js/motion-control.js';
import {
    updateMotionSequenceIndicator,
    resetMotionSequenceLog,
} from '../../static/js/motion/sequence-log.js';
import { state } from '../../static/js/context.js';


function findMotionSequenceEntries(indicator) {
    return indicator.children.filter(
        c => c && c.className && c.className.includes('motion-sequence-entry'),
    );
}

function timeSpanFor(entry) {
    return entry.children.find(c => c && c.className === 'motion-sequence-time');
}


describe('updateActiveModeTimer + sequence log (Backlog #13 proof test)', () => {
    beforeEach(() => {
        // Reset the bits of state we touch. The `el` bindings in
        // context.js are frozen at module load; what we can reset is the
        // mutable contents of the stub elements those bindings point at.
        state.activeModeName = '';
        state.activeModeElapsedSeconds = null;
        state.motionPaused = false;
        state.motionDiagnosticsLevel = 'compact';
        state.motionBackend = 'hamp';
        resetStubElement('active-mode-status');
        resetStubElement('active-mode-label');
        resetStubElement('edging-timer');
        resetStubElement('motion-sequence-indicator');
        resetMotionSequenceLog();
    });

    it('seeds elapsed seconds when a mode starts from idle', () => {
        updateActiveModeTimer('auto', 0, false);
        assert.strictEqual(state.activeModeName, 'auto');
        assert.strictEqual(state.activeModeElapsedSeconds, 0);
    });

    it('advances elapsed while a mode runs', () => {
        updateActiveModeTimer('auto', 0, false);
        updateActiveModeTimer('auto', 42, false);
        assert.strictEqual(state.activeModeElapsedSeconds, 42);
    });

    it('renders mode label and timer as separate fixed chips', () => {
        updateActiveModeTimer('freestyle', 42, false);

        const status = getStubElement('active-mode-status');
        const label = getStubElement('active-mode-label');
        const timer = getStubElement('edging-timer');

        assert.strictEqual(status.hidden, false);
        assert.strictEqual(label.textContent, 'Freestyle');
        assert.strictEqual(timer.textContent, '00:42');
        assert.strictEqual(
            timer.textContent.includes('Freestyle'),
            false,
            'the timer chip should not include the mode label',
        );
    });

    it('freezes elapsed seconds on stop instead of resetting to null/00:00', () => {
        updateActiveModeTimer('auto', 0, false);
        updateActiveModeTimer('auto', 42, false);

        // Stop the mode.
        updateActiveModeTimer('', null, false);

        assert.strictEqual(state.activeModeName, '', 'mode name clears on stop');
        assert.strictEqual(
            state.activeModeElapsedSeconds,
            42,
            'elapsed must stay frozen at the last value, not be nulled or zeroed',
        );

        // Hidden, but the bug-relevant state is the cached elapsed.
        const status = getStubElement('active-mode-status');
        assert.strictEqual(status.hidden, true);
    });

    it('keeps post-stop sequence-log entries on the frozen elapsed timecode', () => {
        // Run a mode for 42s, then stop. The next motion observability poll
        // (idle device frame) should append a sequence-log entry whose
        // timecode reads the frozen elapsed (00:42), NOT 00:00.
        updateActiveModeTimer('auto', 0, false);
        updateActiveModeTimer('auto', 42, false);
        updateActiveModeTimer('', null, false);

        updateMotionSequenceIndicator({
            source: 'idle',
            backend: 'hamp',
            playback_active: false,
            trace: [{ label: 'Idle', source: 'idle' }],
            diagnostics: {},
        });

        const indicator = getStubElement('motion-sequence-indicator');
        const entries = findMotionSequenceEntries(indicator);
        assert.ok(entries.length >= 1, 'sequence log received at least one entry after stop');

        const lastTime = timeSpanFor(entries.at(-1));
        assert.ok(lastTime, 'the post-stop entry has a motion-sequence-time span');
        assert.strictEqual(
            lastTime.textContent,
            '00:42',
            'post-stop entry timecode must read the frozen elapsed (00:42), not 00:00',
        );
    });

    it('resets elapsed and clears the sequence log on a new mode start', () => {
        updateActiveModeTimer('auto', 0, false);
        updateActiveModeTimer('auto', 42, false);

        // Push at least one entry so we can verify the log gets cleared.
        updateMotionSequenceIndicator({
            source: 'auto',
            backend: 'hamp',
            playback_active: true,
            trace: [{ label: 'Stroke', source: 'auto' }],
            diagnostics: {},
        });
        updateActiveModeTimer('', null, false);

        const indicator = getStubElement('motion-sequence-indicator');
        const entriesBefore = findMotionSequenceEntries(indicator);
        assert.ok(
            entriesBefore.length >= 1,
            'log had at least one entry before starting a new mode',
        );

        // Start a new mode. timerStarted should fire and reset both the
        // elapsed counter and the sequence log.
        updateActiveModeTimer('milking', 0, false);

        assert.strictEqual(state.activeModeName, 'milking');
        assert.strictEqual(
            state.activeModeElapsedSeconds,
            0,
            'elapsed resets to 0 when a new mode starts',
        );

        const remaining = findMotionSequenceEntries(indicator);
        assert.deepStrictEqual(
            remaining,
            [],
            'sequence log clears on a new mode start (resetMotionSequenceLog ran)',
        );
    });

    it('treats a same-mode restart (elapsed drops back to 0) as a new mode start', () => {
        // Some backend paths restart the same mode without emitting a
        // stop event in between. The detection looks for nextElapsed <= 1
        // while previousElapsed > 2 with the same mode name. The log
        // should still reset.
        updateActiveModeTimer('auto', 0, false);
        updateActiveModeTimer('auto', 30, false);

        updateMotionSequenceIndicator({
            source: 'auto',
            backend: 'hamp',
            playback_active: true,
            trace: [{ label: 'Stroke', source: 'auto' }],
            diagnostics: {},
        });
        const indicator = getStubElement('motion-sequence-indicator');
        assert.ok(
            findMotionSequenceEntries(indicator).length >= 1,
            'log had an entry before the restart',
        );

        // Backend restarts the same mode; elapsed drops back near 0.
        updateActiveModeTimer('auto', 0, false);
        assert.strictEqual(state.activeModeElapsedSeconds, 0);
        assert.deepStrictEqual(
            findMotionSequenceEntries(indicator),
            [],
            'same-mode restart with elapsed back near 0 also clears the log',
        );
    });
});
