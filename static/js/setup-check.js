import { D, apiCall, el, setStatusMessage } from './context.js';


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
    setStatusMessage(el.setupCheckStatus, payload.summary?.message || 'Setup check completed.', statusTone(payload.summary?.status));
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
}
