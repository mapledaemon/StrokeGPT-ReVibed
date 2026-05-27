import {
    appendQueryParams,
    apiCall,
    el,
    fetchWithConnectionState,
    getUiClientId,
    setStatusMessage,
    state,
} from './context.js';
import {
    HANDY_BLE_RX_UUID,
    HANDY_BLE_SERVICE_UUID,
    HANDY_BLE_TX_UUID,
    decodeHandyRpcMessage,
    encodeHandyRequest,
} from './handy-bluetooth-codec.js';

const COMMAND_WAIT_SECONDS = 6;
const HSP_ADD_CHUNK_POINTS = 48;
const RESPONSE_TIMEOUT_MS = 5000;

function bluetoothSupported() {
    return Boolean(globalThis.navigator?.bluetooth?.requestDevice);
}

function bluetoothConnected() {
    return Boolean(state.handyBluetoothDevice?.gatt?.connected && state.handyBluetoothTx && state.handyBluetoothRx);
}

function updateBluetoothButton(status = state.handyBluetoothStatus) {
    if (!el.topBarBluetoothBtn) return;
    const connected = Boolean(status?.connected || bluetoothConnected());
    const connecting = status?.status === 'connecting';
    const error = status?.status === 'error' || status?.status === 'stale';
    el.topBarBluetoothBtn.classList.toggle('is-on', connected);
    el.topBarBluetoothBtn.classList.toggle('is-connecting', connecting);
    el.topBarBluetoothBtn.classList.toggle('is-error', !connected && error);
    el.topBarBluetoothBtn.textContent = connecting ? 'BT ...' : connected ? 'BT On' : 'BT Off';
    el.topBarBluetoothBtn.setAttribute('aria-pressed', String(connected));
    el.topBarBluetoothBtn.setAttribute(
        'aria-label',
        connected ? 'Handy Bluetooth connected' : connecting ? 'Handy Bluetooth connecting' : 'Handy Bluetooth disconnected',
    );
    el.topBarBluetoothBtn.title = status?.message || (
        connected ? 'Disconnect local Handy Bluetooth' : 'Connect local Handy Bluetooth'
    );
}

export function updateHandyBluetoothStatus(status = {}) {
    state.handyBluetoothStatus = {
        ...state.handyBluetoothStatus,
        ...status,
        connected: Boolean(status.connected),
    };
    updateBluetoothButton(state.handyBluetoothStatus);
    if (el.handyTransportStatus && state.handyTransport === 'browser_bluetooth') {
        setStatusMessage(
            el.handyTransportStatus,
            state.handyBluetoothStatus.message || (
                state.handyBluetoothStatus.connected
                    ? 'Local Bluetooth connected.'
                    : 'Local Bluetooth selected; connect from the top bar.'
            ),
            state.handyBluetoothStatus.connected ? 'success' : 'info',
        );
    }
}

function nextMessageId() {
    state.handyBluetoothMessageId += 1;
    if (state.handyBluetoothMessageId > 2147483000) state.handyBluetoothMessageId = 1;
    return state.handyBluetoothMessageId;
}

async function writeBluetoothValue(bytes) {
    if (!state.handyBluetoothTx) throw new Error('Bluetooth TX characteristic is not ready.');
    if (bytes.length > 512) throw new Error(`Bluetooth command is too large (${bytes.length} bytes).`);
    if (typeof state.handyBluetoothTx.writeValueWithoutResponse === 'function') {
        await state.handyBluetoothTx.writeValueWithoutResponse(bytes);
    } else {
        await state.handyBluetoothTx.writeValue(bytes);
    }
}

async function sendBleRequest(path, body = {}) {
    const id = nextMessageId();
    const bytes = encodeHandyRequest(path, body, id);
    const responsePromise = new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            state.handyBluetoothPendingResponses.delete(id);
            reject(new Error(`Bluetooth response timed out for ${path}.`));
        }, RESPONSE_TIMEOUT_MS);
        state.handyBluetoothPendingResponses.set(id, {resolve, reject, timer, path});
    });
    try {
        await writeBluetoothValue(bytes);
    } catch (error) {
        const pending = state.handyBluetoothPendingResponses.get(id);
        if (pending) {
            clearTimeout(pending.timer);
            state.handyBluetoothPendingResponses.delete(id);
        }
        throw error;
    }
    const response = await responsePromise;
    if (response?.error?.message) {
        throw new Error(response.error.message);
    }
    return response || {ok: true};
}

function hspNotificationName(field) {
    return {
        860: 'hsp_threshold_reached',
        861: 'hsp_state_changed',
        862: 'hsp_looping',
        863: 'hsp_starving',
        864: 'hsp_resumed_on_non_starving',
        865: 'hsp_paused_on_starving',
    }[Number(field)] || 'bluetooth_notification';
}

async function postBluetoothStatus(payload = {}) {
    const data = await apiCall('/handy_bluetooth/status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            client_id: getUiClientId(),
            connected: bluetoothConnected(),
            device_name: state.handyBluetoothDevice?.name || '',
            ...payload,
        }),
    });
    if (data?.bluetooth) updateHandyBluetoothStatus(data.bluetooth);
    return data;
}

function handleBleMessage(event) {
    let parsed;
    try {
        const view = event.target.value;
        parsed = decodeHandyRpcMessage(new Uint8Array(view.buffer, view.byteOffset, view.byteLength));
    } catch (error) {
        console.warn('Could not decode Handy Bluetooth message:', error);
        return;
    }
    if (parsed.type === 'response') {
        const response = parsed.response || {};
        const pending = state.handyBluetoothPendingResponses.get(response.id);
        if (pending) {
            clearTimeout(pending.timer);
            state.handyBluetoothPendingResponses.delete(response.id);
            pending.resolve(response);
        }
        if (response.hsp_state) {
            postBluetoothStatus({
                status: 'connected',
                event_type: 'bluetooth_hsp_response',
                hsp_state: response.hsp_state,
            });
        }
        return;
    }
    if (parsed.type === 'notification') {
        const notification = parsed.notification || {};
        postBluetoothStatus({
            status: 'connected',
            event_type: hspNotificationName(notification.event_field),
            hsp_state: notification.hsp_state,
            message: 'Handy Bluetooth event received.',
        });
    }
}

async function syncBluetoothClock() {
    const samples = [];
    for (let index = 0; index < 5; index += 1) {
        const before = Date.now();
        const response = await sendBleRequest('clock/offset/get');
        const after = Date.now();
        const machineTime = response?.clock_offset_get?.time;
        if (Number.isFinite(machineTime)) {
            samples.push({
                offset: Math.round(((before + after) / 2) - machineTime),
                rtd: Math.max(0, after - before),
            });
        }
        await new Promise(resolve => setTimeout(resolve, 60));
    }
    if (!samples.length) return;
    const offset = Math.round(samples.reduce((sum, sample) => sum + sample.offset, 0) / samples.length);
    const rtd = Math.round(samples.reduce((sum, sample) => sum + sample.rtd, 0) / samples.length);
    state.handyBluetoothClockOffsetMs = offset;
    await sendBleRequest('clock/offset/set', {clock_offset: offset, rtd});
}

function bodyWithLocalServerTime(path, body = {}) {
    if (path !== 'hsp/play' && path !== 'hsp/synctime') return body;
    return {...body, server_time: Date.now()};
}

async function executeHspAdd(body = {}) {
    const points = Array.isArray(body.points) ? body.points : [];
    if (points.length <= HSP_ADD_CHUNK_POINTS) {
        return sendBleRequest('hsp/add', body);
    }
    let lastResponse = null;
    const tailIndex = Number(body.tail_point_stream_index || points.length);
    const baseTail = Math.max(0, tailIndex - points.length);
    for (let offset = 0; offset < points.length; offset += HSP_ADD_CHUNK_POINTS) {
        const chunk = points.slice(offset, offset + HSP_ADD_CHUNK_POINTS);
        const chunkEnd = offset + chunk.length;
        lastResponse = await sendBleRequest('hsp/add', {
            points: chunk,
            flush: offset === 0 ? Boolean(body.flush) : false,
            tail_point_stream_index: baseTail + chunkEnd,
            tail_point_threshold: chunkEnd >= points.length ? body.tail_point_threshold : undefined,
        });
    }
    return lastResponse || {ok: true};
}

async function executeBridgeCommand(command) {
    const started = performance.now();
    try {
        if (!bluetoothConnected()) throw new Error('Handy Bluetooth is not connected.');
        const body = bodyWithLocalServerTime(command.path, command.body || {});
        const response = command.path === 'hsp/add'
            ? await executeHspAdd(body)
            : await sendBleRequest(command.path, body);
        const elapsedMs = performance.now() - started;
        await apiCall('/handy_bluetooth/ack', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                client_id: getUiClientId(),
                id: command.id,
                ok: true,
                elapsed_ms: elapsedMs,
                response: response?.hsp_state ? {hsp_state: response.hsp_state} : {},
            }),
        });
    } catch (error) {
        const elapsedMs = performance.now() - started;
        await apiCall('/handy_bluetooth/ack', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                client_id: getUiClientId(),
                id: command.id,
                ok: false,
                elapsed_ms: elapsedMs,
                error: error?.message || String(error),
            }),
        });
    }
}

async function commandLoop() {
    if (state.handyBluetoothCommandLoopActive) return;
    state.handyBluetoothCommandLoopActive = true;
    try {
        while (bluetoothConnected()) {
            const endpoint = appendQueryParams('/handy_bluetooth/commands', {
                client_id: getUiClientId(),
                wait: COMMAND_WAIT_SECONDS,
            });
            let data;
            try {
                const response = await fetchWithConnectionState(endpoint);
                if (!response.ok) throw new Error(`Command poll failed: ${response.status}`);
                data = await response.json();
            } catch {
                await new Promise(resolve => setTimeout(resolve, 1000));
                continue;
            }
            const commands = Array.isArray(data?.commands) ? data.commands : [];
            for (const command of commands) {
                await executeBridgeCommand(command);
                if (!bluetoothConnected()) break;
            }
        }
    } finally {
        state.handyBluetoothCommandLoopActive = false;
    }
}

async function connectHandyBluetooth() {
    if (!bluetoothSupported()) {
        updateHandyBluetoothStatus({
            connected: false,
            status: 'error',
            message: 'Web Bluetooth is not available in this browser.',
        });
        setStatusMessage(el.statusText, 'Web Bluetooth is not available in this browser.', 'warning');
        return;
    }
    updateHandyBluetoothStatus({connected: false, status: 'connecting', message: 'Selecting Handy Bluetooth device...'});
    try {
        const device = await navigator.bluetooth.requestDevice({
            filters: [{services: [HANDY_BLE_SERVICE_UUID]}],
            optionalServices: [HANDY_BLE_SERVICE_UUID],
        });
        state.handyBluetoothDevice = device;
        device.addEventListener('gattserverdisconnected', handleBluetoothDisconnect);
        const server = await device.gatt.connect();
        state.handyBluetoothServer = server;
        const service = await server.getPrimaryService(HANDY_BLE_SERVICE_UUID);
        state.handyBluetoothTx = await service.getCharacteristic(HANDY_BLE_TX_UUID);
        state.handyBluetoothRx = await service.getCharacteristic(HANDY_BLE_RX_UUID);
        state.handyBluetoothRx.addEventListener('characteristicvaluechanged', handleBleMessage);
        await state.handyBluetoothRx.startNotifications();
        updateHandyBluetoothStatus({connected: true, status: 'connecting', message: 'Syncing Handy Bluetooth clock...'});
        try {
            await syncBluetoothClock();
        } catch (clockError) {
            console.warn('Handy Bluetooth clock sync failed:', clockError);
        }
        const data = await apiCall('/handy_bluetooth/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                client_id: getUiClientId(),
                device_name: device.name || 'Handy',
                message: `Connected to ${device.name || 'Handy'} over local Bluetooth.`,
            }),
        });
        state.handyTransport = 'browser_bluetooth';
        if (el.handyTransportSelect) el.handyTransportSelect.value = state.handyTransport;
        updateHandyBluetoothStatus(data?.bluetooth || {
            connected: true,
            status: 'connected',
            message: `Connected to ${device.name || 'Handy'} over local Bluetooth.`,
        });
        setStatusMessage(el.statusText, 'Handy Bluetooth connected.', 'success');
        commandLoop();
    } catch (error) {
        updateHandyBluetoothStatus({
            connected: false,
            status: 'error',
            message: error?.message || 'Bluetooth connection failed.',
        });
        setStatusMessage(el.statusText, `Bluetooth connection failed: ${error?.message || error}`, 'warning');
        await postBluetoothStatus({
            connected: false,
            status: 'error',
            error: error?.message || String(error),
            message: 'Bluetooth connection failed.',
        });
    }
}

async function disconnectHandyBluetooth() {
    try {
        if (bluetoothConnected()) {
            try {
                await sendBleRequest('hsp/stop');
            } catch {
                // Disconnect still needs to proceed if the device is already gone.
            }
        }
        state.handyBluetoothPendingResponses.forEach(pending => {
            clearTimeout(pending.timer);
            pending.reject?.(new Error('Bluetooth disconnected.'));
        });
        state.handyBluetoothPendingResponses.clear();
        if (state.handyBluetoothDevice?.gatt?.connected) {
            state.handyBluetoothDevice.gatt.disconnect();
        } else {
            await handleBluetoothDisconnect();
        }
    } catch (error) {
        setStatusMessage(el.statusText, `Bluetooth disconnect failed: ${error?.message || error}`, 'warning');
    }
}

async function handleBluetoothDisconnect() {
    const deviceName = state.handyBluetoothDevice?.name || '';
    state.handyBluetoothTx = null;
    state.handyBluetoothRx = null;
    state.handyBluetoothServer = null;
    updateHandyBluetoothStatus({
        connected: false,
        status: 'disconnected',
        message: deviceName ? `${deviceName} Bluetooth disconnected.` : 'Handy Bluetooth disconnected.',
    });
    await apiCall('/handy_bluetooth/disconnect', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            client_id: getUiClientId(),
            message: deviceName ? `${deviceName} Bluetooth disconnected.` : 'Handy Bluetooth disconnected.',
        }),
    });
}

export async function refreshHandyBluetoothStatus() {
    const data = await apiCall('/handy_bluetooth/status');
    if (data?.bluetooth) updateHandyBluetoothStatus(data.bluetooth);
    if (data?.handy_transport) {
        state.handyTransport = data.handy_transport;
        if (el.handyTransportSelect) el.handyTransportSelect.value = state.handyTransport;
    }
    return data;
}

export function initHandyBluetoothControls() {
    updateBluetoothButton();
    el.topBarBluetoothBtn?.addEventListener('click', () => {
        if (bluetoothConnected()) disconnectHandyBluetooth();
        else connectHandyBluetooth();
    });
    refreshHandyBluetoothStatus();
}
