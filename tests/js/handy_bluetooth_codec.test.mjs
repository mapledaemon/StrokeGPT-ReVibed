import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { encodeHandyRequest } from '../../static/js/handy-bluetooth-codec.js';


describe('Handy Bluetooth protobuf codec', () => {
    it('keeps one HSP add chunk under the Handy BLE payload cap', () => {
        const points = Array.from({length: 48}, (_, index) => ({
            t: index * 50,
            x: index % 2 === 0 ? 20 : 80,
        }));
        const encoded = encodeHandyRequest('hsp/add', {
            points,
            flush: true,
            tail_point_stream_index: points.length,
            tail_point_threshold: 24,
        }, 7);
        assert.ok(encoded.length > 0);
        assert.ok(encoded.length <= 512, `encoded payload was ${encoded.length} bytes`);
    });

    it('rejects commands outside the implemented local Bluetooth subset', () => {
        assert.throws(
            () => encodeHandyRequest('unknown/path', {}, 1),
            /not implemented/,
        );
    });
});
