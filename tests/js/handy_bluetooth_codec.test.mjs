import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { encodeHandyRequest } from '../../static/js/handy-bluetooth-codec.js';


function readVarint(bytes, offset = 0) {
    let value = 0n;
    let shift = 0n;
    let index = offset;
    while (index < bytes.length) {
        const byte = BigInt(bytes[index]);
        value |= (byte & 0x7fn) << shift;
        index += 1;
        if ((byte & 0x80n) === 0n) return {value: Number(value), offset: index};
        shift += 7n;
    }
    throw new Error('Truncated varint');
}

function parseFields(bytes) {
    const fields = [];
    let offset = 0;
    while (offset < bytes.length) {
        const key = readVarint(bytes, offset);
        offset = key.offset;
        const field = key.value >> 3;
        const wire = key.value & 0x7;
        let value;
        if (wire === 0) {
            const parsed = readVarint(bytes, offset);
            value = parsed.value;
            offset = parsed.offset;
        } else if (wire === 2) {
            const length = readVarint(bytes, offset);
            offset = length.offset;
            value = bytes.slice(offset, offset + length.value);
            offset += length.value;
        } else if (wire === 5) {
            value = bytes.slice(offset, offset + 4);
            offset += 4;
        } else {
            throw new Error(`Unsupported wire type ${wire}`);
        }
        fields.push({field, wire, value});
    }
    return fields;
}

function firstField(fields, field) {
    return fields.find(item => item.field === field);
}

function floatValue(item) {
    return new DataView(item.value.buffer, item.value.byteOffset, item.value.byteLength).getFloat32(0, true);
}

function firstHspPoint(encoded) {
    const rpc = parseFields(encoded);
    const request = parseFields(firstField(rpc, 2).value);
    const hspAdd = parseFields(firstField(request, 861).value);
    return parseFields(firstField(hspAdd, 1).value);
}

function requestBody(encoded, field) {
    const rpc = parseFields(encoded);
    const request = parseFields(firstField(rpc, 2).value);
    return parseFields(firstField(request, field).value);
}


describe('Handy Bluetooth protobuf codec', () => {
    it('keeps one HSP add chunk under the common BLE ATT payload cap', () => {
        const points = Array.from({length: 20}, (_, index) => ({
            t: 21600000 + index * 50,
            x: index % 2 === 0 ? 20 : 80,
        }));
        const encoded = encodeHandyRequest('hsp/add', {
            points,
            flush: true,
            tail_point_stream_index: 999999,
            tail_point_threshold: 999995,
        }, 7);
        assert.ok(encoded.length > 0);
        assert.ok(encoded.length <= 244, `encoded payload was ${encoded.length} bytes`);
    });

    it('maps app HSP point depth onto the BLE HSP point range', () => {
        const encoded = encodeHandyRequest('hsp/add', {
            points: [{t: 10, x: 100}],
            flush: true,
        }, 8);
        const point = firstHspPoint(encoded);

        assert.equal(firstField(point, 1).value, 10);
        assert.equal(firstField(point, 2).value, 1000);
    });

    it('maps REST-normalized stroke windows onto BLE percent stroke fields', () => {
        const encoded = encodeHandyRequest('slider/stroke', {
            min: 0.1,
            max: 0.9,
        }, 10);
        const body = requestBody(encoded, 841);

        assert.equal(Math.round(floatValue(firstField(body, 1))), 10);
        assert.equal(Math.round(floatValue(firstField(body, 2))), 90);
    });

    it('encodes HSP resume pick-up requests for starving Bluetooth streams', () => {
        const encoded = encodeHandyRequest('hsp/resume', {pick_up: true}, 9);
        const body = requestBody(encoded, 866);

        assert.equal(firstField(body, 1).value, 1);
    });

    it('rejects commands outside the implemented local Bluetooth subset', () => {
        assert.throws(
            () => encodeHandyRequest('unknown/path', {}, 1),
            /not implemented/,
        );
        assert.throws(
            () => encodeHandyRequest('hsp/threshold', {tail_point_threshold: 1}, 1),
            /not implemented/,
        );
    });
});
