import { apiCall, el, setSliderValue, setStatusMessage, state } from './context.js';

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
    syncHandyConnectionKey(state.myHandyKey);
    setHandyConnectionStatus('disconnected');
    setSliderValue(el.motionDepthMinSlider, el.motionDepthMinVal, data.min_depth ?? 5);
    setSliderValue(el.motionDepthMaxSlider, el.motionDepthMaxVal, data.max_depth ?? 100);
    normalizeMotionDepthRange();
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
}
