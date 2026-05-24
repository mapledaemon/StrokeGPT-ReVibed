import { D, apiCall, appendQueryParams, el, fetchWithConnectionState, getUiClientId, setStatusMessage, state } from './context.js';
import { playQueuedAudio, scheduleQueuedAudioPlayback, voiceOutputEnabled } from './audio.js';

const MALFORMED_MODEL_REPLY_TOOLTIP = 'This reply came from malformed JSON from the local model. The readable chat text was preserved, but motion or metadata in that response may have been ignored. If this keeps happening, clear model memory or try a different Ollama model.';

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

function formatMs(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return null;
    return `${Math.round(number)}ms`;
}

function formatLlmMessageTooltip(metadata = {}) {
    if (!metadata || typeof metadata !== 'object') return '';
    const model = String(metadata.model || '').trim();
    const parts = [];
    if (model) parts.push(`Model: ${model}`);
    if (metadata.prompt_mode) parts.push(`Prompt: ${metadata.prompt_mode}`);
    parts.push(`Thinking: ${metadata.thinking_enabled ? 'on' : 'off'}`);
    parts.push(`Streamed: ${metadata.streamed ? 'yes' : 'no'}`);
    const timings = metadata.timings && typeof metadata.timings === 'object' ? metadata.timings : {};
    const timingParts = [
        ['LLM', timings.llm_ms],
        ['Repair', timings.motion_repair_ms],
        ['Mode', timings.mode_action_ms],
        ['Motion', timings.motion_apply_ms],
        ['Total', timings.request_ms],
    ]
        .map(([label, value]) => {
            const formatted = formatMs(value);
            return formatted ? `${label} ${formatted}` : '';
        })
        .filter(Boolean);
    if (timingParts.length) parts.push(`Run: ${timingParts.join(' | ')}`);
    return parts.join('\n');
}

function applyBotMessageMetadata(messageEl, metadata = {}, pfpElement = null) {
    const tooltip = formatLlmMessageTooltip(metadata);
    if (tooltip) {
        messageEl.dataset.llmModel = String(metadata.model || '');
        messageEl.dataset.llmRunDetails = tooltip;
    }
    const pfp = pfpElement || messageEl.querySelector?.('.chat-pfp');
    if (pfp && tooltip) {
        pfp.title = tooltip;
        pfp.setAttribute('aria-label', tooltip);
    }
    const malformed = metadata?.response_warning === 'malformed_json'
        || Boolean(metadata?.timings?.llm_json_salvaged)
        || Boolean(metadata?.timings?.llm_json_invalid);
    if (malformed) messageEl.classList.add('malformed-model-reply');
    else messageEl.classList.remove('malformed-model-reply');
    let badge = messageEl._chatWarningBadge || null;
    if (malformed) {
        if (!badge) {
            badge = D.createElement('span');
            badge.className = 'message-warning-badge';
            badge.textContent = '!';
            badge.setAttribute('aria-label', MALFORMED_MODEL_REPLY_TOOLTIP);
            const speakerName = messageEl._chatSpeakerName || messageEl.querySelector?.('.speaker-name');
            speakerName?.appendChild(badge);
            messageEl._chatWarningBadge = badge;
        }
        badge.title = MALFORMED_MODEL_REPLY_TOOLTIP;
    } else if (badge) {
        badge.parentNode?.removeChild(badge);
        messageEl._chatWarningBadge = null;
    }
}

function insertChatMessage(sender, text, {forceScroll = false, metadata = null} = {}) {
    const shouldScroll = forceScroll || isChatNearBottom();
    const kind = chatMessageKind(sender, text);
    const speaker = kind === 'model-error' ? 'MODEL ERROR' : (sender === 'BOT' ? state.aiName : 'YOU');
    const messageEl = D.createElement('div');
    messageEl.className = `chat-message-container ${kind === 'user' ? 'user-bubble' : kind === 'model-error' ? 'system-bubble error-bubble' : 'bot-bubble'}`;
    let pfp = null;

    if (kind === 'bot') {
        pfp = D.createElement('img');
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
    messageEl._chatSpeakerName = speakerName;
    const bubble = D.createElement('div');
    bubble.className = 'message-bubble';
    appendMessageText(bubble, text);
    content.appendChild(speakerName);
    content.appendChild(bubble);
    messageEl.appendChild(content);
    if (kind === 'bot') applyBotMessageMetadata(messageEl, metadata, pfp);

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
        setMetadata(nextMetadata) {
            applyBotMessageMetadata(messageEl, nextMetadata, pfp);
        },
    };
}

export function addChatMessage(sender, text, {forceScroll = false, metadata = null} = {}) {
    return insertChatMessage(sender, text, {forceScroll, metadata}).messageEl;
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
        if (data.chat) addChatMessage('BOT', data.chat, {
            forceScroll: true,
            metadata: data.llm_message_metadata,
        });
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
        addChatMessage('BOT', data.chat, {forceScroll: true, metadata: data.llm_message_metadata});
        return true;
    }
    if (data.chat_queued === true) {
        clearTypingIndicator();
        if (data.chat) {
            addChatMessage('BOT', data.chat, {forceScroll: true, metadata: data.llm_message_metadata});
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

    if (streamEntry && finalData?.status !== 'model_error' && finalData?.chat && finalData.chat !== streamedText) {
        streamedText = String(finalData.chat);
        streamEntry.updateText(streamedText);
    }
    if (streamEntry && finalData?.llm_message_metadata) {
        streamEntry.setMetadata(finalData.llm_message_metadata);
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
        if (handled) {
            await pollChatUpdates({playAudio: false});
            await waitForReplyAudio();
        }
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
    state.pendingQueuedBotEcho = finalData.chat_queued === true && finalData.chat ? String(finalData.chat) : '';
    await pollChatUpdates({playAudio: false});
    await waitForReplyAudio();
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
                client_id: getUiClientId(),
                source,
            }),
        };
        if (chatStreamingSupported()) {
            const streamedResult = await sendUserMessageStream(requestOptions, startedAt);
            if (streamedResult !== null) return streamedResult;
        }
        const data = await apiCall('/send_message', requestOptions);
        const handled = handleSendMessageStatus(data);
        if (handled) {
            await pollChatUpdates({playAudio: false});
            await waitForReplyAudio();
        }
        return {
            data,
            handled,
            elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
        };
    }
    return {data: null, handled: false, elapsed_ms: 0, skipped: true};
}

async function waitForReplyAudio() {
    if (!voiceOutputEnabled()) return;
    await playQueuedAudio({waitMs: 5000, followupWaitMs: 1000});
}

export async function pollChatUpdates({playAudio = true} = {}) {
    const data = await apiCall(appendQueryParams('/get_updates', {client_id: getUiClientId()}));
    if (!data) return;
    if (data.messages && data.messages.length > 0) {
        el.typingIndicator.style.display = 'none';
    }
    if (data.messages) {
        const records = Array.isArray(data.message_records) && data.message_records.length
            ? data.message_records
            : data.messages.map(text => ({text, metadata: null}));
        let skippedQueuedEcho = false;
        records.forEach(record => {
            const msg = typeof record === 'string' ? record : record?.text;
            if (!skippedQueuedEcho && state.pendingQueuedBotEcho && msg === state.pendingQueuedBotEcho) {
                skippedQueuedEcho = true;
                return;
            }
            addChatMessage('BOT', msg, {metadata: record?.metadata || null});
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
    if (data.audio_ready && playAudio) {
        scheduleQueuedAudioPlayback();
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
