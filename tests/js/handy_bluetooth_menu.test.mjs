// Behavioral coverage for the top-bar Handy Bluetooth status menu.

import { describe, it, before, beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { state } from '../../static/js/context.js';
import { initHandyBluetoothControls, updateHandyBluetoothStatus } from '../../static/js/handy-bluetooth.js';


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

const MENU_IDS = [
    'top-bar-bluetooth-menu',
    'top-bar-bluetooth-btn',
    'top-bar-bluetooth-popover',
    'bluetooth-menu-state',
    'bluetooth-menu-transport',
    'bluetooth-menu-support',
    'bluetooth-menu-device',
    'bluetooth-menu-queue',
    'bluetooth-menu-message',
    'bluetooth-menu-action-btn',
    'bluetooth-menu-settings-btn',
    'handy-transport-status',
    'handy-transport-select',
    'settings-dialog',
    'status-text',
];

describe('Handy Bluetooth top-bar menu', () => {
    let originalFetch;
    let originalBluetooth;

    before(() => {
        originalFetch = globalThis.fetch;
        originalBluetooth = globalThis.navigator?.bluetooth;
        MENU_IDS.forEach(resetStubElement);
        getStubElement('top-bar-bluetooth-popover').hidden = true;
        globalThis.fetch = async () => jsonResponse(200, {
            status: 'success',
            handy_transport: 'rest',
            bluetooth: {
                connected: false,
                status: 'disconnected',
                message: 'Bluetooth not connected.',
                pending: 0,
                inflight: 0,
            },
        });
        initHandyBluetoothControls();
    });

    after(() => {
        globalThis.fetch = originalFetch;
        if (globalThis.navigator) globalThis.navigator.bluetooth = originalBluetooth;
    });

    beforeEach(() => {
        MENU_IDS.forEach(resetStubElement);
        state.handyTransport = 'rest';
        state.handyBluetoothStatus = {connected: false, status: 'disconnected'};
        state.handyBluetoothDevice = null;
        state.handyBluetoothTx = null;
        state.handyBluetoothRx = null;
        state.handyBluetoothPendingResponses = new Map();
        state.handyBluetoothMenuOpen = false;
        getStubElement('top-bar-bluetooth-popover').hidden = true;
        if (globalThis.navigator) {
            globalThis.navigator.bluetooth = {requestDevice: async () => ({})};
        }
        updateHandyBluetoothStatus({
            connected: false,
            status: 'disconnected',
            message: 'Bluetooth not connected.',
            pending: 0,
            inflight: 0,
        });
    });

    it('opens the status menu without launching the Bluetooth chooser', () => {
        let requestDeviceCalls = 0;
        globalThis.navigator.bluetooth = {
            requestDevice: async () => {
                requestDeviceCalls += 1;
                return {};
            },
        };

        getStubElement('top-bar-bluetooth-btn').click();

        assert.equal(getStubElement('top-bar-bluetooth-popover').hidden, false);
        assert.equal(getStubElement('top-bar-bluetooth-btn').getAttribute('aria-expanded'), 'true');
        assert.equal(getStubElement('bluetooth-menu-state').textContent, 'Disconnected');
        assert.equal(getStubElement('bluetooth-menu-action-btn').textContent, 'Connect');
        assert.equal(requestDeviceCalls, 0);
    });

    it('renders selected transport, device, and bridge queue details', () => {
        state.handyTransport = 'browser_bluetooth';
        state.handyBluetoothDevice = {name: 'Handy Test Unit', gatt: {connected: true}};
        state.handyBluetoothTx = {};
        state.handyBluetoothRx = {};

        updateHandyBluetoothStatus({
            connected: true,
            status: 'connected',
            device_name: 'Handy Test Unit',
            pending: 2,
            inflight: 1,
            message: 'Connected to Handy Test Unit over local Bluetooth.',
        });

        assert.equal(getStubElement('top-bar-bluetooth-btn').textContent, 'BT On');
        assert.equal(getStubElement('bluetooth-menu-state').textContent, 'Connected');
        assert.equal(getStubElement('bluetooth-menu-transport').textContent, 'Local Bluetooth');
        assert.equal(getStubElement('bluetooth-menu-device').textContent, 'Handy Test Unit');
        assert.equal(getStubElement('bluetooth-menu-queue').textContent, '2 queued / 1 active');
        assert.equal(getStubElement('bluetooth-menu-action-btn').textContent, 'Disconnect');
        assert.equal(
            getStubElement('bluetooth-menu-message').textContent,
            'Connected to Handy Test Unit over local Bluetooth.',
        );
    });

    it('opens Device settings from the menu', async () => {
        getStubElement('top-bar-bluetooth-btn').click();
        getStubElement('bluetooth-menu-settings-btn').click();
        await flushAsyncHandlers();

        assert.equal(getStubElement('top-bar-bluetooth-popover').hidden, true);
        assert.equal(getStubElement('settings-dialog').classList.contains('open'), true);
    });
});
