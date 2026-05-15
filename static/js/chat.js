import { D, apiCall, el, fetchWithConnectionState, setStatusMessage, state } from './context.js';
import { playQueuedAudio } from './audio.js';

function appendPlainMessageText(parent, text) {
    const parts = String(text || '').split('\n');
    parts.forEach((part, index) => {
        if (index > 0) parent.appendChild(D.createElement('br'));
        if (part) parent.appendChild(D.createTextNode(part));
    });
}

function setChatCodeCopyButtonState(button, label, ariaLabel, restoreMs) {
    if (!button) return;
    const defaultLabel = button.dataset.defaultLabel || 'Copy';
    const defaultAria = button.dataset.defaultAriaLabel || 'Copy code block';
    button.textContent = label;
    button.title = ariaLabel;
    button.setAttribute('aria-label', ariaLabel);
    if (button._chatCodeCopyTimer) globalThis.clearTimeout(button._chatCodeCopyTimer);
    if (restoreMs > 0 && label !== defaultLabel) {
        button._chatCodeCopyTimer = globalThis.setTimeout(() => {
            button.textContent = defaultLabel;
            button.title = defaultAria;
            button.setAttribute('aria-label', defaultAria);
            button._chatCodeCopyTimer = null;
        }, restoreMs);
    }
}

export async function copyChatCodeBlock(text, button, {clipboard = globalThis.navigator?.clipboard, restoreMs = 1500} = {}) {
    if (!clipboard || typeof clipboard.writeText !== 'function') {
        setChatCodeCopyButtonState(button, 'Unavailable', 'Clipboard copy unavailable', restoreMs);
        return false;
    }
    try {
        await clipboard.writeText(String(text ?? ''));
        setChatCodeCopyButtonState(button, 'Copied', 'Code block copied', restoreMs);
        return true;
    } catch {
        setChatCodeCopyButtonState(button, 'Failed', 'Code block copy failed', restoreMs);
        return false;
    }
}

function appendCodeBlock(parent, text) {
    const code = String(text ?? '');
    const wrapper = D.createElement('div');
    wrapper.className = 'chat-code-block';
    wrapper.setAttribute('role', 'group');
    wrapper.setAttribute('aria-label', 'Code block');

    const pre = D.createElement('pre');
    pre.textContent = code;
    const button = D.createElement('button');
    button.type = 'button';
    button.className = 'chat-code-copy-button';
    button.dataset.defaultLabel = 'Copy';
    button.dataset.defaultAriaLabel = 'Copy code block';
    button.textContent = button.dataset.defaultLabel;
    button.title = button.dataset.defaultAriaLabel;
    button.setAttribute('aria-label', button.dataset.defaultAriaLabel);
    button.addEventListener('click', () => copyChatCodeBlock(code, button));

    wrapper.appendChild(pre);
    wrapper.appendChild(button);
    parent.appendChild(wrapper);
}

export function appendMessageText(parent, text) {
    const raw = String(text || '');
    const prePattern = /<pre>([\s\S]*?)<\/pre>|```[^\r\n`]*(?:\r?\n)([\s\S]*?)```/gi;
    let cursor = 0;
    let match;
    while ((match = prePattern.exec(raw)) !== null) {
        appendPlainMessageText(parent, raw.slice(cursor, match.index));
        appendCodeBlock(parent, match[1] ?? match[2]);
        cursor = prePattern.lastIndex;
    }
    appendPlainMessageText(parent, raw.slice(cursor));
}

function renderMessageText(parent, text) {
    parent.replaceChildren();
    appendMessageText(parent, text);
}

export const CHAT_BOTTOM_THRESHOLD_PX = 96;

export function isChatNearBottom() {
    return el.chatView.scrollHeight - el.chatView.scrollTop - el.chatView.clientHeight <= CHAT_BOTTOM_THRESHOLD_PX;
}

function setJumpToLatestVisible(visible) {
    if (!el.jumpToLatestBtn) return;
    el.jumpToLatestBtn.hidden = !visible;
    el.jumpToLatestBtn.setAttribute('aria-hidden', visible ? 'false' : 'true');
}

export function scrollChatToLatest({force = false} = {}) {
    if (force || isChatNearBottom()) {
        el.chatView.scrollTop = el.chatView.scrollHeight;
        setJumpToLatestVisible(false);
        return true;
    }
    setJumpToLatestVisible(true);
    return false;
}

function updateJumpToLatestVisibility() {
    setJumpToLatestVisible(!isChatNearBottom());
}

export function chatMessageKind(sender, text) {
    const value = String(text || '');
    if (sender === 'BOT' && /^(LLM Connection Error|LLM request failed):/i.test(value)) return 'model-error';
    return sender === 'BOT' ? 'bot' : 'user';
}

function insertChatMessage(sender, text, {forceScroll = false} = {}) {
    const shouldScroll = forceScroll || isChatNearBottom();
    const kind = chatMessageKind(sender, text);
    const speaker = kind === 'model-error' ? 'MODEL ERROR' : (sender === 'BOT' ? state.aiName : 'YOU');
    const messageEl = D.createElement('div');
    messageEl.className = `chat-message-container ${kind === 'user' ? 'user-bubble' : kind === 'model-error' ? 'system-bubble error-bubble' : 'bot-bubble'}`;

    if (kind === 'bot') {
        const pfp = D.createElement('img');
        pfp.className = 'chat-pfp';
        pfp.src = el.pfpPreview.src;
        pfp.alt = 'pfp';
        messageEl.appendChild(pfp);
    }

    const content = D.createElement('div');
    content.className = 'message-content';
    const speakerName = D.createElement('p');
    speakerName.className = 'speaker-name';
    speakerName.textContent = speaker;
    const bubble = D.createElement('div');
    bubble.className = 'message-bubble';
    appendMessageText(bubble, text);
    content.appendChild(speakerName);
    content.appendChild(bubble);
    messageEl.appendChild(content);

    el.chatMessagesContainer.insertBefore(messageEl, el.typingIndicator);
    if (shouldScroll) {
        scrollChatToLatest({force: true});
    } else {
        setJumpToLatestVisible(true);
    }
    return {
        messageEl,
        bubble,
        updateText(nextText) {
            renderMessageText(bubble, nextText);
            scrollChatToLatest();
        },
    };
}

export function addChatMessage(sender, text, {forceScroll = false} = {}) {
    return insertChatMessage(sender, text, {forceScroll}).messageEl;
}

function startStreamingBotMessage() {
    const entry = insertChatMessage('BOT', '', {forceScroll: true});
    entry.messageEl.classList.add('streaming-bubble');
    entry.messageEl.setAttribute('aria-busy', 'true');
    return entry;
}

function finishStreamingBotMessage(entry) {
    if (!entry) return;
    entry.messageEl.classList.remove('streaming-bubble');
    entry.messageEl.removeAttribute('aria-busy');
}

function clearTypingIndicator(statusMessage = '') {
    el.typingIndicator.style.display = 'none';
    if (statusMessage) el.statusText.textContent = statusMessage;
}

function handleSendMessageStatus(data) {
    if (!data) {
        clearTypingIndicator('Message failed before the model could answer. Check the app terminal.');
        return false;
    }

    if (data.status === 'model_error') {
        clearTypingIndicator();
        setStatusMessage(
            el.statusText,
            data.message || 'Model request failed. Check Ollama status and try again.',
            'error',
        );
        if (data.chat) addChatMessage('BOT', data.chat, {forceScroll: true});
        return false;
    }

    const statusMessages = {
        no_key_set: 'Set your Handy connection key before chatting.',
        empty_message: 'Type a message first.',
        message_relayed_to_active_mode: 'Sent to the active mode.',
    };
    if (statusMessages[data.status]) {
        clearTypingIndicator(statusMessages[data.status]);
        return false;
    }
    const actionStatusMessages = {
        stopped: 'Stopping.',
        auto_started: 'Legacy Auto started.',
        auto_stopped: 'Legacy Auto stopped.',
        freestyle_started: 'Freestyle started.',
        edging_started: 'Edging mode started.',
        milking_started: 'Milking mode started.',
        close_signaled: "I'm Close signal sent.",
        move_applied: 'Motion command applied.',
        konami_code_activated: 'Special pattern started.',
    };
    if (actionStatusMessages[data.status]) {
        clearTypingIndicator(data.message || actionStatusMessages[data.status]);
        return true;
    }
    if (data.status && data.status !== 'ok') {
        clearTypingIndicator(data.message || `Message failed: ${data.status}`);
        return false;
    }
    if (data.chat && data.chat_queued !== true) {
        clearTypingIndicator();
        addChatMessage('BOT', data.chat, {forceScroll: true});
        return true;
    }
    if (data.chat_queued === true) {
        clearTypingIndicator();
        if (data.chat) {
            addChatMessage('BOT', data.chat, {forceScroll: true});
            state.pendingQueuedBotEcho = String(data.chat);
        }
        return true;
    }
    if (data.chat_queued === false) {
        clearTypingIndicator('The model returned no chat text. Check Ollama model status and try again.');
        return false;
    }
    return true;
}

export function chatSendBlockedMessage() {
    return state.chatModelBlockedMessage || '';
}

function chatStreamingSupported() {
    return state.chatStreamingEnabled !== false
        && typeof TextDecoder !== 'undefined'
        && typeof ReadableStream !== 'undefined';
}

async function readChatStream(response, onEvent) {
    const reader = response.body?.getReader?.();
    if (!reader) return false;
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop() || '';
        for (const line of lines) {
            if (!line.trim()) continue;
            onEvent(JSON.parse(line));
        }
        if (done) break;
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
    return true;
}

async function sendUserMessageStream(requestOptions, startedAt) {
    let response;
    try {
        response = await fetchWithConnectionState('/send_message_stream', requestOptions);
    } catch {
        return {
            data: null,
            handled: false,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: false,
        };
    }
    if (!response.ok) {
        setStatusMessage(el.statusText, `Error: server returned ${response.status}.`, 'error');
        return {
            data: null,
            handled: false,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: false,
        };
    }

    let streamEntry = null;
    let streamedText = '';
    let finalData = null;
    let consumed = false;
    try {
        consumed = await readChatStream(response, event => {
            if (event.type === 'delta') {
                if (!streamEntry) {
                    clearTypingIndicator();
                    streamEntry = startStreamingBotMessage();
                }
                streamedText += String(event.text || '');
                streamEntry.updateText(streamedText);
            } else if (event.type === 'final') {
                finalData = event.data || null;
            }
        });
    } catch (error) {
        console.error('Chat stream failed:', error);
        setStatusMessage(el.statusText, 'Chat stream failed before the model finished.', 'error');
        finishStreamingBotMessage(streamEntry);
        return {
            data: null,
            handled: false,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: Boolean(streamEntry),
        };
    }
    if (!consumed) return null;
    finishStreamingBotMessage(streamEntry);

    if (streamEntry && finalData?.chat && finalData.chat !== streamedText) {
        streamedText = String(finalData.chat);
        streamEntry.updateText(streamedText);
    }
    if (!finalData) {
        clearTypingIndicator('Message failed before the model could answer. Check the app terminal.');
        return {
            data: null,
            handled: false,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: Boolean(streamEntry),
        };
    }
    if (!streamEntry) {
        const handled = handleSendMessageStatus(finalData);
        if (handled) await pollChatUpdates();
        return {
            data: finalData,
            handled,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: false,
        };
    }
    if (finalData.status === 'model_error') {
        setStatusMessage(
            el.statusText,
            finalData.message || 'Model request failed. Check Ollama status and try again.',
            'error',
        );
        return {
            data: finalData,
            handled: false,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: true,
        };
    }
    if (finalData.status && finalData.status !== 'ok') {
        const handled = handleSendMessageStatus(finalData);
        return {
            data: finalData,
            handled,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            streamed: true,
        };
    }
    clearTypingIndicator();
    state.pendingQueuedBotEcho = '';
    await pollChatUpdates();
    return {
        data: finalData,
        handled: true,
        elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
        streamed: true,
    };
}

export async function sendUserMessage(message, {source = 'chat'} = {}) {
    const startedAt = performance.now();
    const persona = el.personaInput.value.trim();
    const blockedMessage = chatSendBlockedMessage();
    if (blockedMessage) {
        el.typingIndicator.style.display = 'none';
        setStatusMessage(el.statusText, blockedMessage, 'warning');
        return {
            data: null,
            handled: false,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
            skipped: true,
            blocked: true,
            reason: blockedMessage,
        };
    }
    if (message.trim() || persona !== state.myPersonaDescription) {
        if (message.trim()) addChatMessage('YOU', message, {forceScroll: true});
        state.myPersonaDescription = persona;
        el.userChatInput.value = '';
        D.querySelector('#typing-indicator .speaker-name').textContent = state.aiName;
        el.typingIndicator.style.display = 'grid';
        scrollChatToLatest({force: true});
        const requestOptions = {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                message,
                key: state.myHandyKey,
                persona_desc: state.myPersonaDescription,
                source,
            }),
        };
        if (chatStreamingSupported()) {
            const streamedResult = await sendUserMessageStream(requestOptions, startedAt);
            if (streamedResult !== null) return streamedResult;
        }
        const data = await apiCall('/send_message', requestOptions);
        const handled = handleSendMessageStatus(data);
        if (handled) await pollChatUpdates();
        return {
            data,
            handled,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
        };
    }
    return {data: null, handled: false, elapsed_ms: 0, skipped: true};
}

export async function pollChatUpdates() {
    const data = await apiCall('/get_updates');
    if (!data) return;
    if (data.messages && data.messages.length > 0) {
        el.typingIndicator.style.display = 'none';
    }
    if (data.messages) {
        let skippedQueuedEcho = false;
        data.messages.forEach(msg => {
            if (!skippedQueuedEcho && state.pendingQueuedBotEcho && msg === state.pendingQueuedBotEcho) {
                skippedQueuedEcho = true;
                return;
            }
            addChatMessage('BOT', msg);
        });
        state.pendingQueuedBotEcho = '';
    }
    if (data.audio_error) {
        el.localTtsStatus.textContent = data.audio_error;
        el.localTtsStatus.style.color = 'var(--yellow)';
    }
    if (data.mode_status_message) {
        setStatusMessage(el.statusText, data.mode_status_message);
    }
    if (data.chat_audio_warning) {
        setStatusMessage(el.statusText, data.chat_audio_warning, 'warning');
    }
    if (data.audio_ready) {
        await playQueuedAudio();
    }
}

export function initChatControls() {
    D.getElementById('send-chat-btn').addEventListener('click', () => sendUserMessage(el.userChatInput.value));
    el.jumpToLatestBtn.addEventListener('click', () => scrollChatToLatest({force: true}));
    el.chatView.addEventListener('scroll', updateJumpToLatestVisibility, {passive: true});
    el.userChatInput.addEventListener('keypress', event => {
        if (event.key === 'Enter') sendUserMessage(el.userChatInput.value);
    });
}
