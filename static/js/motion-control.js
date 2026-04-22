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
    if (data.motion_patterns) renderMotionPatterns(data.motion_patterns);
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

function formatPatternDuration(durationMs) {
    const duration = Math.max(0, Number(durationMs) || 0);
    if (duration >= 1000) return `${(duration / 1000).toFixed(duration >= 10_000 ? 0 : 1)}s`;
    return `${Math.round(duration)}ms`;
}

function setPatternStatus(message, color = 'var(--comment)') {
    if (!el.motionPatternStatus) return;
    el.motionPatternStatus.textContent = message;
    el.motionPatternStatus.style.color = color;
}

export function renderMotionPatterns(catalog = {}) {
    if (!el.motionPatternList) return;
    const patterns = Array.isArray(catalog.patterns) ? catalog.patterns : [];
    state.motionPatterns = patterns;
    el.motionPatternList.replaceChildren();

    if (!patterns.length) {
        setPatternStatus('No motion patterns found.', 'var(--yellow)');
        return;
    }

    patterns.forEach(pattern => {
        const row = D.createElement('div');
        row.className = 'motion-pattern-row';

        const main = D.createElement('label');
        main.className = 'motion-pattern-main';

        const checkbox = D.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = Boolean(pattern.enabled);
        checkbox.dataset.patternId = pattern.id;
        checkbox.addEventListener('change', async () => {
            checkbox.disabled = true;
            await setMotionPatternEnabled(pattern.id, checkbox.checked);
            checkbox.disabled = false;
        });

        const text = D.createElement('div');
        text.className = 'motion-pattern-text';

        const name = D.createElement('div');
        name.className = 'motion-pattern-name';
        name.textContent = pattern.name || pattern.id || 'Unnamed pattern';

        const meta = D.createElement('div');
        meta.className = 'motion-pattern-meta';
        meta.textContent = [
            pattern.source || 'unknown',
            `${formatPatternDuration(pattern.duration_ms)} duration`,
            `${pattern.action_count || 0} actions`,
            pattern.readonly ? 'read-only' : 'editable file',
        ].join(' | ');

        text.append(name, meta);
        if (pattern.description) {
            const description = D.createElement('div');
            description.className = 'motion-pattern-description';
            description.textContent = pattern.description;
            text.appendChild(description);
        }

        const exportButton = D.createElement('button');
        exportButton.type = 'button';
        exportButton.className = 'my-button motion-pattern-export';
        exportButton.textContent = 'Export';
        exportButton.addEventListener('click', () => {
            window.location.href = `/motion_patterns/${encodeURIComponent(pattern.id)}/export`;
        });

        main.append(checkbox, text);
        row.append(main, exportButton);
        el.motionPatternList.appendChild(row);
    });

    const errors = Array.isArray(catalog.errors) ? catalog.errors : [];
    if (errors.length) {
        setPatternStatus(`Loaded ${patterns.length} patterns. ${errors.length} file issue(s) need attention.`, 'var(--yellow)');
    } else {
        setPatternStatus(`Loaded ${patterns.length} patterns.`, 'var(--cyan)');
    }
}

export async function refreshMotionPatterns() {
    setPatternStatus('Loading motion patterns...');
    const data = await apiCall('/motion_patterns');
    if (data) renderMotionPatterns(data);
    return data;
}

async function setMotionPatternEnabled(patternId, enabled) {
    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}/enabled`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled}),
    });
    if (data && data.status === 'success') {
        renderMotionPatterns(data.motion_patterns);
        el.statusText.textContent = `${data.pattern.name} pattern ${data.pattern.enabled ? 'enabled' : 'disabled'}.`;
    }
}

async function importMotionPatternFile(file) {
    if (!file) return;
    setPatternStatus(`Importing ${file.name}...`);
    const body = new FormData();
    body.append('pattern', file);
    try {
        const response = await fetch('/import_motion_pattern', {method: 'POST', body});
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.status !== 'success') {
            const message = data.message || `Could not import ${file.name}.`;
            setPatternStatus(message, 'var(--yellow)');
            el.statusText.textContent = message;
            return;
        }
        el.statusText.textContent = `Imported pattern: ${data.pattern.name}.`;
        await refreshMotionPatterns();
    } catch (error) {
        const message = `Import failed: ${error.message}`;
        setPatternStatus(message, 'var(--yellow)');
        el.statusText.textContent = message;
    } finally {
        el.motionPatternImportInput.value = '';
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
    el.refreshMotionPatternsBtn.addEventListener('click', refreshMotionPatterns);
    el.importMotionPatternBtn.addEventListener('click', () => el.motionPatternImportInput.click());
    el.motionPatternImportInput.addEventListener('change', event => importMotionPatternFile(event.target.files[0]));
    el.settingsTabs.forEach(tab => {
        if (tab.dataset.settingsTab === 'motion') tab.addEventListener('click', refreshMotionPatterns);
    });
    D.getElementById('start-auto-btn').addEventListener('click', () => sendUserMessage('take over'));
    D.getElementById('milking-mode-btn').addEventListener('click', () => apiCall('/start_milking_mode', {method: 'POST'}));
    refreshMotionPatterns();
}
