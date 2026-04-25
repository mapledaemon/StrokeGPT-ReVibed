import { D, apiCall, el, state } from '../context.js';

let renderMotionPatternsCallback = () => {};

export function configureMotionFeedbackControls({renderMotionPatterns} = {}) {
    if (typeof renderMotionPatterns === 'function') renderMotionPatternsCallback = renderMotionPatterns;
}

function feedbackRatingLabel(rating) {
    if (rating === 'thumbs_up') return 'thumbs up';
    if (rating === 'thumbs_down') return 'thumbs down';
    if (rating === 'neutral') return 'neutral';
    if (rating === 'reset') return 'reset';
    return 'feedback';
}

export function renderMotionFeedbackHistory(history = []) {
    if (!el.motionFeedbackHistory) return;
    el.motionFeedbackHistory.replaceChildren();

    const entries = Array.isArray(history) ? history.slice(0, 5) : [];
    const title = D.createElement('div');
    title.className = 'motion-feedback-history-title';
    title.textContent = 'Recent feedback';
    el.motionFeedbackHistory.appendChild(title);

    if (!entries.length) {
        const empty = D.createElement('div');
        empty.className = 'motion-feedback-history-empty';
        empty.textContent = 'No recent pattern feedback.';
        el.motionFeedbackHistory.appendChild(empty);
        return;
    }

    entries.forEach(entry => {
        const row = D.createElement('div');
        row.className = 'motion-feedback-history-row';
        const name = entry.pattern_name || entry.pattern_id || 'pattern';
        const rating = feedbackRatingLabel(entry.rating);
        const source = entry.source || 'feedback';
        const weight = Number.isFinite(Number(entry.weight)) ? `, weight ${entry.weight}` : '';
        row.textContent = `${name}: ${rating} from ${source}${weight}`;
        el.motionFeedbackHistory.appendChild(row);
    });
}

export async function saveMotionFeedbackOptions() {
    const data = await apiCall('/motion_feedback_options', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({auto_disable: Boolean(el.motionFeedbackAutoDisableCheckbox?.checked)}),
    });
    if (data && data.status === 'success') {
        state.motionFeedbackAutoDisable = Boolean(data.motion_feedback_auto_disable);
        if (el.motionFeedbackAutoDisableCheckbox) el.motionFeedbackAutoDisableCheckbox.checked = state.motionFeedbackAutoDisable;
        if (data.motion_patterns) renderMotionPatternsCallback(data.motion_patterns);
        el.statusText.textContent = state.motionFeedbackAutoDisable
            ? 'Repeated thumbs down can disable patterns.'
            : 'Repeated thumbs down will not disable patterns.';
    }
}
