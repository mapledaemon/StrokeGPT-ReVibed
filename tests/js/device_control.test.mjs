// Behavioral coverage for Device-tab Handy connection controls.

import { describe, it, before, beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import { initDeviceControls } from '../../static/js/device-control.js';


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

async function flushAsyncHandlers() {
    await new Promise(resolve => setTimeout(resolve, 0));
    await new Promise(resolve => setTimeout(resolve, 0));
}

describe('Device Handy connection controls', () => {
    let originalFetch;

    before(() => {
        originalFetch = globalThis.fetch;
        [
            'handy-key-input',
            'sidebar-handy-key-input',
            'handy-key-status',
            'sidebar-handy-key-status',
            'save-handy-key-btn',
            'sidebar-save-handy-key-btn',
            'handy-firmware-select',
            'save-handy-device-config-btn',
            'handy-firmware-status',
            'motion-depth-min-slider',
            'motion-depth-max-slider',
            'motion-depth-min-val',
            'motion-depth-max-val',
            'test-motion-depth-range',
            'save-motion-depth-range',
            'status-text',
        ].forEach(resetStubElement);
        getStubElement('motion-depth-min-slider').value = '5';
        getStubElement('motion-depth-max-slider').value = '100';
        initDeviceControls();
    });

    after(() => {
        globalThis.fetch = originalFetch;
    });

    beforeEach(() => {
        [
            'handy-key-input',
            'sidebar-handy-key-input',
            'handy-key-status',
            'sidebar-handy-key-status',
            'handy-firmware-select',
            'handy-firmware-status',
            'status-text',
        ].forEach(resetStubElement);
        state.myHandyKey = '';
        state.handyFirmwareVersion = 'fw4';
        state.connectionLost = false;
    });

    it('Connect posts the key and shows an immediate connected result', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, body: JSON.parse(options.body)});
            return jsonResponse(200, {
                status: 'success',
                connected: true,
                connection_status: 'connected',
                message: 'Connected to Handy.',
                connection: {
                    status: 'connected',
                    connected: true,
                    message: 'Connected to Handy.',
                    last_command: {path: 'slide/position/absolute', ok: true, status_code: 200},
                },
            });
        };

        getStubElement('sidebar-handy-key-input').value = 'new-key';
        getStubElement('sidebar-save-handy-key-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, [{endpoint: '/set_handy_key', body: {key: 'new-key'}}]);
        assert.equal(state.myHandyKey, 'new-key');
        assert.equal(getStubElement('handy-key-input').value, 'new-key');
        assert.equal(getStubElement('handy-key-status').textContent, 'Connected');
        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Connected');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--green)');
        assert.equal(getStubElement('status-text').textContent, 'Connected to Handy.');
    });

    it('Connect keeps the key saved but marks the connection error when the probe fails', async () => {
        globalThis.fetch = async () => jsonResponse(200, {
            status: 'success',
            connected: false,
            connection_status: 'error',
            message: 'Handy connection failed: device offline',
            connection: {
                status: 'error',
                connected: false,
                message: 'Handy connection failed: device offline',
                last_command: {path: 'slide/position/absolute', ok: false, status_code: 503},
            },
        });

        getStubElement('handy-key-input').value = 'saved-but-offline';
        getStubElement('save-handy-key-btn').click();
        await flushAsyncHandlers();

        assert.equal(state.myHandyKey, 'saved-but-offline');
        assert.equal(getStubElement('sidebar-handy-key-input').value, 'saved-but-offline');
        assert.equal(getStubElement('handy-key-status').textContent, 'Error');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--yellow)');
        assert.equal(getStubElement('sidebar-handy-key-status').title, 'Handy connection failed: device offline');
        assert.equal(getStubElement('status-text').textContent, 'Handy connection failed: device offline');
    });

    it('Save firmware posts only the selected firmware version', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, body: JSON.parse(options.body)});
            return jsonResponse(200, {
                status: 'success',
                handy_firmware_version: 'fw4',
                handy_api_v3_enabled: true,
                continuous_streaming_supported: true,
                message: 'Handy firmware set to v4; API v3 uses the saved Handy connection key.',
            });
        };

        state.myHandyKey = 'saved-key';
        getStubElement('handy-firmware-select').value = 'fw4';
        getStubElement('save-handy-device-config-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, [{
            endpoint: '/set_handy_device_config',
            body: {handy_firmware_version: 'fw4'},
        }]);
        assert.equal(state.handyFirmwareVersion, 'fw4');
        assert.equal(
            getStubElement('handy-firmware-status').textContent,
            'Firmware v4 selected. API v3 uses the saved Handy connection key for HSP point streaming.',
        );
        assert.equal(
            getStubElement('status-text').textContent,
            'Handy firmware set to v4; API v3 uses the saved Handy connection key.',
        );
    });
});
