import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { makeStandaloneStubElement } from './_harness.mjs';
import { appendMessageText, copyChatCodeBlock } from '../../static/js/chat.js';


function collectText(node) {
    if (!node || typeof node !== 'object') return '';
    let text = node.textContent || '';
    for (const child of node.children || []) text += collectText(child);
    return text;
}

function childTags(node) {
    return (node.children || []).map(child => child.tagName || `#${child.nodeType}`);
}

function findFirstTag(node, tagName) {
    if (!node || typeof node !== 'object') return null;
    if (node.tagName === tagName) return node;
    for (const child of node.children || []) {
        const found = findFirstTag(child, tagName);
        if (found) return found;
    }
    return null;
}

describe('chat message rendering', () => {
    it('renders complete markdown code fences as explicit copyable code blocks', () => {
        const parent = makeStandaloneStubElement('div');

        appendMessageText(parent, "Before\n```python\nprint('<safe>')\n```\nAfter");

        const wrapper = parent.children.find(child => child.tagName === 'DIV' && child.className === 'chat-code-block');
        assert.ok(wrapper);
        assert.equal(wrapper.getAttribute('role'), 'group');
        assert.equal(wrapper.getAttribute('aria-label'), 'Code block');
        const pre = findFirstTag(wrapper, 'PRE');
        assert.ok(pre);
        assert.equal(pre.textContent, "print('<safe>')\n");
        const copyButton = findFirstTag(wrapper, 'BUTTON');
        assert.ok(copyButton);
        assert.equal(copyButton.textContent, 'Copy');
        assert.equal(copyButton.getAttribute('aria-label'), 'Copy code block');
        assert.equal(collectText(parent).includes("Before"), true);
        assert.equal(collectText(parent).includes("After"), true);
        assert.deepEqual(childTags(parent).filter(tag => tag === 'DIV'), ['DIV']);
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

        const pre = findFirstTag(parent, 'PRE');
        assert.ok(pre);
        assert.equal(pre.textContent, '<b>literal</b>');
        assert.equal(collectText(parent).startsWith('A '), true);
        assert.equal(collectText(parent).endsWith(' B'), true);
    });

    it('copies code block text without reading from rendered markup', async () => {
        const button = makeStandaloneStubElement('button');
        button.dataset.defaultLabel = 'Copy';
        button.dataset.defaultAriaLabel = 'Copy code block';
        button.textContent = 'Copy';
        button.setAttribute('aria-label', 'Copy code block');
        const writes = [];

        const copied = await copyChatCodeBlock('line 1\nline 2', button, {
            clipboard: { writeText: async value => writes.push(value) },
            restoreMs: 0,
        });

        assert.equal(copied, true);
        assert.deepEqual(writes, ['line 1\nline 2']);
        assert.equal(button.textContent, 'Copied');
        assert.equal(button.getAttribute('aria-label'), 'Code block copied');
    });
});
