// Behavioral coverage for Device-tab Handy connection controls.

import { describe, it, before, beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import { initDeviceControls, populateDeviceSettings } from '../../static/js/device-control.js';


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
            'handy-bluetooth-menu',
            'handy-bluetooth-btn',
            'handy-bluetooth-popover',
            'handy-rest-connection-controls',
            'sidebar-handy-rest-controls',
            'sidebar-handy-panel',
            'handy-firmware-select',
            'handy-api-v3-key-input',
            'save-handy-device-config-btn',
            'handy-firmware-status',
            'handy-transport-select',
            'save-handy-transport-btn',
            'handy-transport-status',
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
            'handy-bluetooth-menu',
            'handy-bluetooth-btn',
            'handy-bluetooth-popover',
            'handy-rest-connection-controls',
            'sidebar-handy-rest-controls',
            'sidebar-handy-panel',
            'handy-firmware-select',
            'handy-api-v3-key-input',
            'handy-firmware-status',
            'handy-transport-select',
            'handy-transport-status',
            'motion-depth-min-slider',
            'motion-depth-max-slider',
            'motion-depth-min-val',
            'motion-depth-max-val',
            'status-text',
        ].forEach(resetStubElement);
        state.myHandyKey = '';
        state.handyFirmwareVersion = 'fw4';
        state.handyApiV3Key = '';
        state.handyApiV3ConnectionKeyValid = true;
        state.handyTransport = 'rest';
        state.handyTransportOptions = [];
        state.handyBluetoothStatus = {connected: false, status: 'disconnected'};
        state.connectionLost = false;
        getStubElement('motion-depth-min-slider').value = '5';
        getStubElement('motion-depth-max-slider').value = '100';
    });

    it('Connect posts the key and shows an immediate device-online result', async () => {
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
                    last_command: {path: 'connected', ok: true, status_code: 200},
                },
            });
        };

        getStubElement('sidebar-handy-key-input').value = 'new-key';
        getStubElement('sidebar-save-handy-key-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, [{endpoint: '/set_handy_key', body: {key: 'new-key'}}]);
        assert.equal(state.myHandyKey, 'new-key');
        assert.equal(getStubElement('handy-key-input').value, 'new-key');
        assert.equal(getStubElement('handy-key-status').textContent, 'Device online');
        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Device online');
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
                last_command: {path: 'connected', ok: false, status_code: 503},
            },
        });

        getStubElement('handy-key-input').value = 'saved-but-offline';
        getStubElement('save-handy-key-btn').click();
        await flushAsyncHandlers();

        assert.equal(state.myHandyKey, 'saved-but-offline');
        assert.equal(getStubElement('sidebar-handy-key-input').value, 'saved-but-offline');
        assert.equal(getStubElement('handy-key-status').textContent, 'Device offline');
        assert.equal(getStubElement('sidebar-handy-key-status').style.color, 'var(--red-hover)');
        assert.equal(getStubElement('sidebar-handy-key-status').title, 'Handy connection failed: device offline');
        assert.equal(getStubElement('status-text').textContent, 'Handy connection failed: device offline');
    });

    it('Save firmware posts selected firmware and API v3 Application ID', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, body: JSON.parse(options.body)});
            return jsonResponse(200, {
                status: 'success',
                handy_firmware_version: 'fw4',
                handy_api_v3_key: 'app-id',
                handy_api_v3_enabled: true,
                handy_api_v3_key_configured: true,
                continuous_streaming_supported: true,
                message: 'Handy firmware set to v4; API v3 HSP streaming is enabled.',
            });
        };

        state.myHandyKey = 'saved-key';
        getStubElement('handy-firmware-select').value = 'fw4';
        getStubElement('handy-api-v3-key-input').value = 'app-id';
        getStubElement('save-handy-device-config-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, [{
            endpoint: '/set_handy_device_config',
            body: {handy_firmware_version: 'fw4', handy_api_v3_key: 'app-id'},
        }]);
        assert.equal(state.handyFirmwareVersion, 'fw4');
        assert.equal(state.handyApiV3Key, 'app-id');
        assert.equal(
            getStubElement('handy-firmware-status').textContent,
            'Firmware v4 selected. API v3 HSP point streaming is enabled.',
        );
        assert.equal(
            getStubElement('status-text').textContent,
            'Handy firmware set to v4; API v3 HSP streaming is enabled.',
        );
    });

    it('Save firmware shows invalid API v3 connection-key format guidance', async () => {
        globalThis.fetch = async () => jsonResponse(200, {
            status: 'success',
            handy_firmware_version: 'fw4',
            handy_api_v3_key: 'app-id',
            handy_api_v3_enabled: false,
            handy_api_v3_connection_key_valid: false,
            handy_api_v3_key_configured: true,
            continuous_streaming_supported: false,
            message: 'Handy firmware set to v4; the saved WiFi/Cloud REST Handy connection key is malformed for API v3.',
        });

        state.myHandyKey = 'saved-key';
        getStubElement('handy-firmware-select').value = 'fw4';
        getStubElement('handy-api-v3-key-input').value = 'app-id';
        getStubElement('save-handy-device-config-btn').click();
        await flushAsyncHandlers();

        assert.equal(state.handyApiV3ConnectionKeyValid, false);
        assert.equal(
            getStubElement('handy-firmware-status').textContent,
            'Firmware v4 selected. The saved WiFi/Cloud REST Handy connection key is malformed for API v3; re-copy the device connection key from Handy setup.',
        );
        assert.equal(
            getStubElement('status-text').textContent,
            'Handy firmware set to v4; the saved WiFi/Cloud REST Handy connection key is malformed for API v3.',
        );
    });

    it('Save transport selects local Bluetooth without requiring a Handy key', async () => {
        const calls = [];
        globalThis.fetch = async (endpoint, options = {}) => {
            calls.push({endpoint, body: JSON.parse(options.body)});
            return jsonResponse(200, {
                status: 'success',
                handy_transport: 'browser_bluetooth',
                bluetooth: {
                    connected: false,
                    status: 'disconnected',
                    message: 'Local Bluetooth selected; connect from Handy Connection.',
                },
                message: 'Local Bluetooth selected. Connect from Handy Connection before starting motion.',
            });
        };

        getStubElement('handy-transport-select').value = 'browser_bluetooth';
        getStubElement('save-handy-transport-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, [{
            endpoint: '/set_handy_transport',
            body: {handy_transport: 'browser_bluetooth'},
        }]);
        assert.equal(state.handyTransport, 'browser_bluetooth');
        assert.equal(getStubElement('handy-bluetooth-menu').hidden, false);
        assert.equal(getStubElement('handy-rest-connection-controls').hidden, true);
        assert.equal(getStubElement('sidebar-handy-rest-controls').hidden, true);
        assert.equal(getStubElement('sidebar-handy-panel').hidden, true);
        assert.equal(
            getStubElement('handy-transport-status').textContent,
            'Local Bluetooth selected; connect from Handy Connection before starting motion.',
        );
        assert.equal(
            getStubElement('status-text').textContent,
            'Local Bluetooth selected. Connect from Handy Connection before starting motion.',
        );
    });

    it('startup Local Bluetooth state hides Cloud REST connection-key sections', () => {
        populateDeviceSettings({
            handy_transport: 'browser_bluetooth',
            handy_transport_options: [
                {id: 'rest', label: 'Cloud REST'},
                {id: 'browser_bluetooth', label: 'Local Bluetooth'},
            ],
        });

        assert.equal(state.handyTransport, 'browser_bluetooth');
        assert.equal(getStubElement('handy-bluetooth-menu').hidden, false);
        assert.equal(getStubElement('handy-rest-connection-controls').hidden, true);
        assert.equal(getStubElement('sidebar-handy-rest-controls').hidden, true);
        assert.equal(getStubElement('sidebar-handy-panel').hidden, true);
        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Disconnected');
        assert.equal(
            getStubElement('sidebar-handy-key-status').title,
            'Local Bluetooth selected; connect from Handy Connection.',
        );
    });

    it('transport selector immediately toggles Bluetooth and connection-key visibility', () => {
        populateDeviceSettings({
            handy_transport: 'rest',
            handy_transport_options: [
                {id: 'rest', label: 'Cloud REST'},
                {id: 'browser_bluetooth', label: 'Local Bluetooth'},
            ],
        });

        assert.equal(getStubElement('handy-bluetooth-menu').hidden, true);
        assert.equal(getStubElement('handy-rest-connection-controls').hidden, false);
        assert.equal(getStubElement('sidebar-handy-panel').hidden, false);

        getStubElement('handy-transport-select').value = 'browser_bluetooth';
        getStubElement('handy-transport-select').dispatchEvent('change');

        assert.equal(getStubElement('handy-bluetooth-menu').hidden, false);
        assert.equal(getStubElement('handy-rest-connection-controls').hidden, true);
        assert.equal(getStubElement('sidebar-handy-rest-controls').hidden, true);
        assert.equal(getStubElement('sidebar-handy-panel').hidden, true);

        getStubElement('handy-transport-select').value = 'rest';
        getStubElement('handy-transport-select').dispatchEvent('change');

        assert.equal(getStubElement('handy-bluetooth-menu').hidden, true);
        assert.equal(getStubElement('handy-rest-connection-controls').hidden, false);
        assert.equal(getStubElement('sidebar-handy-rest-controls').hidden, false);
        assert.equal(getStubElement('sidebar-handy-panel').hidden, false);
    });

    it('sidebar key Connect switches from local Bluetooth back to Cloud REST', async () => {
        const calls = [];
        state.handyTransport = 'browser_bluetooth';
        globalThis.fetch = async (endpoint, options = {}) => {
            const body = JSON.parse(options.body);
            calls.push({endpoint, body});
            if (endpoint === '/set_handy_transport') {
                return jsonResponse(200, {
                    status: 'success',
                    handy_transport: 'rest',
                    bluetooth: {connected: false, status: 'disconnected'},
                    message: 'Cloud REST transport selected.',
                });
            }
            return jsonResponse(200, {
                status: 'success',
                connected: true,
                connection_status: 'connected',
                message: 'Connected to Handy.',
                connection: {
                    status: 'connected',
                    connected: true,
                    message: 'Connected to Handy.',
                },
            });
        };

        getStubElement('sidebar-handy-key-input').value = 'cloud-key';
        getStubElement('sidebar-save-handy-key-btn').click();
        await flushAsyncHandlers();

        assert.deepEqual(calls, [
            {endpoint: '/set_handy_transport', body: {handy_transport: 'rest'}},
            {endpoint: '/set_handy_key', body: {key: 'cloud-key'}},
        ]);
        assert.equal(state.handyTransport, 'rest');
        assert.equal(getStubElement('handy-bluetooth-menu').hidden, true);
        assert.equal(getStubElement('handy-rest-connection-controls').hidden, false);
        assert.equal(getStubElement('sidebar-handy-rest-controls').hidden, false);
        assert.equal(getStubElement('sidebar-handy-panel').hidden, false);
        assert.equal(getStubElement('handy-transport-select').value, 'rest');
        assert.equal(getStubElement('sidebar-handy-key-status').textContent, 'Device online');
        assert.equal(getStubElement('status-text').textContent, 'Connected to Handy.');
    });
});
