import { describe, it } from 'node:test';
import assert from 'node:assert';

import {
    createBlankStudioPattern,
    cropPatternToWindow,
    patternFromImportPayload,
    segmentIntensity,
    STUDIO_MAX_ACTIONS,
    studioCropPreviewPayload,
    timelineIntensityColor,
} from '../../static/js/motion/training-editor.js';
import { state } from '../../static/js/context.js';

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
        assert.ok(pattern.tags.includes('drawn'));
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
