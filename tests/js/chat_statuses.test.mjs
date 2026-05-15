// Behavioral replacement for tests/test_frontend_chat_statuses.py. The old
// test pinned the literal action-status map in chat.js; this one drives
// sendUserMessage through the production apiCall path and checks the visible
// status text plus the follow-up update poll.

import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';

import { getStubElement, resetStubElement } from './_harness.mjs';
import { pollChatUpdates, scrollChatToLatest, sendUserMessage } from '../../static/js/chat.js';
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

function streamResponse(lines) {
    const encoder = new TextEncoder();
    const chunks = lines.map(line => encoder.encode(line));
    return {
        ok: true,
        status: 200,
        headers: { get: () => 'application/x-ndjson; charset=utf-8' },
        body: {
            getReader() {
                return {
                    async read() {
                        if (chunks.length) return { value: chunks.shift(), done: false };
                        return { value: undefined, done: true };
                    },
                };
            },
        },
    };
}

function collectText(node) {
    if (!node || typeof node !== 'object') return '';
    let text = node.textContent || '';
    for (const child of node.children || []) text += collectText(child);
    return text;
}

function occurrenceCount(text, needle) {
    return String(text).split(needle).length - 1;
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
        state.chatModelBlockedMessage = '';
        state.pendingQueuedBotEcho = '';
        state.chatStreamingEnabled = false;
    });

    afterEach(() => {
        globalThis.fetch = originalFetch;
        globalThis.document.querySelector = originalQuerySelector;
        state.chatStreamingEnabled = true;
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
        ['auto_started', 'Legacy Auto started.'],
        ['auto_stopped', 'Legacy Auto stopped.'],
        ['close_signaled', "I'm Close signal sent."],
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

    it('renders queued ok chat from the send response and skips the matching update echo', async () => {
        const calls = [];
        globalThis.fetch = async endpoint => {
            calls.push(endpoint);
            if (endpoint === '/send_message') return jsonResponse(200, {
                status: 'ok',
                chat: 'Visible assistant reply.',
                chat_queued: true,
            });
            if (endpoint === '/get_updates') return jsonResponse(200, {
                messages: ['Visible assistant reply.', 'Background mode note.'],
            });
            return jsonResponse(404, { status: 'error', message: `Unexpected endpoint ${endpoint}` });
        };

        const result = await sendUserMessage('hello');
        const chatText = collectText(getStubElement('chat-messages-container'));

        assert.strictEqual(result.handled, true);
        assert.deepStrictEqual(calls, ['/send_message', '/get_updates']);
        assert.strictEqual(occurrenceCount(chatText, 'Visible assistant reply.'), 1);
        assert.strictEqual(occurrenceCount(chatText, 'Background mode note.'), 1);
        assert.strictEqual(state.pendingQueuedBotEcho, '');
    });

    it('renders streamed assistant deltas without waiting for the final chat payload', async () => {
        state.chatStreamingEnabled = true;
        const calls = [];
        globalThis.fetch = async endpoint => {
            calls.push(endpoint);
            if (endpoint === '/send_message_stream') return streamResponse([
                '{"type":"status","status":"generating"}\n',
                '{"type":"delta","text":"Visible "}\n',
                '{"type":"delta","text":"as it arrives."}\n',
                '{"type":"final","data":{"status":"ok","chat":"Visible as it arrives.","chat_streamed":true,"chat_queued":false}}\n',
            ]);
            if (endpoint === '/get_updates') return jsonResponse(200, { messages: [] });
            return jsonResponse(404, { status: 'error', message: `Unexpected endpoint ${endpoint}` });
        };

        const result = await sendUserMessage('hello');
        const chatText = collectText(getStubElement('chat-messages-container'));

        assert.strictEqual(result.handled, true);
        assert.strictEqual(result.streamed, true);
        assert.deepStrictEqual(calls, ['/send_message_stream', '/get_updates']);
        assert.strictEqual(occurrenceCount(chatText, 'Visible as it arrives.'), 1);
        assert.strictEqual(state.pendingQueuedBotEcho, '');
    });

    it('renders model transport errors as direct system errors without polling updates', async () => {
        const calls = installChatResponses({
            status: 'model_error',
            message: 'Model request failed. Check Ollama status and try again.',
            chat: 'LLM Connection Error: read timed out',
            chat_queued: false,
        });

        const result = await sendUserMessage('hello');
        const chatText = collectText(getStubElement('chat-messages-container'));
        const statusText = getStubElement('status-text');

        assert.strictEqual(result.handled, false);
        assert.deepStrictEqual(calls, ['/send_message']);
        assert.strictEqual(occurrenceCount(chatText, 'MODEL ERROR'), 1);
        assert.strictEqual(occurrenceCount(chatText, 'LLM Connection Error: read timed out'), 1);
        assert.strictEqual(statusText.textContent, 'Model request failed. Check Ollama status and try again.');
        assert.strictEqual(statusText.dataset.statusTone, 'error');
        assert.strictEqual(statusText.style.color, 'var(--red)');
        assert.strictEqual(state.pendingQueuedBotEcho, '');
    });

    it('does not send or clear text when model availability blocks chat', async () => {
        const calls = [];
        globalThis.fetch = async endpoint => {
            calls.push(endpoint);
            return jsonResponse(200, { status: 'ok' });
        };
        state.chatModelBlockedMessage = 'Model not installed - download local/test in Settings > Model before chatting.';
        const input = getStubElement('user-chat-input');
        input.value = 'do not lose this draft';

        const result = await sendUserMessage(input.value);

        assert.strictEqual(result.blocked, true);
        assert.strictEqual(result.skipped, true);
        assert.strictEqual(result.reason, state.chatModelBlockedMessage);
        assert.deepStrictEqual(calls, []);
        assert.strictEqual(input.value, 'do not lose this draft');
        assert.strictEqual(
            getStubElement('status-text').textContent,
            'Model not installed - download local/test in Settings > Model before chatting.',
        );
        assert.strictEqual(getStubElement('status-text').dataset.statusTone, 'warning');
        assert.strictEqual(getStubElement('status-text').style.color, 'var(--yellow)');
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

    it('exposes the latest jump button only while scrollback is away from bottom', () => {
        const chatView = getStubElement('chat-view');
        const jumpButton = getStubElement('jump-to-latest-btn');
        chatView.scrollHeight = 1000;
        chatView.scrollTop = 100;
        chatView.clientHeight = 300;

        assert.strictEqual(scrollChatToLatest(), false);
        assert.strictEqual(jumpButton.hidden, false);
        assert.strictEqual(jumpButton.getAttribute('aria-hidden'), 'false');

        assert.strictEqual(scrollChatToLatest({ force: true }), true);
        assert.strictEqual(jumpButton.hidden, true);
        assert.strictEqual(jumpButton.getAttribute('aria-hidden'), 'true');
    });

    it('surfaces backend chat/TTS divergence warnings from updates', async () => {
        globalThis.fetch = async endpoint => {
            assert.strictEqual(endpoint, '/get_updates');
            return jsonResponse(200, {
                messages: [],
                audio_ready: false,
                chat_audio_warning: 'Voice output was queued without a matching chat message.',
            });
        };

        await pollChatUpdates();

        const statusText = getStubElement('status-text');
        assert.strictEqual(statusText.textContent, 'Voice output was queued without a matching chat message.');
        assert.strictEqual(statusText.dataset.statusTone, 'warning');
        assert.strictEqual(statusText.style.color, 'var(--yellow)');
    });

    it('surfaces mode narration as status instead of chat messages', async () => {
        globalThis.fetch = async endpoint => {
            assert.strictEqual(endpoint, '/get_updates');
            return jsonResponse(200, {
                messages: [],
                audio_ready: false,
                mode_status_message: 'Adding slower pressure in Freestyle.',
                chat_audio_warning: '',
            });
        };

        await pollChatUpdates();

        const statusText = getStubElement('status-text');
        const chatView = getStubElement('chat-view');
        assert.strictEqual(statusText.textContent, 'Adding slower pressure in Freestyle.');
        assert.strictEqual(chatView.children.length, 0);
    });
});
