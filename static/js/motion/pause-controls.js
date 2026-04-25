import { D, apiCall, el, state } from '../context.js';

const SHIFT_DOUBLE_TAP_MS = 350;

let lastShiftDownAt = 0;
let updateActiveModeTimerCallback = () => {};

function setActiveModeTimerCallback(callback) {
    if (typeof callback === 'function') updateActiveModeTimerCallback = callback;
}

export function updatePauseResumeUi(paused = state.motionPaused) {
    state.motionPaused = Boolean(paused);
    if (!el.pauseResumeBtn) return;
    el.pauseResumeBtn.textContent = 'Resume/Pause';
    el.pauseResumeBtn.setAttribute('aria-pressed', state.motionPaused ? 'true' : 'false');
    el.pauseResumeBtn.title = state.motionPaused
        ? 'Hotkey: Play/Pause media key to resume'
        : 'Hotkey: Play/Pause media key to pause';
}

export async function toggleMotionPause(action = 'toggle') {
    const data = await apiCall('/toggle_motion_pause', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action}),
    });
    if (data && data.status === 'success') {
        updatePauseResumeUi(data.paused);
        updateActiveModeTimerCallback(data.active_mode, data.active_mode_elapsed_seconds, data.active_mode_paused);
        el.statusText.textContent = data.paused ? 'Motion paused.' : 'Motion resumed.';
    }
}

export function closeSignalAvailable() {
    return ['edging', 'milking', 'freestyle'].includes(state.activeModeName);
}

export async function signalImClose() {
    if (!closeSignalAvailable()) {
        el.statusText.textContent = "I'm Close is available in Edge, Milk, or Freestyle.";
        return;
    }
    const data = await apiCall('/signal_edge', {method: 'POST'});
    if (data && data.status === 'signaled') {
        el.statusText.textContent = data.mode === 'milking'
            ? 'Milking mode extended.'
            : data.mode === 'freestyle'
                ? 'Freestyle close signal sent.'
            : 'Close signal sent.';
    }
    if (el.imCloseBtn) {
        el.imCloseBtn.style.transform = 'scale(0.95)';
        setTimeout(() => { el.imCloseBtn.style.transform = ''; }, 100);
    }
}

export function stopMotion(sendUserMessage, emergency = false) {
    if (el.imCloseBtn) el.imCloseBtn.style.display = 'none';
    updatePauseResumeUi(false);
    updateActiveModeTimerCallback('', null, false);
    if (emergency) sendUserMessage('stop');
    else apiCall('/stop_auto_mode', {method: 'POST'});
}

export function handleMotionHotkey(event, sendUserMessage) {
    if (event.repeat) return;
    if (event.key === 'MediaPlayPause' || event.key === 'MediaPause' || event.key === 'MediaPlay') {
        event.preventDefault();
        const action = event.key === 'MediaPause' ? 'pause' : event.key === 'MediaPlay' ? 'resume' : 'toggle';
        toggleMotionPause(action);
        return;
    }
    if (event.key === 'MediaStop') {
        event.preventDefault();
        stopMotion(sendUserMessage, true);
        return;
    }
    if (event.key !== 'Shift' || event.ctrlKey || event.altKey || event.metaKey) return;
    const now = Date.now();
    if (lastShiftDownAt && now - lastShiftDownAt <= SHIFT_DOUBLE_TAP_MS) {
        event.preventDefault();
        lastShiftDownAt = 0;
        signalImClose();
        return;
    }
    lastShiftDownAt = now;
}

export function bindMotionPauseControls({sendUserMessage, updateActiveModeTimer, closeMotionTrainingWorkspace}) {
    setActiveModeTimerCallback(updateActiveModeTimer);
    const stopButtons = [D.getElementById('stop-auto-btn'), D.getElementById('emergency-stop-all-btn')];
    stopButtons.forEach(btn => btn.addEventListener('click', () => {
        stopMotion(sendUserMessage, btn.id === 'emergency-stop-all-btn');
    }));
    el.pauseResumeBtn?.addEventListener('click', () => toggleMotionPause());
    el.imCloseBtn.addEventListener('click', signalImClose);
    D.addEventListener('keydown', event => {
        if (event.key === 'Escape' && el.motionTrainingDialog?.classList.contains('open')) closeMotionTrainingWorkspace();
        handleMotionHotkey(event, sendUserMessage);
    });
    updatePauseResumeUi(false);
}
