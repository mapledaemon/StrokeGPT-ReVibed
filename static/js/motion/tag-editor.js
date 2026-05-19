import { state } from '../context.js';

export function normalizeMotionTagList(tags) {
    const raw = Array.isArray(tags) ? tags : String(tags || '').split(',');
    const seen = new Set();
    const clean = [];
    raw.forEach(tag => {
        const text = String(tag || '').trim().replace(/\s+/g, ' ').toLowerCase();
        if (!text || seen.has(text)) return;
        seen.add(text);
        clean.push(text);
    });
    return clean;
}

export function updateMotionTagSuggestions(catalog = {}) {
    const suggestions = normalizeMotionTagList(catalog.tag_suggestions || []);
    if (suggestions.length) state.motionTagSuggestions = suggestions;
    return state.motionTagSuggestions;
}

export function tagPromptMessage(kind = 'Pattern') {
    const suggestions = normalizeMotionTagList(state.motionTagSuggestions || []);
    if (!suggestions.length) return `${kind} tags, comma-separated`;
    return `${kind} tags, comma-separated\nSuggestions: ${suggestions.join(', ')}`;
}
