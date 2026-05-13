import { D, apiCall, el, setStatusMessage, state } from './context.js';


const STATUS_LABELS = {
    ok: 'OK',
    warning: 'Warning',
    error: 'Needs Fix',
    skipped: 'Skipped',
    info: 'Info',
};


function createTextElement(tag, className, text) {
    const node = D.createElement(tag);
    if (className) node.className = className;
    node.textContent = text || '';
    return node;
}


function setupCheckStatusClass(status) {
    if (['ok', 'warning', 'error', 'skipped'].includes(status)) return status;
    return 'info';
}


function statusTone(status) {
    if (status === 'ok') return 'success';
    if (status === 'error') return 'error';
    if (status === 'warning' || status === 'skipped') return 'warning';
    return 'info';
}


function formatMs(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '';
    if (number >= 1000) return `${(number / 1000).toFixed(2)}s`;
    return `${Math.max(0, Math.round(number))}ms`;
}


function metricLabel(key) {
    return String(key || '')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, letter => letter.toUpperCase());
}


function createSetupCheckRow(item = {}) {
    const status = setupCheckStatusClass(item.status);
    const row = D.createElement('div');
    row.className = `setup-check-row ${status}`;

    const badge = createTextElement('span', `setup-check-badge ${status}`, STATUS_LABELS[status] || STATUS_LABELS.info);
    const body = D.createElement('div');
    body.className = 'setup-check-row-body';
    body.appendChild(createTextElement('div', 'setup-check-row-label', item.label || 'Check'));
    body.appendChild(createTextElement('div', 'setup-check-row-detail', item.detail || 'No detail reported.'));

    row.appendChild(badge);
    row.appendChild(body);
    return row;
}


function createLatencyRow(test = {}) {
    const status = setupCheckStatusClass(test.status);
    const row = D.createElement('div');
    row.className = `latency-test-row ${status}`;

    row.appendChild(createTextElement('span', `setup-check-badge ${status}`, STATUS_LABELS[status] || STATUS_LABELS.info));

    const body = D.createElement('div');
    body.className = 'latency-test-body';
    body.appendChild(createTextElement('div', 'latency-test-label', test.label || 'Latency check'));
    body.appendChild(createTextElement('div', 'latency-test-detail', test.detail || 'No detail reported.'));

    const metrics = test.metrics || {};
    const metricEntries = Object.entries(metrics)
        .filter(([, value]) => value !== null && value !== undefined && value !== '');
    if (metricEntries.length) {
        const metricList = D.createElement('div');
        metricList.className = 'latency-metric-list';
        metricEntries.forEach(([key, value]) => {
            metricList.appendChild(createTextElement('span', 'latency-metric', `${metricLabel(key)}: ${value}`));
        });
        body.appendChild(metricList);
    }
    row.appendChild(body);

    const elapsed = formatMs(test.elapsed_ms);
    row.appendChild(createTextElement('div', 'latency-test-elapsed', elapsed));
    return row;
}


function createSummaryMetric(label, value) {
    return createTextElement('span', 'latency-metric', `${label}: ${value}`);
}


function renderMotionCaptureSummary(capture = {}) {
    const root = el.motionCaptureResults;
    if (!root) return;
    const summary = capture.summary || {};
    root.replaceChildren();
    root.appendChild(createTextElement(
        'div',
        `setup-check-summary ${setupCheckStatusClass(summary.status)}`,
        summary.message || 'Motion transport capture ready.',
    ));

    const metricList = D.createElement('div');
    metricList.className = 'latency-metric-list';
    metricList.appendChild(createSummaryMetric('Trace rows', summary.trace_rows ?? 0));
    metricList.appendChild(createSummaryMetric('Commands', summary.command_rows ?? 0));
    metricList.appendChild(createSummaryMetric('HSP', summary.hsp_commands ?? 0));
    metricList.appendChild(createSummaryMetric('HDSP', summary.hdsp_commands ?? 0));
    metricList.appendChild(createSummaryMetric('HAMP/mode', summary.hamp_or_mode_commands ?? 0));
    metricList.appendChild(createSummaryMetric('Failed', summary.failed_commands ?? 0));
    root.appendChild(metricList);

    const pathEntries = Object.entries(summary.path_counts || {});
    if (pathEntries.length) {
        const pathList = D.createElement('div');
        pathList.className = 'latency-metric-list motion-capture-path-list';
        pathEntries.forEach(([path, count]) => {
            pathList.appendChild(createSummaryMetric(path || 'unknown', count));
        });
        root.appendChild(pathList);
    }
}


export function renderMotionTransportCapture(payload = {}) {
    const capture = payload.capture || {};
    state.motionTransportCapture = capture;
    state.motionTransportCaptureActive = Boolean(payload.active);

    renderMotionCaptureSummary(capture);
    if (el.motionCaptureOutput) {
        el.motionCaptureOutput.textContent = Object.keys(capture).length
            ? JSON.stringify(capture, null, 2)
            : 'No motion transport capture recorded.';
    }
    if (el.startMotionCaptureBtn) el.startMotionCaptureBtn.disabled = state.motionTransportCaptureActive;
    if (el.finishMotionCaptureBtn) el.finishMotionCaptureBtn.disabled = !state.motionTransportCaptureActive;
    if (el.downloadMotionCaptureBtn) {
        el.downloadMotionCaptureBtn.disabled = !capture || !Object.keys(capture).length;
    }
}


export function renderSetupCheckResults(payload = {}) {
    const root = el.setupCheckResults;
    if (!root) return;
    const summary = payload.summary || {};
    const sections = payload.sections || [];
    root.replaceChildren();

    root.appendChild(createTextElement(
        'div',
        `setup-check-summary ${setupCheckStatusClass(summary.status)}`,
        summary.message || 'Setup check completed.',
    ));

    const list = D.createElement('div');
    list.className = 'setup-check-list';
    sections.forEach(section => {
        const sectionNode = D.createElement('section');
        sectionNode.className = 'setup-check-section';
        sectionNode.appendChild(createTextElement('h3', '', section.title || 'Checks'));
        (section.items || []).forEach(item => sectionNode.appendChild(createSetupCheckRow(item)));
        list.appendChild(sectionNode);
    });
    root.appendChild(list);
}


export function renderLatencyResults(payload = {}) {
    const root = el.latencyTestResults;
    if (!root) return;
    const summary = payload.summary || {};
    root.replaceChildren();
    root.appendChild(createTextElement(
        'div',
        `setup-check-summary ${setupCheckStatusClass(summary.status)}`,
        summary.message || 'Latency diagnostics completed.',
    ));

    const list = D.createElement('div');
    list.className = 'latency-test-list';
    (payload.tests || []).forEach(test => list.appendChild(createLatencyRow(test)));
    root.appendChild(list);
}


function motionCaptureDownloadName(capture = {}) {
    const run = capture.run || {};
    const pattern = String(run.active_mode || run.backend || 'motion').replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    return `strokegpt-motion-${pattern || 'capture'}-${stamp}.json`;
}


export function downloadMotionTransportCapture() {
    const capture = state.motionTransportCapture;
    if (!capture || !Object.keys(capture).length) return;
    const blob = new Blob([JSON.stringify(capture, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = D.createElement('a');
    link.href = url;
    link.download = motionCaptureDownloadName(capture);
    D.body.appendChild(link);
    link.click();
    if (typeof link.remove === 'function') link.remove();
    else if (link.parentNode) link.parentNode.removeChild(link);
    URL.revokeObjectURL(url);
}


export async function runMotionTransportCapture(action) {
    const normalizedAction = action === 'finish' ? 'finish' : 'start';
    setStatusMessage(
        el.motionCaptureStatus,
        normalizedAction === 'finish' ? 'Stopping motion capture...' : 'Starting motion capture...',
        'info',
    );
    if (el.startMotionCaptureBtn) el.startMotionCaptureBtn.disabled = true;
    if (el.finishMotionCaptureBtn) el.finishMotionCaptureBtn.disabled = true;
    const payload = await apiCall('/motion_transport_capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: normalizedAction }),
    });
    if (!payload) {
        setStatusMessage(el.motionCaptureStatus, 'Motion capture failed.', 'error');
        if (el.startMotionCaptureBtn) el.startMotionCaptureBtn.disabled = state.motionTransportCaptureActive;
        if (el.finishMotionCaptureBtn) el.finishMotionCaptureBtn.disabled = !state.motionTransportCaptureActive;
        return;
    }
    renderMotionTransportCapture(payload);
    setStatusMessage(
        el.motionCaptureStatus,
        payload.message || (normalizedAction === 'finish' ? 'Motion capture stopped.' : 'Motion capture started.'),
        statusTone(payload.capture?.summary?.status || (payload.status === 'started' ? 'info' : 'ok')),
    );
}


export async function runSetupCheck() {
    setStatusMessage(el.setupCheckStatus, 'Running setup checks...', 'info');
    el.setupCheckResults?.replaceChildren(
        createTextElement('div', 'setup-check-summary info', 'Checking local setup...'),
    );
    if (el.runSetupCheckBtn) el.runSetupCheckBtn.disabled = true;
    const payload = await apiCall('/setup_check');
    if (!payload) {
        el.setupCheckResults?.replaceChildren(
            createTextElement('div', 'setup-check-summary error', 'Setup check failed. Confirm the backend is still running.'),
        );
        setStatusMessage(el.setupCheckStatus, 'Setup check failed.', 'error');
        if (el.runSetupCheckBtn) el.runSetupCheckBtn.disabled = false;
        return;
    }
    renderSetupCheckResults(payload);
    const summaryStatus = payload.summary?.status;
    const inlineMessage = summaryStatus === 'error'
        ? 'Review items marked Needs Fix below.'
        : summaryStatus === 'warning'
            ? 'Review warnings below.'
            : 'Setup check completed.';
    setStatusMessage(el.setupCheckStatus, inlineMessage, statusTone(summaryStatus));
    if (el.runSetupCheckBtn) el.runSetupCheckBtn.disabled = false;
}


export async function runLatencyDiagnostics() {
    setStatusMessage(el.latencyTestStatus, 'Running latency tests...', 'info');
    el.latencyTestResults?.replaceChildren(
        createTextElement('div', 'setup-check-summary info', 'Measuring local runtime paths...'),
    );
    if (el.runLatencyTestsBtn) el.runLatencyTestsBtn.disabled = true;
    const payload = await apiCall('/diagnostics_latency', { method: 'POST' });
    if (!payload) {
        el.latencyTestResults?.replaceChildren(
            createTextElement('div', 'setup-check-summary error', 'Latency tests failed. Confirm the backend is still running.'),
        );
        setStatusMessage(el.latencyTestStatus, 'Latency tests failed.', 'error');
        if (el.runLatencyTestsBtn) el.runLatencyTestsBtn.disabled = false;
        return;
    }
    renderLatencyResults(payload);
    setStatusMessage(el.latencyTestStatus, payload.summary?.message || 'Latency diagnostics completed.', statusTone(payload.summary?.status));
    if (el.runLatencyTestsBtn) el.runLatencyTestsBtn.disabled = false;
}


export function initDiagnosticsControls() {
    el.runSetupCheckBtn?.addEventListener('click', runSetupCheck);
    el.runLatencyTestsBtn?.addEventListener('click', runLatencyDiagnostics);
    el.startMotionCaptureBtn?.addEventListener('click', () => runMotionTransportCapture('start'));
    el.finishMotionCaptureBtn?.addEventListener('click', () => runMotionTransportCapture('finish'));
    el.downloadMotionCaptureBtn?.addEventListener('click', downloadMotionTransportCapture);
}
