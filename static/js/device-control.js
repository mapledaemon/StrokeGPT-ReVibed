import { apiCall, el, setSliderValue, state } from './context.js';

function normalizeMotionDepthRange() {
    const a = parseInt(el.motionDepthMinSlider.value, 10);
    const b = parseInt(el.motionDepthMaxSlider.value, 10);
    state.motionMinDepth = Math.min(a, b);
    state.motionMaxDepth = Math.max(a, b);
    el.motionDepthMinVal.textContent = `${state.motionMinDepth}%`;
    el.motionDepthMaxVal.textContent = `${state.motionMaxDepth}%`;
}

export function populateDeviceSettings(data = {}) {
    el.handyKeyInput.value = data.handy_key || state.myHandyKey || '';
    setSliderValue(el.motionDepthMinSlider, el.motionDepthMinVal, data.min_depth ?? 5);
    setSliderValue(el.motionDepthMaxSlider, el.motionDepthMaxVal, data.max_depth ?? 100);
    normalizeMotionDepthRange();
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

async function saveHandyConnectionKey() {
    const key = el.handyKeyInput.value.trim();
    if (!key) {
        el.handyKeyStatus.textContent = 'Enter a Handy connection key first.';
        el.handyKeyStatus.style.color = 'var(--yellow)';
        return;
    }
    const res = await apiCall('/set_handy_key', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key}),
    });
    if (res && res.status === 'success') {
        state.myHandyKey = key;
        el.handyKeyStatus.textContent = 'Connection key saved.';
        el.handyKeyStatus.style.color = 'var(--cyan)';
        el.statusText.textContent = 'Handy connection key saved.';
    }
}

export function initDeviceControls() {
    el.saveHandyKeyBtn.addEventListener('click', saveHandyConnectionKey);
    el.motionDepthMinSlider.addEventListener('input', normalizeMotionDepthRange);
    el.motionDepthMaxSlider.addEventListener('input', normalizeMotionDepthRange);
    el.motionDepthMinSlider.addEventListener('change', testMotionDepthRange);
    el.motionDepthMaxSlider.addEventListener('change', testMotionDepthRange);
    document.getElementById('test-motion-depth-range').addEventListener('click', testMotionDepthRange);
    document.getElementById('save-motion-depth-range').addEventListener('click', saveMotionDepthRange);
}
