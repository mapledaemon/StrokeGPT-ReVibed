import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { makeStandaloneStubElement } from './_harness.mjs';
import { appendMessageText } from '../../static/js/chat.js';


function collectText(node) {
    if (!node || typeof node !== 'object') return '';
    let text = node.textContent || '';
    for (const child of node.children || []) text += collectText(child);
    return text;
}

function childTags(node) {
    return (node.children || []).map(child => child.tagName || `#${child.nodeType}`);
}

describe('chat message rendering', () => {
    it('renders complete markdown code fences as explicit pre blocks', () => {
        const parent = makeStandaloneStubElement('div');

        appendMessageText(parent, "Before\n```python\nprint('<safe>')\n```\nAfter");

        const pre = parent.children.find(child => child.tagName === 'PRE');
        assert.ok(pre);
        assert.equal(pre.textContent, "print('<safe>')\n");
        assert.equal(collectText(parent).includes("Before"), true);
        assert.equal(collectText(parent).includes("After"), true);
        assert.deepEqual(childTags(parent).filter(tag => tag === 'PRE'), ['PRE']);
    });

    it('keeps ordinary markdown and html-like text literal', () => {
        const parent = makeStandaloneStubElement('div');

        appendMessageText(parent, "**bold** <script>alert(1)</script> `inline`");

        assert.equal(parent.children.some(child => child.tagName === 'PRE'), false);
        assert.equal(collectText(parent), "**bold** <script>alert(1)</script> `inline`");
    });

    it('leaves incomplete code fences as text for predictable partial rendering', () => {
        const parent = makeStandaloneStubElement('div');

        appendMessageText(parent, "```json\n{\"partial\": true}");

        assert.equal(parent.children.some(child => child.tagName === 'PRE'), false);
        assert.deepEqual(childTags(parent), ['#3', 'BR', '#3']);
        assert.equal(collectText(parent), "```json{\"partial\": true}");
    });

    it('keeps legacy pre-tag blocks supported without interpreting other html', () => {
        const parent = makeStandaloneStubElement('div');

        appendMessageText(parent, "A <pre><b>literal</b></pre> B");

        const pre = parent.children.find(child => child.tagName === 'PRE');
        assert.ok(pre);
        assert.equal(pre.textContent, '<b>literal</b>');
        assert.equal(collectText(parent).startsWith('A '), true);
        assert.equal(collectText(parent).endsWith(' B'), true);
    });
});
