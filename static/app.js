import { D, initBackendRequiredControlGuard, state } from './js/context.js';
import { initAudioControls, refreshLocalTtsStatus, updateAudioProviderUi } from './js/audio.js';
import { addChatMessage, initChatControls, pollChatUpdates, sendUserMessage } from './js/chat.js';
import { initDeviceControls } from './js/device-control.js';
import { initMotionControls, pollMotionStatus, resizeCanvas } from './js/motion-control.js';
import { refreshOllamaStatus, initSettingsControls } from './js/settings.js';
import { startupCheck } from './js/setup.js';

function startPollingLoops() {
    setInterval(pollChatUpdates, 1500);
    setInterval(pollMotionStatus, 500);
    setInterval(async () => {
        if (state.ollamaDownloadPolling) await refreshOllamaStatus();
        if (state.localTtsStatusPolling) await refreshLocalTtsStatus();
    }, 2500);
}

function initApp() {
    initBackendRequiredControlGuard();
    resizeCanvas();
    updateAudioProviderUi();
    initChatControls();
    initSettingsControls({addChatMessage});
    initAudioControls();
    initDeviceControls();
    initMotionControls({sendUserMessage});
    startPollingLoops();
    startupCheck();
}

window.addEventListener('resize', resizeCanvas);
D.addEventListener('DOMContentLoaded', initApp);
