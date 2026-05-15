import { D, initBackendRequiredControlGuard, state } from './js/context.js';
import { initAudioControls, refreshLocalTtsStatus, updateAudioProviderUi } from './js/audio.js';
import { addChatMessage, initChatControls, pollChatUpdates, sendUserMessage } from './js/chat.js';
import { initDeviceControls } from './js/device-control.js';
import { initMotionControls, pollMotionStatus, resizeCanvas } from './js/motion-control.js';
import { refreshOllamaStatus, initSettingsControls } from './js/settings.js';
import { startupCheck } from './js/setup.js';
import { initDiagnosticsControls } from './js/setup-check.js';
import { initVoiceInputControls } from './js/voice-input.js';
import { initSingleActiveTabWarning } from './js/browser-session.js';
import { initAppViewportHeightSync, initCompactMotionPanels } from './js/responsive-layout.js';

function startPollingLoops() {
    startGuardedPoll(pollChatUpdates, 1500);
    startGuardedPoll(pollMotionStatus, 500);
    startGuardedPoll(async () => {
        if (state.ollamaDownloadPolling) await refreshOllamaStatus();
        if (state.localTtsStatusPolling) await refreshLocalTtsStatus();
    }, 2500);
}

function startGuardedPoll(callback, intervalMs) {
    let inFlight = false;
    setInterval(async () => {
        if (inFlight) return;
        inFlight = true;
        try {
            await callback();
        } finally {
            inFlight = false;
        }
    }, intervalMs);
}

function initApp() {
    initAppViewportHeightSync();
    initBackendRequiredControlGuard();
    initSingleActiveTabWarning();
    initCompactMotionPanels();
    resizeCanvas();
    updateAudioProviderUi();
    initChatControls();
    initSettingsControls({addChatMessage});
    initDiagnosticsControls();
    initAudioControls();
    initVoiceInputControls({sendUserMessage});
    initDeviceControls();
    initMotionControls({sendUserMessage});
    startPollingLoops();
    startupCheck();
}

window.addEventListener('resize', resizeCanvas);
D.addEventListener('DOMContentLoaded', initApp);
