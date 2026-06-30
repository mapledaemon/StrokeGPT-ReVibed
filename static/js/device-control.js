import { apiCall, el, reportSaveFailure, setSliderValue, setStatusMessage, state } from './context.js';
import { syncHandyBluetoothVisibility, updateHandyBluetoothStatus } from './handy-bluetooth.js';

function handyKeyInputs() {
    return [el.handyKeyInput, el.sidebarHandyKeyInput].filter(Boolean);
}

function handyKeyStatusElements() {
    return [el.handyKeyStatus, el.sidebarHandyKeyStatus].filter(Boolean);
}

function connectionStatusColor(status = 'disconnected') {
    return {
        connected: 'var(--green)',
        api: 'var(--green)',
        active: 'var(--green)',
        saved: 'var(--comment)',
        disconnected: 'var(--red-hover)',
        offline: 'var(--red-hover)',
        error: 'var(--yellow)',
    }[status] || 'var(--red-hover)';
}

function connectionStatusLabel(status = 'disconnected') {
    return {
        connected: 'Device online',
        api: 'Command OK',
        active: 'Motion active',
        saved: 'Key saved',
        disconnected: 'Disconnected',
        offline: 'Device offline',
        error: 'Connection issue',
    }[status] || 'Disconnected';
}

function offlineDetail(value = '') {
    return /\b(offline|disconnected|not connected|device timeout|device unavailable)\b/i.test(String(value || ''));
}

function normalizeHandyStatus(status = 'disconnected', detail = '') {
    const normalized = String(status || 'disconnected').toLowerCase();
    if (normalized === 'online') return 'connected';
    if (normalized === 'offline' || offlineDetail(detail)) return 'offline';
    if (normalized === 'api' || normalized === 'active' || normalized === 'saved') return normalized;
    if (normalized === 'connected' || normalized === 'disconnected' || normalized === 'error') return normalized;
    return 'disconnected';
}

export function setHandyConnectionStatus(status = 'disconnected', detail = '') {
    const normalizedStatus = normalizeHandyStatus(status, detail);
    const label = connectionStatusLabel(normalizedStatus);
    const color = connectionStatusColor(normalizedStatus);
    handyKeyStatusElements().forEach(statusElement => {
        statusElement.textContent = label;
        statusElement.style.color = color;
        statusElement.title = detail || label;
    });
}

export function syncHandyConnectionKey(key = '', source = null) {
    handyKeyInputs().forEach(input => {
        if (input !== source) input.value = key;
    });
}

export function markHandyConnectionKeySaved(key) {
    state.myHandyKey = key || '';
    syncHandyConnectionKey(state.myHandyKey);
    setHandyConnectionStatus(
        state.myHandyKey ? 'saved' : 'disconnected',
        state.myHandyKey
            ? 'Handy key saved; waiting for a device status or command result.'
            : 'No Handy connection key saved.',
    );
}

export function applyHandyConnectionResult(key, res) {
    markHandyConnectionKeySaved(key);
    const connection = res?.connection || {};
    const connectionStatus = connection.status || res?.connection_status || (res?.connected ? 'connected' : 'error');
    const detail = connection.message || res?.message || (
        connectionStatus === 'connected' ? 'Connected to Handy.' : 'Handy connection check failed.'
    );
    const normalizedStatus = normalizeHandyStatus(connectionStatus, detail);
    setHandyConnectionStatus(normalizedStatus, detail);
    setStatusMessage(el.statusText, detail, normalizedStatus === 'connected' ? 'success' : 'warning');
}

function hasUnsavedHandyKeyDraft() {
    return handyKeyInputs().some(input => {
        const draft = (input.value || '').trim();
        return draft && draft !== state.myHandyKey;
    });
}

function updateHandyRestConnectionVisibility() {
    const bluetoothSelected = state.handyTransport === 'browser_bluetooth';
    if (el.handyRestConnectionControls) el.handyRestConnectionControls.hidden = bluetoothSelected;
    if (el.sidebarHandyRestControls) el.sidebarHandyRestControls.hidden = bluetoothSelected;
    if (el.sidebarHandyPanel) el.sidebarHandyPanel.hidden = bluetoothSelected;
}

export function normalizeMotionDepthRange() {
    const a = parseInt(el.motionDepthMinSlider.value, 10);
    const b = parseInt(el.motionDepthMaxSlider.value, 10);
    state.motionMinDepth = Math.min(a, b);
    state.motionMaxDepth = Math.max(a, b);
    el.motionDepthMinVal.textContent = `${state.motionMinDepth}%`;
    el.motionDepthMaxVal.textContent = `${state.motionMaxDepth}%`;
}

export function populateDeviceSettings(data = {}) {
    state.myHandyKey = data.handy_key || state.myHandyKey || '';
    state.handyFirmwareVersion = data.handy_firmware_version || state.handyFirmwareVersion || 'fw4';
    state.handyApiV3Key = data.handy_api_v3_key ?? state.handyApiV3Key ?? '';
    state.handyApiV3ConnectionKeyValid = data.handy_api_v3_connection_key_valid ?? state.handyApiV3ConnectionKeyValid ?? true;
    state.handyTransport = data.handy_transport || state.handyTransport || 'rest';
    state.handyTransportOptions = Array.isArray(data.handy_transport_options) ? data.handy_transport_options : state.handyTransportOptions;
    syncHandyConnectionKey(state.myHandyKey);
    populateHandyTransportSelect();
    updateHandyRestConnectionVisibility();
    syncHandyBluetoothVisibility();
    if (el.handyFirmwareSelect) el.handyFirmwareSelect.value = state.handyFirmwareVersion;
    if (el.handyApiV3KeyInput) el.handyApiV3KeyInput.value = state.handyApiV3Key;
    updateHandyFirmwareStatus(data);
    updateHandyTransportStatus();
    const bluetoothSelected = state.handyTransport === 'browser_bluetooth';
    setHandyConnectionStatus(
        bluetoothSelected ? 'disconnected' : state.myHandyKey ? 'saved' : 'disconnected',
        bluetoothSelected
            ? 'Local Bluetooth selected; connect from Handy Connection.'
            : state.myHandyKey
                ? 'Handy key saved; waiting for a device status or command result.'
                : 'No Handy connection key saved.',
    );
    setSliderValue(el.motionDepthMinSlider, el.motionDepthMinVal, data.min_depth ?? 5);
    setSliderValue(el.motionDepthMaxSlider, el.motionDepthMaxVal, data.max_depth ?? 100);
    normalizeMotionDepthRange();
}

function populateHandyTransportSelect() {
    if (!el.handyTransportSelect) return;
    const options = state.handyTransportOptions.length
        ? state.handyTransportOptions
        : [
            {id: 'rest', label: 'Cloud REST'},
            {id: 'browser_bluetooth', label: 'Local Bluetooth'},
        ];
    el.handyTransportSelect.innerHTML = '';
    options.forEach(option => {
        const item = document.createElement('option');
        item.value = option.id;
        item.textContent = option.label || option.id;
        if (option.description) item.title = option.description;
        el.handyTransportSelect.appendChild(item);
    });
    el.handyTransportSelect.value = state.handyTransport;
}

function updateHandyTransportStatus(data = {}) {
    if (!el.handyTransportStatus) return;
    const transport = data.handy_transport || state.handyTransport || 'rest';
    updateHandyRestConnectionVisibility();
    syncHandyBluetoothVisibility();
    if (transport === 'browser_bluetooth') {
        const bluetooth = data.bluetooth || state.handyBluetoothStatus || {};
        setStatusMessage(
            el.handyTransportStatus,
            bluetooth.connected
                ? (bluetooth.message || 'Local Bluetooth connected.')
                : 'Local Bluetooth selected; connect from Handy Connection before starting motion.',
            bluetooth.connected ? 'success' : 'info',
        );
        return;
    }
    setStatusMessage(el.handyTransportStatus, 'Cloud REST selected. Uses the saved Handy connection key.', 'neutral');
}

function updateHandyFirmwareStatus(data = {}) {
    if (!el.handyFirmwareStatus) return;
    const firmware = data.handy_firmware_version || state.handyFirmwareVersion || 'fw4';
    const apiKeyConfigured = Boolean(data.handy_api_v3_key_configured ?? state.handyApiV3Key);
    const connectionKeyValid = Boolean(data.handy_api_v3_connection_key_valid ?? state.handyApiV3ConnectionKeyValid ?? true);
    const v4Ready = Boolean(data.handy_api_v3_enabled ?? (state.myHandyKey && apiKeyConfigured && connectionKeyValid));
    if (firmware === 'fw4') {
        if (state.handyTransport === 'browser_bluetooth') {
            el.handyFirmwareStatus.textContent = 'Firmware v4 selected. Local Bluetooth HSP streaming is enabled after the Handy Connection Bluetooth link is active.';
            return;
        }
        el.handyFirmwareStatus.textContent = v4Ready
            ? 'Firmware v4 selected. API v3 HSP point streaming is enabled.'
            : apiKeyConfigured
                ? connectionKeyValid
                    ? 'Firmware v4 selected. Connect a Handy key to enable API v3 HSP point streaming.'
                    : 'Firmware v4 selected. The saved WiFi/Cloud REST Handy connection key is malformed for API v3; re-copy the device connection key from Handy setup.'
                : 'Firmware v4 selected. Add a Handy API v3 Application ID to enable HSP point streaming.';
    } else {
        el.handyFirmwareStatus.textContent = 'Firmware v3 legacy selected. Continuous backend falls back to HDSP direct position commands.';
    }
}

export function updateHandyConnectionStatusFromMotion(payload = {}) {
    if (hasUnsavedHandyKeyDraft()) return;
    const diagnostics = payload?.diagnostics || {};
    if (diagnostics.transport_mode === 'browser_bluetooth' || state.handyTransport === 'browser_bluetooth') {
        const bluetooth = diagnostics.bluetooth || state.handyBluetoothStatus || {};
        updateHandyBluetoothStatus(bluetooth);
        if (bluetooth.connected) {
            setHandyConnectionStatus('connected', bluetooth.message || 'Handy Bluetooth connected.');
        } else {
            setHandyConnectionStatus('disconnected', bluetooth.message || 'Local Bluetooth selected; connect from Handy Connection.');
        }
        return;
    }
    if (!state.myHandyKey) {
        setHandyConnectionStatus('disconnected', 'No Handy connection key saved.');
        return;
    }
    const deviceStatus = normalizeHandyStatus(
        diagnostics.device_connection_status || 'unknown',
        diagnostics.device_connection_message || '',
    );
    if (deviceStatus === 'connected' || deviceStatus === 'offline' || deviceStatus === 'error') {
        setHandyConnectionStatus(
            deviceStatus,
            diagnostics.device_connection_message || (
                deviceStatus === 'connected'
                    ? 'Handy device status reports online.'
                    : deviceStatus === 'offline'
                        ? 'Handy device status reports offline.'
                        : 'Handy device status reported a problem.'
            ),
        );
        return;
    }
    const command = diagnostics.last_command;
    if (!command) {
        setHandyConnectionStatus('saved', 'Handy key saved; no command result or live device status has been seen this session.');
        return;
    }
    const path = String(command.path || 'command').trim();
    const motionActive = Boolean(payload.playback_active || diagnostics.hsp_streaming || diagnostics.hamp_started);
    if (command.ok === false) {
        const status = command.status_code !== undefined ? ` ${command.status_code}` : '';
        const error = String(command.error || '').trim();
        const nonFatalActiveHspPath = /^(hsp\/synctime|hsp\/threshold)$/i.test(path);
        if (motionActive && !offlineDetail(error) && (nonFatalActiveHspPath || !error)) {
            setHandyConnectionStatus(
                'active',
                `Motion is active. Last Handy ${path}${status} command reported a non-fatal issue${error ? `: ${error}` : '.'}`,
            );
            return;
        }
        setHandyConnectionStatus(
            offlineDetail(error) ? 'offline' : 'error',
            `Handy ${path}${status} failed${error ? `: ${error}` : '.'}`,
        );
        return;
    }
    if (command.ok === true) {
        setHandyConnectionStatus('api', `Last Handy ${path} command succeeded; no live device status event yet.`);
    }
}

async function testMotionDepthRange() {
    normalizeMotionDepthRange();
    const res = await apiCall('/test_depth_range', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({min_depth: state.motionMinDepth, max_depth: state.motionMaxDepth}),
    });
    if (res && res.status === 'busy') el.statusText.textContent = 'Depth test already running.';
}

export async function saveMotionDepthRange() {
    normalizeMotionDepthRange();
    const res = await apiCall('/set_depth_limits', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({min_depth: state.motionMinDepth, max_depth: state.motionMaxDepth}),
    });
    if (res && res.status === 'success') {
        const message = `Stroke range saved: ${state.motionMinDepth}-${state.motionMaxDepth}%.`;
        setStatusMessage(el.motionDepthRangeStatus, message, 'success');
        el.statusText.textContent = message;
        return true;
    }
    reportSaveFailure(el.motionDepthRangeStatus || el.statusText, res, 'Could not save stroke range.');
    return false;
}

async function saveHandyConnectionKey(sourceInput = el.handyKeyInput) {
    const key = (sourceInput?.value || '').trim();
    if (!key) {
        setHandyConnectionStatus('disconnected', 'Enter a Handy connection key first.');
        return false;
    }
    if (state.handyTransport === 'browser_bluetooth') {
        setStatusMessage(el.statusText, 'Switching to Cloud REST before connecting...', 'neutral');
        const transportRes = await apiCall('/set_handy_transport', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({handy_transport: 'rest'}),
        });
        if (!transportRes || transportRes.status !== 'success') {
            reportSaveFailure(el.handyTransportStatus || el.statusText, transportRes, 'Could not switch to Cloud REST before connecting.');
            return false;
        }
        state.handyTransport = transportRes.handy_transport || 'rest';
        if (el.handyTransportSelect) el.handyTransportSelect.value = state.handyTransport;
        if (transportRes.bluetooth) updateHandyBluetoothStatus(transportRes.bluetooth);
        syncHandyBluetoothVisibility();
        updateHandyRestConnectionVisibility();
        updateHandyTransportStatus(transportRes);
        updateHandyFirmwareStatus(transportRes);
    }
    setStatusMessage(el.statusText, 'Connecting to Handy...', 'neutral');
    const res = await apiCall('/set_handy_key', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key}),
    });
    if (res && res.status === 'success') {
        applyHandyConnectionResult(key, res);
        return true;
    }
    reportSaveFailure(el.handyKeyStatus || el.statusText, res, 'Could not save Handy connection key.');
    return false;
}

async function saveHandyDeviceConfig() {
    const handyFirmwareVersion = el.handyFirmwareSelect?.value || 'fw4';
    const handyApiV3Key = (el.handyApiV3KeyInput?.value || '').trim();
    const res = await apiCall('/set_handy_device_config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            handy_firmware_version: handyFirmwareVersion,
            handy_api_v3_key: handyApiV3Key,
        }),
    });
    if (res && res.status === 'success') {
        state.handyFirmwareVersion = res.handy_firmware_version || handyFirmwareVersion;
        state.handyApiV3Key = res.handy_api_v3_key ?? handyApiV3Key;
        state.handyApiV3ConnectionKeyValid = res.handy_api_v3_connection_key_valid ?? state.handyApiV3ConnectionKeyValid ?? true;
        updateHandyFirmwareStatus(res);
        setStatusMessage(el.statusText, res.message || 'Handy firmware settings saved.', 'success');
        return true;
    } else {
        reportSaveFailure(el.handyFirmwareStatus || el.statusText, res, 'Could not save Handy firmware settings.');
        return false;
    }
}

async function saveHandyTransport() {
    const handyTransport = el.handyTransportSelect?.value || state.handyTransport || 'rest';
    const res = await apiCall('/set_handy_transport', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({handy_transport: handyTransport}),
    });
    if (res && res.status === 'success') {
        state.handyTransport = res.handy_transport || handyTransport;
        if (el.handyTransportSelect) el.handyTransportSelect.value = state.handyTransport;
        if (res.bluetooth) updateHandyBluetoothStatus(res.bluetooth);
        syncHandyBluetoothVisibility();
        updateHandyRestConnectionVisibility();
        updateHandyTransportStatus(res);
        updateHandyFirmwareStatus(res);
        setStatusMessage(el.statusText, res.message || 'Handy transport saved.', 'success');
        return true;
    } else {
        reportSaveFailure(el.handyTransportStatus || el.statusText, res, 'Could not save Handy transport.');
        return false;
    }
}

export function initDeviceControls() {
    handyKeyInputs().forEach(input => {
        input.addEventListener('input', event => {
            const draft = event.target.value;
            syncHandyConnectionKey(draft, event.target);
            const normalized = draft.trim();
            if (!normalized) {
                setHandyConnectionStatus('disconnected', 'Enter a Handy connection key first.');
            } else if (normalized !== state.myHandyKey) {
                setHandyConnectionStatus('error', 'Unsaved Handy connection key.');
            } else {
                setHandyConnectionStatus('saved', 'Handy key saved; waiting for a device status or command result.');
            }
        });
        input.addEventListener('keydown', event => {
            if (event.key === 'Enter') saveHandyConnectionKey(input);
        });
    });
    el.saveHandyKeyBtn.addEventListener('click', () => saveHandyConnectionKey(el.handyKeyInput));
    el.sidebarSaveHandyKeyBtn?.addEventListener('click', () => saveHandyConnectionKey(el.sidebarHandyKeyInput));
    el.motionDepthMinSlider.addEventListener('input', normalizeMotionDepthRange);
    el.motionDepthMaxSlider.addEventListener('input', normalizeMotionDepthRange);
    el.motionDepthMinSlider.addEventListener('change', testMotionDepthRange);
    el.motionDepthMaxSlider.addEventListener('change', testMotionDepthRange);
    document.getElementById('test-motion-depth-range').addEventListener('click', testMotionDepthRange);
    document.getElementById('save-motion-depth-range').addEventListener('click', saveMotionDepthRange);
    el.handyFirmwareSelect?.addEventListener('change', () => {
        state.handyFirmwareVersion = el.handyFirmwareSelect.value || 'fw4';
        updateHandyFirmwareStatus();
    });
    el.handyApiV3KeyInput?.addEventListener('input', () => {
        state.handyApiV3Key = (el.handyApiV3KeyInput.value || '').trim();
        updateHandyFirmwareStatus();
    });
    el.saveHandyDeviceConfigBtn?.addEventListener('click', saveHandyDeviceConfig);
    el.handyTransportSelect?.addEventListener('change', () => {
        state.handyTransport = el.handyTransportSelect.value || 'rest';
        syncHandyBluetoothVisibility();
        updateHandyRestConnectionVisibility();
        updateHandyTransportStatus();
        updateHandyFirmwareStatus();
    });
    el.saveHandyTransportBtn?.addEventListener('click', saveHandyTransport);
}
