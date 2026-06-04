import {
    D,
    appendQueryParams,
    apiCall,
    el,
    fetchWithConnectionState,
    getUiClientId,
    setStatusMessage,
    state,
} from './context.js';
import { openSettings } from './settings.js';
import {
    HANDY_BLE_RX_UUID,
    HANDY_BLE_SERVICE_UUID,
    HANDY_BLE_TX_UUID,
    decodeHandyRpcMessage,
    encodeHandyRequest,
} from './handy-bluetooth-codec.js';

const COMMAND_WAIT_SECONDS = 6;
const HSP_ADD_CHUNK_POINTS = 20;
const WRITE_WITHOUT_RESPONSE_SETTLE_MS = 20;
const RESPONSE_TIMEOUT_MS = 5000;
const POPOVER_GAP_PX = 8;
const POPOVER_MARGIN_PX = 8;
const POPOVER_MIN_HEIGHT_PX = 120;
const POPOVER_SCROLL_TOLERANCE_PX = 4;
const POPOVER_WIDTH_PX = 240;
const BRIDGE_RESPONSE_REQUIRED_PATHS = new Set(['hsp/state']);

function bluetoothSupported() {
    return Boolean(globalThis.navigator?.bluetooth?.requestDevice);
}

function bluetoothConnected() {
    return Boolean(state.handyBluetoothDevice?.gatt?.connected && state.handyBluetoothTx && state.handyBluetoothRx);
}

function bluetoothStateLabel(status = state.handyBluetoothStatus) {
    const localConnected = bluetoothConnected();
    if (localConnected) return 'Connected';
    if (status?.connected) return 'Bridge active';
    if (status?.status === 'connecting') return 'Connecting';
    if (status?.status === 'stale') return 'Stale';
    if (status?.status === 'error') return 'Error';
    return 'Disconnected';
}

function bluetoothSupportLabel() {
    return bluetoothSupported() ? 'Available' : 'Unavailable';
}

function bluetoothTransportLabel(status = state.handyBluetoothStatus) {
    if (state.handyTransport === 'browser_bluetooth' || status?.connected || bluetoothConnected()) {
        return 'Local Bluetooth';
    }
    return 'Cloud REST';
}

function bluetoothDeviceLabel(status = state.handyBluetoothStatus) {
    const name = status?.device_name || state.handyBluetoothDevice?.name || '';
    if (name) return name;
    return Boolean(status?.connected || bluetoothConnected()) ? 'Handy' : 'None';
}

function bluetoothBridgeLabel(status = state.handyBluetoothStatus) {
    const pending = Number(status?.pending ?? 0);
    const inflight = Number(status?.inflight ?? 0);
    if (pending || inflight) return `${pending} queued / ${inflight} active`;
    const ack = status?.last_ack;
    if (ack && Number.isFinite(Number(ack.elapsed_ms))) {
        return `${ack.ok === false ? 'Last failed' : 'Last OK'} (${Math.round(Number(ack.elapsed_ms))} ms)`;
    }
    return Boolean(status?.connected || bluetoothConnected()) ? 'Ready' : 'Idle';
}

function bluetoothMessage(status = state.handyBluetoothStatus) {
    if (!bluetoothSupported()) return 'Web Bluetooth is not available in this browser.';
    if (status?.last_error) return status.last_error;
    if (status?.message) return status.message;
    if (state.handyTransport !== 'browser_bluetooth') {
        return 'Cloud REST is selected. Connect here to switch Handy control to local Bluetooth.';
    }
    return Boolean(status?.connected || bluetoothConnected())
        ? 'Local Bluetooth is connected and ready for HSP commands.'
        : 'Local Bluetooth is selected. Connect before starting motion.';
}

function viewportMetric(name, fallback) {
    const visualViewport = globalThis.visualViewport || globalThis.window?.visualViewport;
    const value = visualViewport?.[name] ?? globalThis.window?.[name] ?? globalThis[name];
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : fallback;
}

function clampPopoverPosition(value, min, max) {
    if (max <= min) return min;
    return Math.min(max, Math.max(min, value));
}

function clearBluetoothPopoverPosition() {
    const popover = el.handyBluetoothPopover;
    if (!popover) return;
    delete popover.dataset.placement;
    popover.style.left = '';
    popover.style.top = '';
    popover.style.right = '';
    popover.style.bottom = '';
    popover.style.width = '';
    popover.style.maxHeight = '';
    popover.style.overflowY = '';
}

function positionBluetoothPopover() {
    if (!state.handyBluetoothMenuOpen || !el.handyBluetoothPopover || !el.handyBluetoothBtn) return;
    const popover = el.handyBluetoothPopover;
    const buttonRect = el.handyBluetoothBtn.getBoundingClientRect();
    const viewportWidth = viewportMetric('innerWidth', 1024);
    const viewportHeight = viewportMetric('innerHeight', 768);
    const popoverWidth = Math.max(
        180,
        Math.min(POPOVER_WIDTH_PX, viewportWidth - POPOVER_MARGIN_PX * 2),
    );

    popover.style.position = 'fixed';
    popover.style.width = `${Math.round(popoverWidth)}px`;
    popover.style.right = 'auto';
    popover.style.bottom = 'auto';
    popover.style.maxHeight = '';
    popover.style.overflowY = '';

    const contentHeight = Math.max(
        POPOVER_MIN_HEIGHT_PX,
        Number(popover.scrollHeight || 0),
        Number(popover.offsetHeight || 0),
    );
    const aboveSpace = Math.max(0, Number(buttonRect.top || 0) - POPOVER_MARGIN_PX - POPOVER_GAP_PX);
    const belowSpace = Math.max(0, viewportHeight - Number(buttonRect.bottom || 0) - POPOVER_MARGIN_PX - POPOVER_GAP_PX);
    const openAbove = aboveSpace >= Math.min(contentHeight, POPOVER_MIN_HEIGHT_PX) || aboveSpace > belowSpace;
    const availableHeight = Math.max(
        POPOVER_MIN_HEIGHT_PX,
        Math.min(viewportHeight - POPOVER_MARGIN_PX * 2, openAbove ? aboveSpace : belowSpace),
    );
    const needsScroll = contentHeight - availableHeight > POPOVER_SCROLL_TOLERANCE_PX;
    const popoverHeight = needsScroll ? availableHeight : contentHeight;
    const maxLeft = viewportWidth - POPOVER_MARGIN_PX - popoverWidth;
    const left = clampPopoverPosition(
        Number(buttonRect.right || 0) - popoverWidth,
        POPOVER_MARGIN_PX,
        maxLeft,
    );
    const top = openAbove
        ? clampPopoverPosition(Number(buttonRect.top || 0) - POPOVER_GAP_PX - popoverHeight, POPOVER_MARGIN_PX, viewportHeight - POPOVER_MARGIN_PX - popoverHeight)
        : clampPopoverPosition(Number(buttonRect.bottom || 0) + POPOVER_GAP_PX, POPOVER_MARGIN_PX, viewportHeight - POPOVER_MARGIN_PX - popoverHeight);

    popover.dataset.placement = openAbove ? 'top' : 'bottom';
    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(top)}px`;
    popover.style.maxHeight = needsScroll
        ? `${Math.floor(popoverHeight)}px`
        : `${Math.ceil(popoverHeight + POPOVER_SCROLL_TOLERANCE_PX)}px`;
    popover.style.overflowY = needsScroll ? 'auto' : 'visible';
}

function requestBluetoothPopoverPosition() {
    positionBluetoothPopover();
    const requestFrame = globalThis.requestAnimationFrame || globalThis.window?.requestAnimationFrame;
    if (typeof requestFrame === 'function') requestFrame(positionBluetoothPopover);
}

function setBluetoothMenuOpen(isOpen) {
    const open = Boolean(isOpen && el.handyBluetoothPopover && el.handyBluetoothBtn);
    state.handyBluetoothMenuOpen = open;
    if (el.handyBluetoothPopover) el.handyBluetoothPopover.hidden = !open;
    if (el.handyBluetoothBtn) el.handyBluetoothBtn.setAttribute('aria-expanded', String(open));
    if (open) {
        requestBluetoothPopoverPosition();
    } else {
        clearBluetoothPopoverPosition();
    }
}

function bluetoothMenuContains(target) {
    let node = target;
    while (node) {
        if (node === el.handyBluetoothMenu) return true;
        node = node.parentNode;
    }
    return target === el.handyBluetoothBtn
        || target === el.handyBluetoothPopover
        || target === el.bluetoothMenuActionBtn
        || target === el.bluetoothMenuSettingsBtn;
}

function updateBluetoothMenu(status = state.handyBluetoothStatus) {
    const connected = Boolean(status?.connected || bluetoothConnected());
    const connecting = status?.status === 'connecting';
    const error = status?.status === 'error' || status?.status === 'stale';
    if (el.bluetoothMenuState) {
        el.bluetoothMenuState.textContent = bluetoothStateLabel(status);
        el.bluetoothMenuState.classList.toggle('is-on', connected);
        el.bluetoothMenuState.classList.toggle('is-waiting', connecting);
        el.bluetoothMenuState.classList.toggle('is-error', !connected && error);
    }
    if (el.bluetoothMenuTransport) el.bluetoothMenuTransport.textContent = bluetoothTransportLabel(status);
    if (el.bluetoothMenuSupport) el.bluetoothMenuSupport.textContent = bluetoothSupportLabel();
    if (el.bluetoothMenuDevice) el.bluetoothMenuDevice.textContent = bluetoothDeviceLabel(status);
    if (el.bluetoothMenuQueue) el.bluetoothMenuQueue.textContent = bluetoothBridgeLabel(status);
    if (el.bluetoothMenuMessage) {
        el.bluetoothMenuMessage.textContent = bluetoothMessage(status);
        el.bluetoothMenuMessage.dataset.statusTone = !connected && error ? 'warning' : connected ? 'success' : 'info';
    }
    if (el.bluetoothMenuActionBtn) {
        el.bluetoothMenuActionBtn.textContent = bluetoothConnected()
            ? 'Disconnect'
            : connecting
                ? 'Connecting...'
                : connected
                    ? 'Reconnect'
                    : 'Connect';
        el.bluetoothMenuActionBtn.disabled = connecting;
    }
    requestBluetoothPopoverPosition();
}

function updateBluetoothButton(status = state.handyBluetoothStatus) {
    const connected = Boolean(status?.connected || bluetoothConnected());
    const connecting = status?.status === 'connecting';
    const error = status?.status === 'error' || status?.status === 'stale';
    if (el.handyBluetoothBtn) {
        el.handyBluetoothBtn.classList.toggle('is-on', connected);
        el.handyBluetoothBtn.classList.toggle('is-connecting', connecting);
        el.handyBluetoothBtn.classList.toggle('is-error', !connected && error);
        el.handyBluetoothBtn.dataset.bluetoothState = connecting ? 'connecting' : connected ? 'connected' : 'disconnected';
        el.handyBluetoothBtn.setAttribute('aria-pressed', String(connected));
        el.handyBluetoothBtn.setAttribute(
            'aria-label',
            connected ? 'Handy Bluetooth connected' : connecting ? 'Handy Bluetooth connecting' : 'Handy Bluetooth disconnected',
        );
        el.handyBluetoothBtn.title = status?.message
            ? `${status.message} Open for Bluetooth details.`
            : 'Show local Handy Bluetooth status';
    }
    updateBluetoothMenu(status);
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
                    : 'Local Bluetooth selected; connect from Handy Connection.'
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
    const canWriteWithResponse = state.handyBluetoothTx.properties?.write;
    const canWriteWithoutResponse = state.handyBluetoothTx.properties?.writeWithoutResponse;
    if (canWriteWithResponse && typeof state.handyBluetoothTx.writeValueWithResponse === 'function') {
        await state.handyBluetoothTx.writeValueWithResponse(bytes);
        return 'with-response';
    } else if (canWriteWithResponse && typeof state.handyBluetoothTx.writeValue === 'function') {
        await state.handyBluetoothTx.writeValue(bytes);
        return 'with-response';
    } else if (canWriteWithoutResponse && typeof state.handyBluetoothTx.writeValueWithoutResponse === 'function') {
        await state.handyBluetoothTx.writeValueWithoutResponse(bytes);
        await new Promise(resolve => setTimeout(resolve, WRITE_WITHOUT_RESPONSE_SETTLE_MS));
        return 'without-response';
    } else if (typeof state.handyBluetoothTx.writeValueWithResponse === 'function') {
        try {
            await state.handyBluetoothTx.writeValueWithResponse(bytes);
            return 'with-response';
        } catch (error) {
            if (typeof state.handyBluetoothTx.writeValueWithoutResponse !== 'function') throw error;
            await state.handyBluetoothTx.writeValueWithoutResponse(bytes);
            await new Promise(resolve => setTimeout(resolve, WRITE_WITHOUT_RESPONSE_SETTLE_MS));
            return 'without-response';
        }
    } else if (typeof state.handyBluetoothTx.writeValue === 'function') {
        await state.handyBluetoothTx.writeValue(bytes);
        return 'with-response';
    } else if (typeof state.handyBluetoothTx.writeValueWithoutResponse === 'function') {
        await state.handyBluetoothTx.writeValueWithoutResponse(bytes);
        await new Promise(resolve => setTimeout(resolve, WRITE_WITHOUT_RESPONSE_SETTLE_MS));
        return 'without-response';
    } else {
        throw new Error('Bluetooth TX characteristic does not support writes.');
    }
}

async function sendBleRequest(path, body = {}, options = {}) {
    const waitForResponse = options.waitForResponse !== false;
    const id = nextMessageId();
    const bytes = encodeHandyRequest(path, body, id);
    if (!waitForResponse) {
        const write_mode = await writeBluetoothValue(bytes);
        return {ok: true, response_pending: true, write_mode};
    }
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
        if (response.error?.message) {
            postBluetoothStatus({
                status: 'error',
                event_type: 'bluetooth_rpc_error',
                error: response.error.message,
                message: response.error.message,
            });
            return;
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
        return sendBleRequest('hsp/add', body, {waitForResponse: false});
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
        }, {waitForResponse: false});
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
            : await sendBleRequest(command.path, body, {
                waitForResponse: BRIDGE_RESPONSE_REQUIRED_PATHS.has(command.path),
            });
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

export const executeBridgeCommandForTests = executeBridgeCommand;

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
        updateBluetoothButton(state.handyBluetoothStatus);
    }
    return data;
}

export function initHandyBluetoothControls() {
    updateBluetoothButton();
    el.handyBluetoothBtn?.addEventListener('click', event => {
        event.stopPropagation?.();
        setBluetoothMenuOpen(!state.handyBluetoothMenuOpen);
    });
    el.bluetoothMenuActionBtn?.addEventListener('click', event => {
        event.stopPropagation?.();
        if (bluetoothConnected()) disconnectHandyBluetooth();
        else connectHandyBluetooth();
    });
    el.bluetoothMenuSettingsBtn?.addEventListener('click', event => {
        event.stopPropagation?.();
        setBluetoothMenuOpen(false);
        openSettings('device');
    });
    D.addEventListener('click', event => {
        if (!state.handyBluetoothMenuOpen) return;
        if (!bluetoothMenuContains(event.target)) setBluetoothMenuOpen(false);
    });
    D.addEventListener('scroll', () => {
        if (state.handyBluetoothMenuOpen) requestBluetoothPopoverPosition();
    }, true);
    D.addEventListener('keydown', event => {
        if (event.key === 'Escape') setBluetoothMenuOpen(false);
    });
    globalThis.window?.addEventListener?.('resize', () => {
        if (state.handyBluetoothMenuOpen) requestBluetoothPopoverPosition();
    });
    refreshHandyBluetoothStatus();
}
