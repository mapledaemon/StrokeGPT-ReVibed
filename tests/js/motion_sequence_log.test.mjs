import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { formatMotionSequenceText } from '../../static/js/motion/sequence-log.js';

describe('motion sequence diagnostics formatting', () => {
    it('surfaces failed Handy commands in debug output', () => {
        const text = formatMotionSequenceText({
            backend: 'continuous',
            playback_active: true,
            trace: [{
                label: 'Freestyle sample',
                speed: 52,
                depth: 45,
                range: 70,
                frame_index: 0,
                frame_count: 1,
                command_ms: 12.5,
                hsp_buffer_after_command_ms: 1875.5,
                handy_ok: false,
                handy_path: 'hdsp/xava',
                handy_status: 503,
            }],
        }, 'debug');

        assert.match(text, /Handy hdsp\/xava 503 failed/);
        assert.match(text, /buf 1875\.5ms/);
    });
});
