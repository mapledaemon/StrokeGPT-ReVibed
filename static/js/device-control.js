import { apiCall, el, reportSaveFailure, setSliderValue, setStatusMessage, state } from './context.js';

function handyKeyInputs() {
    return [el.handyKeyInput, el.sidebarHandyKeyInput].filter(Boolean);
}

function handyKeyStatusElements() {
    return [el.handyKeyStatus, el.sidebarHandyKeyStatus].filter(Boolean);
}

function connectionStatusColor(status = 'disconnected') {
    return {
        connected: 'var(--green)',
        disconnected: 'var(--red-hover)',
        error: 'var(--yellow)',
    }[status] || 'var(--red-hover)';
}

function connectionStatusLabel(status = 'disconnected') {
    return {
        connected: 'Connected',
        disconnected: 'Disconnected',
        error: 'Error',
    }[status] || 'Disconnected';
}

export function setHandyConnectionStatus(status = 'disconnected', detail = '') {
    const label = connectionStatusLabel(status);
    const color = connectionStatusColor(status);
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
    setHandyConnectionStatus('disconnected');
}

export function applyHandyConnectionResult(key, res) {
    markHandyConnectionKeySaved(key);
    const connection = res?.connection || {};
    const connectionStatus = connection.status || res?.connection_status || (res?.connected ? 'connected' : 'error');
    const detail = connection.message || res?.message || (
        connectionStatus === 'connected' ? 'Connected to Handy.' : 'Handy connection check failed.'
    );
    setHandyConnectionStatus(connectionStatus, detail);
    setStatusMessage(el.statusText, detail, connectionStatus === 'connected' ? 'success' : 'warning');
}

function hasUnsavedHandyKeyDraft() {
    return handyKeyInputs().some(input => {
        const draft = (input.value || '').trim();
        return draft && draft !== state.myHandyKey;
    });
}

function normalizeMotionDepthRange() {
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
    state.handyApiV3Key = data.handy_api_v3_key || state.handyApiV3Key || '';
    syncHandyConnectionKey(state.myHandyKey);
    if (el.handyFirmwareSelect) el.handyFirmwareSelect.value = state.handyFirmwareVersion;
    if (el.handyApiV3KeyInput) el.handyApiV3KeyInput.value = state.handyApiV3Key;
    updateHandyFirmwareStatus(data);
    setHandyConnectionStatus('disconnected');
    setSliderValue(el.motionDepthMinSlider, el.motionDepthMinVal, data.min_depth ?? 5);
    setSliderValue(el.motionDepthMaxSlider, el.motionDepthMaxVal, data.max_depth ?? 100);
    normalizeMotionDepthRange();
}

function updateHandyFirmwareStatus(data = {}) {
    if (!el.handyFirmwareStatus) return;
    const firmware = data.handy_firmware_version || state.handyFirmwareVersion || 'fw4';
    const v4Ready = Boolean(data.handy_api_v3_enabled ?? state.handyApiV3Key);
    if (firmware === 'fw4') {
        el.handyFirmwareStatus.textContent = v4Ready
            ? 'Firmware v4 selected. Continuous backend can use API v3 HSP point streaming.'
            : 'Firmware v4 selected. Add an API v3 app key to enable HSP point streaming.';
    } else {
        el.handyFirmwareStatus.textContent = 'Firmware v3 legacy selected. Continuous backend falls back to HDSP direct position commands.';
    }
}

export function updateHandyConnectionStatusFromMotion(payload = {}) {
    if (hasUnsavedHandyKeyDraft()) return;
    if (!state.myHandyKey) {
        setHandyConnectionStatus('disconnected', 'No Handy connection key saved.');
        return;
    }
    const command = payload?.diagnostics?.last_command;
    if (!command) {
        setHandyConnectionStatus('disconnected', 'No successful Handy command has been seen this session.');
        return;
    }
    const path = String(command.path || 'command').trim();
    if (command.ok === false) {
        const status = command.status_code !== undefined ? ` ${command.status_code}` : '';
        const error = String(command.error || '').trim();
        setHandyConnectionStatus(
            'error',
            `Handy ${path}${status} failed${error ? `: ${error}` : '.'}`,
        );
        return;
    }
    if (command.ok === true) {
        setHandyConnectionStatus('connected', `Handy ${path} OK.`);
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

async function saveMotionDepthRange() {
    normalizeMotionDepthRange();
    const res = await apiCall('/set_depth_limits', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({min_depth: state.motionMinDepth, max_depth: state.motionMaxDepth}),
    });
    if (res && res.status === 'success') {
        el.statusText.textContent = `Stroke range saved: ${state.motionMinDepth}-${state.motionMaxDepth}%.`;
    }
}

async function saveHandyConnectionKey(sourceInput = el.handyKeyInput) {
    const key = (sourceInput?.value || '').trim();
    if (!key) {
        setHandyConnectionStatus('disconnected', 'Enter a Handy connection key first.');
        return;
    }
    setStatusMessage(el.statusText, 'Connecting to Handy...', 'neutral');
    const res = await apiCall('/set_handy_key', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key}),
    });
    if (res && res.status === 'success') {
        applyHandyConnectionResult(key, res);
    }
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
        state.handyApiV3Key = handyApiV3Key;
        updateHandyFirmwareStatus(res);
        setStatusMessage(el.statusText, res.message || 'Handy firmware settings saved.', 'success');
    } else {
        reportSaveFailure(el.handyFirmwareStatus || el.statusText, res, 'Could not save Handy firmware settings.');
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
                setHandyConnectionStatus('disconnected', 'No successful Handy command has been seen this session.');
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
    el.saveHandyDeviceConfigBtn?.addEventListener('click', saveHandyDeviceConfig);
}
