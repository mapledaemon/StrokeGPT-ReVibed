// Behavioral coverage for forwarding backend motion commands over browser BLE.

import { describe, it, beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';

import { resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import { executeBridgeCommandForTests } from '../../static/js/handy-bluetooth.js';


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

describe('Handy Bluetooth command transport', () => {
    let originalFetch;

    beforeEach(() => {
        originalFetch = globalThis.fetch;
        ['connection-lost-banner', 'status-text'].forEach(resetStubElement);
        state.handyBluetoothDevice = {name: 'Handy Test Unit', gatt: {connected: true}};
        state.handyBluetoothRx = {};
        state.handyBluetoothPendingResponses = new Map();
        state.handyBluetoothMessageId = 1;
        state.connectionLost = false;
    });

    after(() => {
        globalThis.fetch = originalFetch;
    });

    it('acks backend motion commands after GATT writes without waiting for RPC notifications', async () => {
        const writes = [];
        const acknowledgements = [];
        state.handyBluetoothTx = {
            properties: {write: true, writeWithoutResponse: true},
            async writeValueWithResponse(bytes) {
                writes.push(new Uint8Array(bytes));
            },
            async writeValueWithoutResponse() {
                throw new Error('write without response should not be preferred');
            },
        };
        globalThis.fetch = async (endpoint, options = {}) => {
            acknowledgements.push({
                endpoint,
                body: JSON.parse(options.body || '{}'),
            });
            return jsonResponse(200, {
                status: 'success',
                bluetooth: {connected: true, status: 'connected'},
            });
        };

        await executeBridgeCommandForTests({id: 42, path: 'mode2', body: {mode: 4}});

        assert.equal(writes.length, 1);
        assert.equal(state.handyBluetoothPendingResponses.size, 0);
        assert.equal(state.handyBluetoothMessageId, 1);
        assert.equal(acknowledgements.length, 1);
        assert.equal(acknowledgements[0].endpoint, '/handy_bluetooth/ack');
        assert.equal(acknowledgements[0].body.id, 42);
        assert.equal(acknowledgements[0].body.ok, true);
    });

    it('uses write-without-response when that is the advertised GATT write mode', async () => {
        const writes = [];
        const acknowledgements = [];
        state.handyBluetoothTx = {
            properties: {write: false, writeWithoutResponse: true},
            async writeValueWithResponse() {
                throw new Error('write with response should not be used');
            },
            async writeValueWithoutResponse(bytes) {
                writes.push(new Uint8Array(bytes));
            },
        };
        globalThis.fetch = async (endpoint, options = {}) => {
            acknowledgements.push({
                endpoint,
                body: JSON.parse(options.body || '{}'),
            });
            return jsonResponse(200, {
                status: 'success',
                bluetooth: {connected: true, status: 'connected'},
            });
        };

        await executeBridgeCommandForTests({id: 43, path: 'hsp/play', body: {start_time: 0}});

        assert.equal(writes.length, 1);
        assert.equal(state.handyBluetoothPendingResponses.size, 0);
        assert.equal(state.handyBluetoothMessageId, 1);
        assert.equal(acknowledgements.length, 1);
        assert.equal(acknowledgements[0].body.id, 43);
        assert.equal(acknowledgements[0].body.ok, true);
    });

    it('waits for HSP state responses before acking backend device checks', async () => {
        const writes = [];
        const acknowledgements = [];
        state.handyBluetoothTx = {
            properties: {write: true, writeWithoutResponse: true},
            async writeValueWithResponse(bytes) {
                writes.push(new Uint8Array(bytes));
                const [id, pending] = Array.from(state.handyBluetoothPendingResponses.entries())[0] || [];
                assert.ok(pending, 'hsp/state should wait for a response');
                state.handyBluetoothPendingResponses.delete(id);
                pending.resolve({
                    ok: true,
                    hsp_state: {
                        play_state: 'stopped',
                        stream_id: 9,
                        current_time_ms: 0,
                    },
                });
            },
        };
        globalThis.fetch = async (endpoint, options = {}) => {
            acknowledgements.push({
                endpoint,
                body: JSON.parse(options.body || '{}'),
            });
            return jsonResponse(200, {
                status: 'success',
                bluetooth: {connected: true, status: 'connected'},
            });
        };

        await executeBridgeCommandForTests({id: 45, path: 'hsp/state', body: {}});

        assert.equal(writes.length, 1);
        assert.equal(state.handyBluetoothPendingResponses.size, 0);
        assert.equal(state.handyBluetoothMessageId, 2);
        assert.equal(acknowledgements.length, 1);
        assert.equal(acknowledgements[0].body.id, 45);
        assert.equal(acknowledgements[0].body.ok, true);
        assert.deepEqual(
            acknowledgements[0].body.response,
            {hsp_state: {play_state: 'stopped', stream_id: 9, current_time_ms: 0}},
        );
    });

    it('splits HSP add payloads into conservative BLE-sized writes', async () => {
        const writes = [];
        const acknowledgements = [];
        state.handyBluetoothTx = {
            properties: {write: false, writeWithoutResponse: true},
            async writeValueWithoutResponse(bytes) {
                writes.push(new Uint8Array(bytes));
            },
        };
        globalThis.fetch = async (endpoint, options = {}) => {
            acknowledgements.push({
                endpoint,
                body: JSON.parse(options.body || '{}'),
            });
            return jsonResponse(200, {
                status: 'success',
                bluetooth: {connected: true, status: 'connected'},
            });
        };
        const points = Array.from({length: 60}, (_, index) => ({
            t: index * 50,
            x: index % 2 === 0 ? 15 : 85,
        }));

        await executeBridgeCommandForTests({
            id: 44,
            path: 'hsp/add',
            body: {
                points,
                flush: true,
                tail_point_stream_index: points.length,
                tail_point_threshold: 48,
            },
        });

        assert.equal(writes.length, 3);
        assert.ok(writes.every(bytes => bytes.length <= 244), writes.map(bytes => bytes.length).join(', '));
        assert.equal(acknowledgements.length, 1);
        assert.equal(acknowledgements[0].body.id, 44);
        assert.equal(acknowledgements[0].body.ok, true);
    });
});
