import { D, apiCall, el, setStatusMessage } from './context.js';


const STATUS_LABELS = {
    ok: 'OK',
    warning: 'Warning',
    error: 'Needs Fix',
    info: 'Info',
};


function createTextElement(tag, className, text) {
    const node = D.createElement(tag);
    if (className) node.className = className;
    node.textContent = text || '';
    return node;
}


function setupCheckStatusClass(status) {
    if (status === 'ok' || status === 'warning' || status === 'error') return status;
    return 'info';
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


function closeSetupCheckWizard() {
    if (el.setupOverlay) el.setupOverlay.style.display = 'none';
    if (el.setupBox) el.setupBox.classList.remove('setup-check-box');
}


export function renderSetupCheckWizard(payload = {}) {
    const summary = payload.summary || {};
    const sections = payload.sections || [];
    el.setupOverlay.style.display = 'flex';
    el.setupBox.replaceChildren();
    el.setupBox.classList.add('setup-check-box');

    const title = createTextElement('h2', '', 'Setup Check Wizard');
    const summaryNode = createTextElement(
        'div',
        `setup-check-summary ${setupCheckStatusClass(summary.status)}`,
        summary.message || 'Setup check completed.',
    );
    const list = D.createElement('div');
    list.className = 'setup-check-list';
    sections.forEach(section => {
        const sectionNode = D.createElement('section');
        sectionNode.className = 'setup-check-section';
        sectionNode.appendChild(createTextElement('h3', '', section.title || 'Checks'));
        (section.items || []).forEach(item => sectionNode.appendChild(createSetupCheckRow(item)));
        list.appendChild(sectionNode);
    });

    const actions = D.createElement('div');
    actions.className = 'setup-actions';
    const refreshBtn = createTextElement('button', 'my-button', 'Refresh Checks');
    refreshBtn.type = 'button';
    refreshBtn.onclick = () => runSetupCheckWizard();
    const closeBtn = createTextElement('button', 'my-button', 'Close');
    closeBtn.type = 'button';
    closeBtn.onclick = closeSetupCheckWizard;
    actions.appendChild(refreshBtn);
    actions.appendChild(closeBtn);

    el.setupBox.appendChild(title);
    el.setupBox.appendChild(summaryNode);
    el.setupBox.appendChild(list);
    el.setupBox.appendChild(actions);
}


export async function runSetupCheckWizard() {
    el.setupOverlay.style.display = 'flex';
    el.setupBox.classList.add('setup-check-box');
    el.setupBox.replaceChildren(
        createTextElement('h2', '', 'Setup Check Wizard'),
        createTextElement('div', 'setup-check-summary info', 'Checking local setup...'),
    );
    setStatusMessage(el.setupCheckStatus, 'Running setup check...', 'info');
    const payload = await apiCall('/setup_check');
    if (!payload) {
        el.setupBox.replaceChildren(
            createTextElement('h2', '', 'Setup Check Wizard'),
            createTextElement('div', 'setup-check-summary error', 'Setup check failed. Confirm the backend is still running.'),
        );
        setStatusMessage(el.setupCheckStatus, 'Setup check failed.', 'error');
        return;
    }
    renderSetupCheckWizard(payload);
    const tone = payload.summary?.status === 'ok'
        ? 'success'
        : payload.summary?.status === 'error' ? 'error' : 'warning';
    setStatusMessage(el.setupCheckStatus, payload.summary?.message || 'Setup check completed.', tone);
}


export function initSetupCheckWizard() {
    if (!el.runSetupCheckBtn) return;
    el.runSetupCheckBtn.addEventListener('click', runSetupCheckWizard);
}
