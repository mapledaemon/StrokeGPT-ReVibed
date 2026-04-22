import { D, apiCall, clampNumber, ctx, el, setSliderValue, state } from './context.js';

function normalizeMotionSpeedLimits() {
    const a = parseInt(el.motionSpeedMinSlider.value, 10);
    const b = parseInt(el.motionSpeedMaxSlider.value, 10);
    state.motionMinSpeed = Math.min(a, b);
    state.motionMaxSpeed = Math.max(a, b);
    el.motionSpeedMinVal.textContent = `${state.motionMinSpeed}%`;
    el.motionSpeedMaxVal.textContent = `${state.motionMaxSpeed}%`;
}

export function populateMotionSettings(data = {}) {
    const timings = data.timings || {};
    setSliderValue(el.motionSpeedMinSlider, el.motionSpeedMinVal, data.min_speed ?? state.motionMinSpeed);
    setSliderValue(el.motionSpeedMaxSlider, el.motionSpeedMaxVal, data.max_speed ?? state.motionMaxSpeed);
    normalizeMotionSpeedLimits();
    el.autoMinTimeInput.value = timings.auto_min ?? el.autoMinTimeInput.value ?? 4;
    el.autoMaxTimeInput.value = timings.auto_max ?? el.autoMaxTimeInput.value ?? 7;
    el.edgingMinTimeInput.value = timings.edging_min ?? el.edgingMinTimeInput.value ?? 5;
    el.edgingMaxTimeInput.value = timings.edging_max ?? el.edgingMaxTimeInput.value ?? 8;
    el.milkingMinTimeInput.value = timings.milking_min ?? el.milkingMinTimeInput.value ?? 2.5;
    el.milkingMaxTimeInput.value = timings.milking_max ?? el.milkingMaxTimeInput.value ?? 4.5;
}

async function saveMotionSpeedLimits() {
    normalizeMotionSpeedLimits();
    const res = await apiCall('/set_speed_limits', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({min_speed: state.motionMinSpeed, max_speed: state.motionMaxSpeed}),
    });
    if (res && res.status === 'success') {
        populateMotionSettings({min_speed: res.min_speed, max_speed: res.max_speed});
        el.statusText.textContent = `Speed limits saved: ${state.motionMinSpeed}-${state.motionMaxSpeed}%.`;
    }
}

function readTimingPair(minInput, maxInput) {
    const a = clampNumber(minInput.value, 1, 60, 1);
    const b = clampNumber(maxInput.value, 1, 60, a);
    minInput.value = Math.min(a, b);
    maxInput.value = Math.max(a, b);
    return [Number(minInput.value), Number(maxInput.value)];
}

async function saveModeTimings() {
    const [autoMin, autoMax] = readTimingPair(el.autoMinTimeInput, el.autoMaxTimeInput);
    const [edgingMin, edgingMax] = readTimingPair(el.edgingMinTimeInput, el.edgingMaxTimeInput);
    const [milkingMin, milkingMax] = readTimingPair(el.milkingMinTimeInput, el.milkingMaxTimeInput);
    const data = await apiCall('/set_mode_timings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            auto_min: autoMin,
            auto_max: autoMax,
            edging_min: edgingMin,
            edging_max: edgingMax,
            milking_min: milkingMin,
            milking_max: milkingMax,
        }),
    });
    if (data && data.status === 'success') {
        populateMotionSettings({timings: data.timings});
        el.statusText.textContent = 'Mode timings saved.';
    }
}

export function resizeCanvas() {
    const bounds = el.rhythmCanvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    el.rhythmCanvas.width = Math.round(bounds.width);
    el.rhythmCanvas.height = Math.round(bounds.height);
}

export function drawHandyVisualizer(speed, depth) {
    const width = el.rhythmCanvas.width;
    const height = el.rhythmCanvas.height;
    if (width === 0 || height === 0) return;
    const barHeight = (height / 2) - 4;
    ctx.clearRect(0, 0, width, height);
    ctx.font = '12px sans-serif';
    ctx.fillStyle = 'rgba(193, 18, 31, 0.28)';
    ctx.fillRect(0, 0, width, barHeight);
    ctx.fillStyle = '#e01b2f';
    ctx.fillRect(0, 0, (speed / 100) * width, barHeight);
    ctx.fillStyle = 'white';
    ctx.fillText(`Speed: ${speed}%`, 5, barHeight / 2 + 5);
    ctx.fillStyle = 'rgba(127, 183, 163, 0.25)';
    ctx.fillRect(0, height / 2 + 4, width, barHeight);
    ctx.fillStyle = '#7fb7a3';
    ctx.fillRect(0, height / 2 + 4, (depth / 100) * width, barHeight);
    ctx.fillStyle = 'white';
    ctx.fillText(`Depth: ${depth}%`, 5, height - (barHeight / 2) + 5);
}

export function startEdgingTimer() {
    if (state.edgingTimerInterval) clearInterval(state.edgingTimerInterval);
    el.edgingTimer.style.display = 'block';
    let seconds = 0;
    state.edgingTimerInterval = setInterval(() => {
        seconds++;
        const min = Math.floor(seconds / 60).toString().padStart(2, '0');
        const sec = (seconds % 60).toString().padStart(2, '0');
        el.edgingTimer.textContent = `${min}:${sec}`;
    }, 1000);
}

export function stopEdgingTimer() {
    clearInterval(state.edgingTimerInterval);
    state.edgingTimerInterval = null;
    el.edgingTimer.style.display = 'none';
}

export async function pollMotionStatus() {
    const data = await apiCall('/get_status');
    if (!data) return;
    const emoji = {
        Curious: '\u{1F914}',
        Teasing: '\u{1F609}',
        Playful: '\u{1F61C}',
        Loving: '\u2764\uFE0F',
        Excited: '\u2728',
        Passionate: '\u{1F525}',
        Seductive: '\u{1F608}',
        Anticipatory: '\u{1F440}',
        Breathless: '\u{1F975}',
        Dominant: '\u{1F451}',
        Submissive: '\u{1F647}\u200D\u2640\uFE0F',
        Vulnerable: '\u{1F633}',
        Confident: '\u{1F60F}',
        Intimate: '\u{1F970}',
        Needy: '\u{1F97A}',
        Overwhelmed: '\u{1F92F}',
        Afterglow: '\u{1F60C}',
    }[data.mood] || '';
    el.moodDisplay.textContent = `Mood: ${data.mood} ${emoji}`;
    drawHandyVisualizer(data.speed || 0, data.depth || 0);
}

async function likeLastMove() {
    const data = await apiCall('/like_last_move', {method: 'POST'});
    if (data && data.status === 'boosted') {
        el.statusText.textContent = `Saved '${data.name}' to my memory!`;
    } else {
        el.statusText.textContent = 'Status: No active move to like.';
    }
}

export function initMotionControls({sendUserMessage}) {
    D.getElementById('like-this-move-btn').addEventListener('click', likeLastMove);
    const stopButtons = [D.getElementById('stop-auto-btn'), D.getElementById('emergency-stop-all-btn')];
    stopButtons.forEach(btn => btn.addEventListener('click', () => {
        el.imCloseBtn.style.display = 'none';
        stopEdgingTimer();
        if (btn.id === 'emergency-stop-all-btn') sendUserMessage('stop');
        else apiCall('/stop_auto_mode', {method: 'POST'});
    }));
    el.edgingModeBtn.addEventListener('click', () => {
        apiCall('/start_edging_mode', {method: 'POST'});
        el.imCloseBtn.style.display = 'block';
        startEdgingTimer();
    });
    el.imCloseBtn.addEventListener('click', () => {
        apiCall('/signal_edge', {method: 'POST'});
        el.imCloseBtn.style.transform = 'scale(0.95)';
        setTimeout(() => { el.imCloseBtn.style.transform = ''; }, 100);
    });
    el.motionSpeedMinSlider.addEventListener('input', normalizeMotionSpeedLimits);
    el.motionSpeedMaxSlider.addEventListener('input', normalizeMotionSpeedLimits);
    D.getElementById('save-motion-speed-limits').addEventListener('click', saveMotionSpeedLimits);
    D.getElementById('save-timings-btn').addEventListener('click', saveModeTimings);
    D.getElementById('start-auto-btn').addEventListener('click', () => sendUserMessage('take over'));
    D.getElementById('milking-mode-btn').addEventListener('click', () => apiCall('/start_milking_mode', {method: 'POST'}));
}
