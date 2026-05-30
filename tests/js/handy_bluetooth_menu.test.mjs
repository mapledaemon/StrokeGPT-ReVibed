// Behavioral coverage for the sidebar Handy Bluetooth status menu.

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
    'handy-bluetooth-menu',
    'handy-bluetooth-btn',
    'handy-bluetooth-popover',
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

describe('Handy Bluetooth sidebar menu', () => {
    let originalFetch;
    let originalBluetooth;

    before(() => {
        originalFetch = globalThis.fetch;
        originalBluetooth = globalThis.navigator?.bluetooth;
        MENU_IDS.forEach(resetStubElement);
        getStubElement('handy-bluetooth-popover').hidden = true;
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
        getStubElement('handy-bluetooth-btn').getBoundingClientRect = () => ({
            top: 500,
            bottom: 532,
            left: 900,
            right: 932,
            width: 32,
            height: 32,
        });
        const popover = getStubElement('handy-bluetooth-popover');
        popover.hidden = true;
        popover.scrollHeight = 260;
        popover.offsetHeight = 260;
        globalThis.window.innerWidth = 1000;
        globalThis.window.innerHeight = 700;
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

        getStubElement('handy-bluetooth-btn').click();

        assert.equal(getStubElement('handy-bluetooth-popover').hidden, false);
        assert.equal(getStubElement('handy-bluetooth-popover').style.position, 'fixed');
        assert.equal(getStubElement('handy-bluetooth-popover').dataset.placement, 'top');
        assert.match(getStubElement('handy-bluetooth-popover').style.left, /px$/);
        assert.match(getStubElement('handy-bluetooth-popover').style.maxHeight, /px$/);
        assert.equal(getStubElement('handy-bluetooth-popover').style.overflowY, 'visible');
        assert.equal(getStubElement('handy-bluetooth-btn').getAttribute('aria-expanded'), 'true');
        assert.equal(getStubElement('bluetooth-menu-state').textContent, 'Disconnected');
        assert.equal(getStubElement('bluetooth-menu-action-btn').textContent, 'Connect');
        assert.equal(requestDeviceCalls, 0);
    });

    it('scrolls the status menu only when viewport space is constrained', () => {
        getStubElement('handy-bluetooth-btn').getBoundingClientRect = () => ({
            top: 220,
            bottom: 252,
            left: 900,
            right: 932,
            width: 32,
            height: 32,
        });
        const popover = getStubElement('handy-bluetooth-popover');
        popover.scrollHeight = 420;
        popover.offsetHeight = 420;
        globalThis.window.innerHeight = 300;

        getStubElement('handy-bluetooth-btn').click();

        assert.equal(popover.hidden, false);
        assert.equal(popover.style.overflowY, 'auto');
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

        assert.equal(getStubElement('handy-bluetooth-btn').getAttribute('aria-label'), 'Handy Bluetooth connected');
        assert.equal(getStubElement('handy-bluetooth-btn').classList.contains('is-on'), true);
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
        getStubElement('handy-bluetooth-btn').click();
        getStubElement('bluetooth-menu-settings-btn').click();
        await flushAsyncHandlers();

        assert.equal(getStubElement('handy-bluetooth-popover').hidden, true);
        assert.equal(getStubElement('handy-bluetooth-popover').dataset.placement, undefined);
        assert.equal(getStubElement('handy-bluetooth-popover').style.top, '');
        assert.equal(getStubElement('settings-dialog').classList.contains('open'), true);
    });
});
