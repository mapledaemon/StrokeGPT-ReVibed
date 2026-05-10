// Behavioral replacement for tests/test_frontend_chat_statuses.py. The old
// test pinned the literal action-status map in chat.js; this one drives
// sendUserMessage through the production apiCall path and checks the visible
// status text plus the follow-up update poll.

import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { sendUserMessage } from '../../static/js/chat.js';
import { state } from '../../static/js/context.js';


function jsonResponse(httpStatus, body) {
    const factory = () => ({
        ok: httpStatus >= 200 && httpStatus < 300,
        status: httpStatus,
        headers: {
            get(name) {
                return name && name.toLowerCase() === 'content-type'
                    ? 'application/json'
                    : null;
            },
        },
        async json() { return body; },
        async blob() { return null; },
        clone() { return factory(); },
    });
    return factory();
}

describe('chat action statuses', () => {
    let originalFetch;
    let originalQuerySelector;

    beforeEach(() => {
        originalFetch = globalThis.fetch;
        originalQuerySelector = globalThis.document.querySelector;
        globalThis.document.querySelector = selector => {
            if (selector === '#typing-indicator .speaker-name') {
                return getStubElement('typing-indicator-speaker-name');
            }
            return originalQuerySelector.call(globalThis.document, selector);
        };

        resetStubElement('status-text');
        resetStubElement('typing-indicator');
        resetStubElement('typing-indicator-speaker-name');
        resetStubElement('chat-messages-container');
        resetStubElement('user-chat-input');
        resetStubElement('persona-input');
        resetStubElement('chat-view');
        resetStubElement('jump-to-latest-btn');
        getStubElement('persona-input').value = '';
        getStubElement('user-chat-input').value = 'before send';
        getStubElement('status-text').textContent = 'baseline';
        state.myPersonaDescription = '';
        state.aiName = 'BOT';
        state.connectionLost = false;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        globalThis.document.querySelector = originalQuerySelector;
    });

    function installChatResponses(sendPayload) {
        const calls = [];
        globalThis.fetch = async endpoint => {
            calls.push(endpoint);
            if (endpoint === '/send_message') return jsonResponse(200, sendPayload);
            if (endpoint === '/get_updates') return jsonResponse(200, { messages: [] });
            return jsonResponse(404, { status: 'error', message: `Unexpected endpoint ${endpoint}` });
        };
        return calls;
    }

    const actionStatuses = [
        ['stopped', 'Stopping.'],
        ['auto_started', 'Auto mode started.'],
        ['auto_stopped', 'Auto mode stopped.'],
        ['freestyle_started', 'Freestyle started.'],
        ['edging_started', 'Edging mode started.'],
        ['milking_started', 'Milking mode started.'],
        ['move_applied', 'Motion command applied.'],
        ['konami_code_activated', 'Special pattern started.'],
    ];

    for (const [status, fallback] of actionStatuses) {
        it(`treats ${status} as handled and polls for updates`, async () => {
            const calls = installChatResponses({ status });

            const result = await sendUserMessage('start mode');

            assert.strictEqual(result.handled, true);
            assert.strictEqual(result.data.status, status);
            assert.strictEqual(getStubElement('status-text').textContent, fallback);
            assert.deepStrictEqual(calls, ['/send_message', '/get_updates']);
            assert.ok(result.elapsed_ms >= 0);
        });
    }

    it('prefers the server message for handled action statuses', async () => {
        installChatResponses({
            status: 'auto_started',
            message: 'Auto accepted but waiting for the next tick.',
        });

        const result = await sendUserMessage('take over');

        assert.strictEqual(result.handled, true);
        assert.strictEqual(
            getStubElement('status-text').textContent,
            'Auto accepted but waiting for the next tick.',
        );
    });

    it('does not poll updates for unhandled failure statuses', async () => {
        const calls = installChatResponses({ status: 'auto_started_but_blocked' });

        const result = await sendUserMessage('take over');

        assert.strictEqual(result.handled, false);
        assert.strictEqual(
            getStubElement('status-text').textContent,
            'Message failed: auto_started_but_blocked',
        );
        assert.deepStrictEqual(calls, ['/send_message']);
    });
});
