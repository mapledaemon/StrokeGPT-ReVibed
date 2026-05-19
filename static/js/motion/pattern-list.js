import { D, apiCall, clampNumber, el, markRequiresBackend, reportSaveFailure, state } from '../context.js';
import { normalizeMotionTagList, tagPromptMessage } from './tag-editor.js';

const TRASH_ICON = '<svg aria-hidden="true" focusable="false" viewBox="0 0 24 24"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-.7 11H7.7L7 9Zm3 2v7h2v-7h-2Zm3 0v7h2v-7h-2Z"></path></svg>';

let renderMotionPatternsCallback = () => {};
let setMotionTrainingDetailCallback = () => {};

export function configureMotionPatternList({renderMotionPatterns, setMotionTrainingDetail} = {}) {
    if (typeof renderMotionPatterns === 'function') renderMotionPatternsCallback = renderMotionPatterns;
    if (typeof setMotionTrainingDetail === 'function') setMotionTrainingDetailCallback = setMotionTrainingDetail;
}

export function formatPatternDuration(durationMs) {
    const duration = Math.max(0, Number(durationMs) || 0);
    if (duration >= 1000) return `${(duration / 1000).toFixed(duration >= 10_000 ? 0 : 1)}s`;
    return `${Math.round(duration)}ms`;
}

export function setPatternStatus(message, color = 'var(--comment)') {
    if (!el.motionPatternStatus) return;
    el.motionPatternStatus.textContent = message;
    el.motionPatternStatus.style.color = color;
}

export function patternDisplayName(pattern) {
    return pattern.name || pattern.id || 'Unnamed pattern';
}

function patternFeedbackCounts(pattern) {
    const feedback = pattern.feedback || {};
    return {
        thumbsUp: Number(feedback.thumbs_up) || 0,
        neutral: Number(feedback.neutral) || 0,
        thumbsDown: Number(feedback.thumbs_down) || 0,
    };
}

export function patternHasFeedbackState(pattern) {
    const counts = patternFeedbackCounts(pattern);
    return counts.thumbsUp + counts.neutral + counts.thumbsDown > 0
        || (pattern.source === 'fixed' && Number(pattern.weight) !== 50);
}

function formatPatternFeedback(pattern) {
    const counts = patternFeedbackCounts(pattern);
    return `feedback +${counts.thumbsUp} / ${counts.neutral} / -${counts.thumbsDown}`;
}

function formatPatternTags(pattern) {
    const tags = Array.isArray(pattern.tags) ? pattern.tags.map(tag => String(tag).trim()).filter(Boolean) : [];
    return tags.length ? `tags ${tags.join(', ')}` : '';
}

export function formatPatternMetadata(pattern, {compact = false} = {}) {
    const parts = compact
        ? [
            pattern.source || 'unknown',
            formatPatternDuration(pattern.duration_ms),
            `${pattern.action_count || 0} actions`,
        ]
        : [
            pattern.source || 'unknown',
            `${formatPatternDuration(pattern.duration_ms)} duration`,
            `${pattern.action_count || 0} actions`,
            pattern.readonly ? 'read-only' : 'editable file',
            formatPatternFeedback(pattern),
        ];
    if (pattern.source === 'fixed') parts.push(`weight ${pattern.weight ?? 50}/100`);
    if (!pattern.enabled) parts.push('disabled');
    const tags = formatPatternTags(pattern);
    if (tags) parts.push(tags);
    return parts.join(' | ');
}

export function createPatternText(pattern, {includeDescription = true, compactMetadata = false} = {}) {
    const text = D.createElement('div');
    text.className = 'motion-pattern-text';

    const name = D.createElement('div');
    name.className = 'motion-pattern-name';
    name.textContent = patternDisplayName(pattern);

    const meta = D.createElement('div');
    meta.className = 'motion-pattern-meta';
    meta.textContent = formatPatternMetadata(pattern, {compact: compactMetadata});

    text.append(name, meta);
    if (includeDescription && pattern.description) {
        const description = D.createElement('div');
        description.className = 'motion-pattern-description';
        description.textContent = pattern.description;
        text.appendChild(description);
    }
    return text;
}

export function createPatternExportButton(pattern) {
    const exportButton = D.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'my-button motion-pattern-export';
    exportButton.textContent = 'Export';
    exportButton.addEventListener('click', event => {
        event.stopPropagation();
        window.location.href = `/motion_patterns/${encodeURIComponent(pattern.id)}/export`;
    });
    return exportButton;
}

export function createPatternTagsButton(pattern) {
    const tagsButton = D.createElement('button');
    tagsButton.type = 'button';
    tagsButton.className = 'my-button motion-pattern-tags';
    tagsButton.textContent = 'Tags';
    markRequiresBackend(tagsButton);
    const readonly = Boolean(pattern.readonly || pattern.source === 'fixed');
    tagsButton.disabled = readonly;
    tagsButton.title = readonly
        ? 'Built-in pattern tags are read-only.'
        : `Edit tags for ${patternDisplayName(pattern)}`;
    tagsButton.addEventListener('click', event => {
        event.stopPropagation?.();
        const current = Array.isArray(pattern.tags) ? pattern.tags.join(', ') : '';
        const next = window.prompt?.(tagPromptMessage('Pattern'), current);
        if (next === null || next === undefined) return;
        setMotionPatternTags(pattern.id, next);
    });
    return tagsButton;
}

export function createPatternFeedbackResetButton(pattern) {
    const resetButton = D.createElement('button');
    resetButton.type = 'button';
    resetButton.className = 'my-button motion-pattern-feedback-reset';
    resetButton.textContent = 'Reset';
    markRequiresBackend(resetButton);
    resetButton.addEventListener('click', event => {
        event.stopPropagation();
        resetMotionPatternFeedback(pattern.id);
    });
    return resetButton;
}

export function createPatternDeleteButton(pattern) {
    const deleteButton = D.createElement('button');
    deleteButton.type = 'button';
    deleteButton.className = 'my-button ollama-model-action ollama-model-delete motion-pattern-delete';
    deleteButton.innerHTML = TRASH_ICON;
    markRequiresBackend(deleteButton);
    const readonly = Boolean(pattern.readonly || pattern.source === 'fixed');
    deleteButton.disabled = readonly;
    deleteButton.title = readonly
        ? 'Built-in patterns can be disabled, not deleted.'
        : `Delete ${patternDisplayName(pattern)}`;
    deleteButton.setAttribute('aria-label', `Delete ${patternDisplayName(pattern)}`);
    deleteButton.addEventListener('click', event => {
        event.stopPropagation();
        deleteMotionPattern(pattern);
    });
    return deleteButton;
}

function createPatternWeightControl(pattern) {
    const wrapper = D.createElement('div');
    wrapper.className = 'motion-pattern-weight-control';
    wrapper.addEventListener('click', event => event.stopPropagation());

    const label = D.createElement('div');
    label.className = 'motion-pattern-weight-label';
    label.textContent = 'Weight';

    const field = D.createElement('div');
    field.className = 'motion-training-number-field motion-pattern-weight-field';

    const input = D.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.max = '100';
    input.step = '1';
    input.value = clampNumber(pattern.weight, 0, 100, 50);
    input.setAttribute('aria-label', `${patternDisplayName(pattern)} LLM weight`);
    markRequiresBackend(input);
    input.addEventListener('change', () => setMotionPatternWeight(pattern.id, input.value));
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
            event.preventDefault();
            input.blur();
            setMotionPatternWeight(pattern.id, input.value);
        }
    });

    const stepper = D.createElement('div');
    stepper.className = 'motion-training-number-stepper';
    [
        ['motion-training-number-step-up', 1, 'Increase LLM weight'],
        ['motion-training-number-step-down', -1, 'Decrease LLM weight'],
    ].forEach(([className, delta, ariaLabel]) => {
        const button = D.createElement('button');
        button.type = 'button';
        button.className = `motion-training-number-step ${className}`;
        button.setAttribute('aria-label', `${ariaLabel} for ${patternDisplayName(pattern)}`);
        markRequiresBackend(button);
        button.addEventListener('click', () => {
            input.value = Math.round(clampNumber(Number(input.value) + delta, 0, 100, 50));
            setMotionPatternWeight(pattern.id, input.value);
        });
        stepper.appendChild(button);
    });

    field.append(input, stepper);
    wrapper.append(label, field);
    return wrapper;
}

export function patternById(patternId) {
    return state.motionPatterns.find(pattern => pattern.id === patternId);
}

export function clonePattern(pattern) {
    return pattern ? JSON.parse(JSON.stringify(pattern)) : null;
}

export function normalizedActions(actions) {
    return (Array.isArray(actions) ? actions : [])
        .map(action => ({
            at: Math.max(0, Math.round(Number(action.at) || 0)),
            pos: clampNumber(action.pos, 0, 100, 50),
        }))
        .filter(action => Number.isFinite(action.at) && Number.isFinite(action.pos))
        .sort((a, b) => a.at - b.at)
        .filter((action, index, all) => index === all.length - 1 || action.at !== all[index + 1].at);
}

export function updatePatternStats(pattern) {
    if (!pattern) return null;
    const actions = normalizedActions(pattern?.actions);
    const duration = actions.length > 1 ? actions[actions.length - 1].at - actions[0].at : 0;
    return {
        ...pattern,
        actions,
        action_count: actions.length,
        duration_ms: Math.max(0, duration),
    };
}

export function renderCompactMotionPatternList(patterns) {
    if (!el.motionPatternList) return;
    el.motionPatternList.replaceChildren();

    if (!patterns.length) {
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
        markRequiresBackend(checkbox);
        checkbox.addEventListener('change', async () => {
            checkbox.disabled = true;
            await setMotionPatternEnabled(pattern.id, checkbox.checked);
            checkbox.disabled = false;
        });

        const text = createPatternText(pattern);

        const actions = D.createElement('div');
        actions.className = 'motion-pattern-row-actions';

        if (pattern.source === 'fixed') actions.append(createPatternWeightControl(pattern));
        if (patternHasFeedbackState(pattern)) actions.append(createPatternFeedbackResetButton(pattern));
        actions.append(createPatternTagsButton(pattern));
        actions.append(createPatternExportButton(pattern));
        actions.append(createPatternDeleteButton(pattern));
        main.append(checkbox, text);
        row.append(main, actions);
        el.motionPatternList.appendChild(row);
    });
}

export async function setMotionPatternEnabled(patternId, enabled) {
    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}/enabled`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({enabled}),
    });
    if (data && data.status === 'success') {
        renderMotionPatternsCallback(data.motion_patterns);
        el.statusText.textContent = `${data.pattern.name} pattern ${data.pattern.enabled ? 'enabled' : 'disabled'}.`;
    } else {
        reportSaveFailure(el.motionPatternStatus, data, 'Could not change pattern enablement.');
    }
}

export async function setMotionPatternWeight(patternId, weight) {
    const cleanWeight = Math.round(clampNumber(weight, 0, 100, 50));
    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}/weight`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({weight: cleanWeight}),
    });
    if (data && data.status === 'success') {
        renderMotionPatternsCallback(data.motion_patterns);
        el.statusText.textContent = `${data.pattern.name} LLM weight saved: ${data.pattern.weight}.`;
    } else {
        reportSaveFailure(el.motionPatternStatus, data, 'Could not save pattern weight.');
    }
}

export async function resetMotionPatternFeedback(patternId) {
    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}/feedback/reset`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({}),
    });
    if (data && data.status === 'success') {
        renderMotionPatternsCallback(data.motion_patterns);
        if (data.pattern && data.pattern.id === state.motionTrainingSelectedPatternId) {
            setMotionTrainingDetailCallback(data.pattern);
        }
        el.statusText.textContent = data.message || 'Pattern feedback reset.';
    } else {
        reportSaveFailure(el.motionPatternStatus, data, 'Could not reset pattern feedback.');
    }
}

export async function setMotionPatternTags(patternId, tags) {
    const tagList = normalizeMotionTagList(tags);
    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}/tags`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({tags: tagList}),
    });
    if (data && data.status === 'success') {
        renderMotionPatternsCallback(data.motion_patterns);
        if (data.pattern && data.pattern.id === state.motionTrainingSelectedPatternId) {
            setMotionTrainingDetailCallback(data.pattern);
        }
        el.statusText.textContent = data.message || 'Pattern tags updated.';
    } else {
        reportSaveFailure(el.motionPatternStatus, data, 'Could not update pattern tags.');
    }
    return data;
}

export async function deleteMotionPattern(pattern) {
    const patternId = String(pattern?.id || '').trim();
    const name = patternDisplayName(pattern || {});
    if (!patternId) return;
    if (!window.confirm(`Delete ${name} from Motion Patterns?`)) return;

    const data = await apiCall(`/motion_patterns/${encodeURIComponent(patternId)}`, {method: 'DELETE'});
    if (data && data.status === 'success') {
        renderMotionPatternsCallback(data.motion_patterns);
        if (state.motionTrainingSelectedPatternId === patternId) {
            state.motionTrainingSelectedPatternId = '';
            setMotionTrainingDetailCallback(null);
        }
        el.statusText.textContent = data.message || `Deleted ${name}.`;
    } else {
        reportSaveFailure(el.motionPatternStatus, data, `Could not delete ${name}.`);
    }
}
