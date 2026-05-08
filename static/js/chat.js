import { D, apiCall, el, state } from './context.js';
import { playQueuedAudio } from './audio.js';

function appendPlainMessageText(parent, text) {
    const parts = String(text || '').split('\n');
    parts.forEach((part, index) => {
        if (index > 0) parent.appendChild(D.createElement('br'));
        if (part) parent.appendChild(D.createTextNode(part));
    });
}

export function appendMessageText(parent, text) {
    const raw = String(text || '');
    const prePattern = /<pre>([\s\S]*?)<\/pre>/gi;
    let cursor = 0;
    let match;
    while ((match = prePattern.exec(raw)) !== null) {
        appendPlainMessageText(parent, raw.slice(cursor, match.index));
        const pre = D.createElement('pre');
        pre.textContent = match[1];
        parent.appendChild(pre);
        cursor = prePattern.lastIndex;
    }
    appendPlainMessageText(parent, raw.slice(cursor));
}

export const CHAT_BOTTOM_THRESHOLD_PX = 96;

export function isChatNearBottom() {
    return el.chatView.scrollHeight - el.chatView.scrollTop - el.chatView.clientHeight <= CHAT_BOTTOM_THRESHOLD_PX;
}

function setJumpToLatestVisible(visible) {
    if (el.jumpToLatestBtn) el.jumpToLatestBtn.hidden = !visible;
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

export function addChatMessage(sender, text, {forceScroll = false} = {}) {
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
        auto_started: 'Auto mode started.',
        auto_stopped: 'Auto mode stopped.',
        freestyle_started: 'Freestyle started.',
        edging_started: 'Edging mode started.',
        milking_started: 'Milking mode started.',
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
        return true;
    }
    if (data.chat_queued === false) {
        clearTypingIndicator('The model returned no chat text. Check Ollama model status and try again.');
        return false;
    }
    return true;
}

export async function sendUserMessage(message) {
    const startedAt = performance.now();
    const persona = el.personaInput.value.trim();
    if (message.trim() || persona !== state.myPersonaDescription) {
        if (message.trim()) addChatMessage('YOU', message, {forceScroll: true});
        state.myPersonaDescription = persona;
        el.userChatInput.value = '';
        D.querySelector('#typing-indicator .speaker-name').textContent = state.aiName;
        el.typingIndicator.style.display = 'flex';
        scrollChatToLatest({force: true});
        const data = await apiCall('/send_message', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message, key: state.myHandyKey, persona_desc: state.myPersonaDescription}),
        });
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
        data.messages.forEach(msg => addChatMessage('BOT', msg));
    }
    if (data.audio_error) {
        el.localTtsStatus.textContent = data.audio_error;
        el.localTtsStatus.style.color = 'var(--yellow)';
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
