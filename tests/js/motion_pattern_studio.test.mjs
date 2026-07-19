import { describe, it } from 'node:test';
import assert from 'node:assert';

import {
    createBlankStudioPattern,
    cropPatternToWindow,
    drawPatternPreviewCanvas,
    patternFromImportPayload,
    segmentIntensity,
    simplifyDrawnActions,
    smoothEditedPattern,
    STUDIO_EDIT_HIT_TOLERANCE_PX,
    STUDIO_MAX_ACTIONS,
    studioActionAtPixel,
    studioActionFromPixel,
    studioCanDeleteActionAt,
    studioCropPreviewPayload,
    studioDeleteActionAt,
    studioInsertSortedAction,
    studioMoveActionAt,
    setMotionTrainingDetail,
    timelineIntensityColor,
} from '../../static/js/motion/training-editor.js';
import { el, state } from '../../static/js/context.js';
import { patternMatchesQuery, patternPreviewPath } from '../../static/js/motion/pattern-list.js';

function studioMetrics(actions, width = 400, height = 200) {
    const pad = 34;
    const start = actions[0].at;
    const end = actions[actions.length - 1].at;
    const duration = Math.max(1, end - start);
    return {
        pad,
        start,
        end,
        duration,
        width,
        height,
        innerWidth: width - pad * 2,
        innerHeight: height - pad * 2,
    };
}

function stubCanvas(canvas, width = 400, height = 220) {
    canvas.getBoundingClientRect = () => ({top: 0, left: 0, right: width, bottom: height, width, height});
    const context = {
        bezierCurveCalls: 0,
        lineToCalls: 0,
        clipCalls: 0,
        rectCalls: [],
        beginPath() {},
        arc() {},
        bezierCurveTo() { this.bezierCurveCalls += 1; },
        clearRect() {},
        clip() { this.clipCalls += 1; },
        fill() {},
        fillRect() {},
        fillText() {},
        lineTo() { this.lineToCalls += 1; },
        moveTo() {},
        rect(x, y, rectWidth, rectHeight) { this.rectCalls.push({x, y, width: rectWidth, height: rectHeight}); },
        restore() {},
        save() {},
        stroke() {},
        setTransform(...args) { this.transform = args; },
        set fillStyle(_value) {},
        set font(_value) {},
        set lineWidth(_value) {},
        set strokeStyle(_value) {},
        set textAlign(_value) {},
    };
    canvas.__testContext = context;
    canvas.getContext = () => context;
}

describe('motion pattern studio helpers', () => {
    it('imports a funscript as a rebased editable pattern', () => {
        const pattern = patternFromImportPayload({
            actions: [
                { at: 1200, pos: 12 },
                { at: 2400, pos: 88 },
            ],
        }, 'sample-loop.funscript');

        assert.strictEqual(pattern.name, 'sample-loop');
        assert.strictEqual(pattern.duration_ms, 1200);
        assert.strictEqual(pattern.action_count, 2);
        assert.deepStrictEqual(pattern.actions, [
            { at: 0, pos: 12 },
            { at: 1200, pos: 88 },
        ]);
        assert.ok(pattern.tags.includes('funscript'));
    });

    it('crops a timeline window with interpolated endpoints and rebased timing', () => {
        const cropped = cropPatternToWindow({
            id: 'wave',
            name: 'Wave',
            actions: [
                { at: 0, pos: 0 },
                { at: 1000, pos: 100 },
                { at: 2000, pos: 0 },
                { at: 3000, pos: 100 },
            ],
        }, 500, 2500);

        assert.strictEqual(cropped.duration_ms, 2000);
        assert.deepStrictEqual(cropped.actions.map(action => action.at), [0, 500, 1500, 2000]);
        assert.strictEqual(cropped.actions[0].pos, 50);
        assert.strictEqual(cropped.actions[cropped.actions.length - 1].pos, 50);
    });

    it('caps very dense imported crops to the studio action limit', () => {
        const actions = [];
        for (let i = 0; i <= STUDIO_MAX_ACTIONS + 50; i++) {
            actions.push({ at: i * 10, pos: i % 100 });
        }

        const cropped = cropPatternToWindow({ name: 'Dense', actions }, 0, actions[actions.length - 1].at);

        assert.ok(cropped.actions.length <= STUDIO_MAX_ACTIONS);
        assert.strictEqual(cropped.actions[0].at, 0);
        assert.strictEqual(cropped.actions[cropped.actions.length - 1].at, actions[actions.length - 1].at);
    });

    it('creates a flat blank pattern for drawing', () => {
        const pattern = createBlankStudioPattern(4200);

        assert.strictEqual(pattern.name, 'Drawn Pattern');
        assert.strictEqual(pattern.duration_ms, 4200);
        assert.deepStrictEqual(pattern.actions, [
            { at: 0, pos: 50 },
            { at: 4200, pos: 50 },
        ]);
        assert.strictEqual(pattern.style.interpolation, 'cubic');
        assert.strictEqual(pattern.style.interpolation_ms, 80);
        assert.ok(pattern.tags.includes('drawn'));
    });

    it('simplifies dense drawn gestures into sparse editable controls', () => {
        const dense = [];
        for (let i = 0; i <= 120; i++) {
            const phase = (i / 120) * Math.PI * 2;
            dense.push({
                at: i * 50,
                pos: 50 + (Math.sin(phase) * 36) + (Math.sin(phase * 11) * 1.2),
            });
        }

        const simplified = simplifyDrawnActions(dense, {epsilon: 2.7, maxPoints: 24, minSpacingMs: 110});

        assert.ok(simplified.length <= 24);
        assert.strictEqual(simplified[0].at, dense[0].at);
        assert.strictEqual(simplified[simplified.length - 1].at, dense[dense.length - 1].at);
        assert.ok(simplified.some(action => action.pos > 82));
        assert.ok(simplified.some(action => action.pos < 18));
    });

    it('scales the default drawn control budget with pattern duration', () => {
        const dense = [];
        for (let i = 0; i <= 240; i++) {
            dense.push({
                at: i * 100,
                pos: 50 + Math.sin((i / 240) * Math.PI * 12) * 35,
            });
        }

        const simplified = simplifyDrawnActions(dense);

        // Medium detail allows roughly 4.5 controls/second, capped by
        // simplification when the curve needs fewer points.
        assert.ok(simplified.length <= 100);
        assert.ok(simplified.length >= 13);
    });

    it('preserves every direction reversal while simplifying', () => {
        const zigzag = [50, 51, 50, 51, 50].map((pos, index) => ({at: index * 100, pos}));

        assert.throws(
            () => simplifyDrawnActions(zigzag, {epsilon: 100, maxPoints: 2, minSpacingMs: 0}),
            /essential reversal points/,
        );
        const simplified = simplifyDrawnActions(zigzag, {epsilon: 100, maxPoints: 5, minSpacingMs: 0});

        assert.deepStrictEqual(simplified, zigzag);
    });

    it('renders preview actions as a monotone cubic path matching backend sampling', () => {
        const canvas = el.motionTrainingPreviewCanvas;
        stubCanvas(canvas);

        drawPatternPreviewCanvas(canvas, {
            actions: [
                { at: 0, pos: 20 },
                { at: 1000, pos: 80 },
                { at: 2000, pos: 20 },
            ],
        }, 'Empty');

        // The preview now uses the same Fritsch-Carlson monotone cubic as the
        // backend, drawn as dense line segments instead of overshooting
        // Catmull-Rom beziers, so the graph matches device output.
        assert.ok(canvas.__testContext.lineToCalls > 0, 'expected monotone line segments');
        assert.strictEqual(canvas.__testContext.bezierCurveCalls, 0);
        assert.strictEqual(canvas.__testContext.clipCalls, 1);
        assert.deepStrictEqual(canvas.__testContext.rectCalls.at(-1), {x: 34, y: 34, width: 332, height: 152});
    });

    it('renders preview canvases at device pixel density', () => {
        const canvas = el.motionTrainingPreviewCanvas;
        stubCanvas(canvas);
        const previousRatio = window.devicePixelRatio;
        window.devicePixelRatio = 2;

        drawPatternPreviewCanvas(canvas, {actions: [{at: 0, pos: 20}, {at: 1000, pos: 80}]}, 'Empty');

        assert.strictEqual(canvas.width, 800);
        assert.strictEqual(canvas.height, 440);
        assert.deepStrictEqual(canvas.__testContext.transform, [2, 0, 0, 2, 0, 0]);
        window.devicePixelRatio = previousRatio;
    });

    it('builds catalog curves from backend samples and searches metadata', () => {
        const pattern = {
            id: 'pulse',
            name: 'Pulse',
            description: 'Alternating deep and shorter peaks.',
            tags: ['rhythmic', 'varied'],
            preview_samples: [{at: 0, pos: 15}, {at: 500, pos: 100}, {at: 1000, pos: 15}],
        };

        const path = patternPreviewPath(pattern);
        assert.match(path, /^M/);
        assert.match(path, / L/);
        assert.strictEqual(patternMatchesQuery(pattern, 'shorter'), true);
        assert.strictEqual(patternMatchesQuery(pattern, 'rhythmic'), true);
        assert.strictEqual(patternMatchesQuery(pattern, 'stroke'), false);
    });

    it('smooths sparse controls without flattening peaks and troughs', () => {
        stubCanvas(el.motionTrainingOriginalPreviewCanvas);
        stubCanvas(el.motionTrainingPreviewCanvas);
        stubCanvas(el.motionStudioCropCanvas);
        state.motionTrainingEditedPattern = {
            id: 'sparse-wave',
            name: 'Sparse Wave',
            actions: [
                { at: 0, pos: 50 },
                { at: 1000, pos: 96 },
                { at: 2000, pos: 4 },
                { at: 3000, pos: 96 },
                { at: 4000, pos: 50 },
            ],
        };
        state.motionTrainingDirty = false;

        smoothEditedPattern();

        const actions = state.motionTrainingEditedPattern.actions;
        const positions = actions.map(action => action.pos);
        assert.strictEqual(actions.length, 5);
        assert.strictEqual(actions[0].pos, 50);
        assert.strictEqual(actions[actions.length - 1].pos, 50);
        assert.ok(Math.max(...positions) > 90, positions);
        assert.ok(Math.min(...positions) < 10, positions);
        assert.strictEqual(state.motionTrainingDirty, true);

        state.motionTrainingEditedPattern = null;
        state.motionTrainingPreviewPattern = null;
        state.motionTrainingDirty = false;
    });

    it('maps faster motion segments to hotter timeline colors', () => {
        const slow = segmentIntensity({ at: 0, pos: 45 }, { at: 2000, pos: 55 });
        const fast = segmentIntensity({ at: 0, pos: 0 }, { at: 200, pos: 100 });

        assert.ok(slow < fast);
        assert.ok(fast <= 1);
        assert.strictEqual(timelineIntensityColor(0), 'rgba(127, 183, 163, 0.96)');
        assert.strictEqual(timelineIntensityColor(1, 0.5), 'rgba(255, 85, 85, 0.5)');
    });

    it('builds the current unsaved crop preview without mutating the edited pattern', () => {
        state.motionStudioSourcePattern = {
            id: 'imported-wave',
            name: 'Imported Wave',
            actions: [
                { at: 0, pos: 0 },
                { at: 1000, pos: 100 },
                { at: 2000, pos: 0 },
            ],
        };
        state.motionStudioCropStartMs = 500;
        state.motionStudioCropEndMs = 1500;
        state.motionTrainingEditedPattern = { id: 'existing-edit', actions: [{ at: 0, pos: 50 }, { at: 1000, pos: 50 }] };

        const payload = studioCropPreviewPayload();

        assert.strictEqual(payload.name, 'Imported Wave 0.5-1.5s crop');
        assert.strictEqual(payload.duration_ms, 1000);
        assert.deepStrictEqual(payload.actions.map(action => action.at), [0, 500, 1000]);
        assert.deepStrictEqual(state.motionTrainingEditedPattern.actions, [{ at: 0, pos: 50 }, { at: 1000, pos: 50 }]);

        state.motionStudioSourcePattern = null;
        state.motionStudioCropStartMs = 0;
        state.motionStudioCropEndMs = 0;
        state.motionTrainingEditedPattern = null;
    });
});

describe('motion pattern studio edit-tool helpers', () => {
    const actions = [
        { at: 0, pos: 20 },
        { at: 1000, pos: 80 },
        { at: 2000, pos: 20 },
    ];
    const metrics = studioMetrics(actions);

    it('returns the closest point index when the cursor is within tolerance', () => {
        // Mid action sits at the midpoint of the inner width, on a curve
        // top high enough that pixel y maps to pos 80.
        const midX = metrics.pad + metrics.innerWidth / 2;
        const midY = metrics.pad + ((100 - 80) / 100) * metrics.innerHeight;
        assert.strictEqual(studioActionAtPixel(actions, midX, midY, metrics), 1);
    });

    it('returns -1 when the cursor is outside the hit tolerance ring', () => {
        const midX = metrics.pad + metrics.innerWidth / 2;
        const midY = metrics.pad + ((100 - 80) / 100) * metrics.innerHeight;
        assert.strictEqual(
            studioActionAtPixel(actions, midX + STUDIO_EDIT_HIT_TOLERANCE_PX + 4, midY, metrics),
            -1,
        );
    });

    it('inserts a new point and keeps the action list sorted by `at`', () => {
        const next = studioInsertSortedAction(actions, { at: 1500, pos: 50 });

        assert.strictEqual(next.length, actions.length + 1);
        assert.deepStrictEqual(next.map(a => a.at), [0, 1000, 1500, 2000]);
        assert.strictEqual(next[2].pos, 50);
    });

    it('refuses to delete the start or end anchor and preserves cycle duration', () => {
        // Interior point goes away cleanly.
        const trimmed = studioDeleteActionAt(actions, 1);
        assert.deepStrictEqual(trimmed.map(a => a.at), [0, 2000]);
        assert.strictEqual(studioCanDeleteActionAt(actions, 1), true);

        // First and last anchors are protected so cycle duration / start
        // pos stay stable.
        assert.strictEqual(studioCanDeleteActionAt(actions, 0), false);
        assert.strictEqual(studioCanDeleteActionAt(actions, actions.length - 1), false);
        assert.strictEqual(studioDeleteActionAt(actions, 0), actions);
        assert.strictEqual(studioDeleteActionAt(actions, actions.length - 1), actions);

        // Patterns with only the two anchors have nothing safe to remove.
        const onlyAnchors = [{ at: 0, pos: 50 }, { at: 1000, pos: 50 }];
        assert.strictEqual(studioCanDeleteActionAt(onlyAnchors, 0), false);
        assert.strictEqual(studioDeleteActionAt(onlyAnchors, 0), onlyAnchors);
    });

    it('clamps a dragged interior point between its neighbors', () => {
        // Try to drag the middle point past the right neighbor.
        const moved = studioMoveActionAt(actions, 1, 5000, 95);

        // `at` is clamped to one ms below the next neighbor.
        assert.strictEqual(moved[1].at, 1999);
        assert.strictEqual(moved[1].pos, 95);

        // Original list is untouched.
        assert.strictEqual(actions[1].at, 1000);
    });

    it('keeps endpoint anchors at their authored `at` while letting pos follow the drag', () => {
        const moved = studioMoveActionAt(actions, 0, 500, 10);
        assert.strictEqual(moved[0].at, 0);
        assert.strictEqual(moved[0].pos, 10);

        const movedEnd = studioMoveActionAt(actions, 2, 5000, 90);
        assert.strictEqual(movedEnd[2].at, 2000);
        assert.strictEqual(movedEnd[2].pos, 90);
    });

    it('reverse-projects a pixel coordinate back into an action', () => {
        const action = studioActionFromPixel(
            metrics.pad + metrics.innerWidth / 4,
            metrics.pad + metrics.innerHeight / 2,
            metrics,
        );

        // Quarter across the inner width maps to a quarter of the cycle.
        assert.strictEqual(action.at, Math.round(metrics.duration / 4));
        // Half the inner height maps to pos 50 (top of canvas = pos 100).
        assert.strictEqual(action.pos, 50);
    });

    it('clamps pixels outside the graph to the valid pattern bounds', () => {
        const highLeft = studioActionFromPixel(metrics.pad - 80, metrics.pad - 40, metrics);
        const lowRight = studioActionFromPixel(
            metrics.width - metrics.pad + 80,
            metrics.height - metrics.pad + 40,
            metrics,
        );

        assert.deepStrictEqual(highLeft, {at: 0, pos: 100});
        assert.deepStrictEqual(lowRight, {at: metrics.duration, pos: 0});
    });

    it('opens edit and draw tools for existing library patterns', () => {
        stubCanvas(el.motionTrainingPreviewCanvas);
        stubCanvas(el.motionTrainingOriginalPreviewCanvas);
        stubCanvas(el.motionStudioCropCanvas);

        setMotionTrainingDetail({
            id: 'library-wave',
            name: 'Library Wave',
            actions: [
                { at: 0, pos: 20 },
                { at: 1000, pos: 80 },
                { at: 2000, pos: 20 },
            ],
        });

        assert.strictEqual(state.motionStudioFlow, 'edit');
        assert.strictEqual(state.motionStudioTool, 'edit');
        assert.strictEqual(el.motionStudioPanel.hidden, false);
        assert.strictEqual(el.motionStudioDrawControls.hidden, false);
        assert.strictEqual(el.motionStudioToolEditBtn.disabled, false);
        assert.strictEqual(el.motionStudioToolDrawBtn.disabled, false);

        el.motionStudioPanel.hidden = true;
        el.motionStudioDrawControls.hidden = true;
        state.motionStudioFlow = '';
        state.motionStudioTool = 'edit';
        state.motionStudioSelectedPointIndex = -1;
        state.motionStudioDragPointIndex = -1;
        state.motionTrainingOriginalPattern = null;
        state.motionTrainingEditedPattern = null;
        state.motionTrainingPreviewPattern = null;
    });
});
