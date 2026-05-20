import { D, apiCall, el, state } from './context.js';
import { populateAudioSettings, populateLocalEngineOptions, populateLocalStyleOptions, refreshLocalTtsStatus, updateAudioProviderUi, updateLocalTtsStatus } from './audio.js';
import { applyHandyConnectionResult, markHandyConnectionKeySaved, populateDeviceSettings } from './device-control.js';
import { populateMotionSettings } from './motion-control.js';
import { populateVoiceInputSettings } from './voice-input.js';
import {
    fillPersonaPromptSelect,
    normalizePersonaPrompt,
    populateDiagnosticsSettings,
    populateLongTermMemorySetting,
    populateModelOptions,
    populateOllamaThinkingSetting,
    populatePersonaPromptOptions,
    populatePromptModeSetting,
    populateUserGenitaliaSetting,
    refreshOllamaStatus,
    setPersonaPrompt,
    updateOllamaStatus,
} from './settings.js';

function applySetupOllamaGpuWarning(status = {}) {
    const warning = status?.gpu_status?.setup_warning || '';
    if (!el.setupBox) return;
    Array.from(el.setupBox.children || []).forEach(node => {
        if (node.classList?.contains('setup-ollama-gpu-warning')) {
            node.parentNode?.removeChild?.(node);
        }
    });
    if (!warning) return;
    const node = D.createElement('div');
    node.className = 'setup-warning setup-ollama-gpu-warning';
    node.setAttribute('role', 'alert');
    node.textContent = warning;
    el.setupBox.prepend(node);
}

function refreshStartupOllamaStatus(data = {}) {
    refreshOllamaStatus().then(status => {
        if (!status) return;
        data.ollama_status = status;
        if (el.setupOverlay?.style?.display !== 'none') {
            applySetupOllamaGpuWarning(status);
        }
    });
}

const COMPACT_SIDEBAR_QUERY = '(max-width: 760px)';
const STARTUP_SPLASH_STEPS = [
    {delayMs: 0, progress: 8, message: 'Starting browser UI...'},
    {delayMs: 500, progress: 22, message: 'Checking saved settings...'},
    {delayMs: 1800, progress: 46, message: 'Checking local voice settings. Chatterbox and Torch checks can take a moment.'},
    {delayMs: 4500, progress: 68, message: 'Still waiting on startup checks. Local voice dependency scans may be slow on first run.'},
    {delayMs: 9000, progress: 84, message: 'Almost ready. StrokeGPT will open as soon as the backend responds.'},
];

function storedSidebarCollapsedPreference() {
    try {
        return globalThis.localStorage?.getItem('sidebar_collapsed') ?? null;
    } catch {
        return null;
    }
}

function isCompactSidebarViewport() {
    try {
        return Boolean(globalThis.window?.matchMedia?.(COMPACT_SIDEBAR_QUERY)?.matches);
    } catch {
        return false;
    }
}

export function applyInitialSidebarState() {
    const stored = storedSidebarCollapsedPreference();
    const shouldCollapse = stored === 'true' || (stored === null && isCompactSidebarViewport());
    if (shouldCollapse) D.body.classList.add('sidebar-collapsed');
    else D.body.classList.remove('sidebar-collapsed');
}

export function setSplashLoadingStatus(progress, message) {
    const safeProgress = Math.max(0, Math.min(100, Math.round(Number(progress) || 0)));
    if (el.splashStatus) el.splashStatus.textContent = message || '';
    if (el.splashProgressBar) el.splashProgressBar.style.width = `${safeProgress}%`;
    if (el.splashProgressText) el.splashProgressText.textContent = `${safeProgress}%`;
}

function startSplashLoadingStatus() {
    const timers = [];
    STARTUP_SPLASH_STEPS.forEach(step => {
        timers.push(window.setTimeout(() => {
            setSplashLoadingStatus(step.progress, step.message);
        }, step.delayMs));
    });
    return () => timers.forEach(timer => window.clearTimeout(timer));
}

function hideSplashScreen() {
    if (el.splashScreen) el.splashScreen.style.display = 'none';
}

function fadeSplashToSetup(data) {
    if (el.splashPrompt) el.splashPrompt.textContent = 'Press Enter to Begin';
    setSplashLoadingStatus(100, 'Startup checks complete. Press Enter to begin setup.');
    const startHandler = event => {
        if (event.key === 'Enter') {
            D.removeEventListener('keydown', startHandler);
            el.splashScreen?.classList.add('hidden');
            setTimeout(() => renderSetup(false, data || {}), 1000);
        }
    };
    D.addEventListener('keydown', startHandler);
}

export function renderSetup(isReturningUser = false, data = {}) {
    el.setupOverlay.style.display = 'flex';
    let step = isReturningUser ? 2 : 1;
    let setupMinSpeed = data.min_speed ?? 10;

    function displayStep() {
        el.setupBox.classList.remove('setup-check-box');
        if (step === 1) {
            el.setupBox.innerHTML = `<h2>Step 1: Handy Key</h2><p>Please enter your connection key from handyfeeling.com</p><input type="password" id="setup-key" class="input-text" placeholder="Handy Key" data-requires-backend><br><button id="setup-next" class="my-button" data-requires-backend>Next</button>`;
            D.getElementById('setup-next').onclick = async () => {
                const key = D.getElementById('setup-key').value.trim();
                if (!key) return;
                state.myHandyKey = key;
                const res = await apiCall('/set_handy_key', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({key: state.myHandyKey}),
                });
                if (res && res.status === 'success') {
                    applyHandyConnectionResult(state.myHandyKey, res);
                } else {
                    markHandyConnectionKeySaved(state.myHandyKey);
                }
                step = 2;
                displayStep();
            };
        } else if (step === 2) {
            const personaTitle = isReturningUser ? 'Session Persona' : 'Step 2: Persona';
            const personaCopy = isReturningUser
                ? 'Review or change the AI prompt before starting this session.'
                : 'Choose or edit the AI prompt for this session.';
            el.setupBox.innerHTML = `<h2>${personaTitle}</h2><p>${personaCopy}</p><select id="setup-persona-select" class="select-box"></select><input type="text" id="setup-persona" class="input-text" placeholder="Describe persona"><div class="voice-actions"><button id="setup-save-persona" class="my-button" data-requires-backend>Save Prompt</button><button id="setup-next" class="my-button" data-requires-backend>Continue</button></div>`;
            const setupPersonaSelect = D.getElementById('setup-persona-select');
            const setupPersonaInput = D.getElementById('setup-persona');
            const currentPrompt = data.persona || el.personaInput.value || state.personaPrompts[0] || 'An energetic and passionate girlfriend';
            fillPersonaPromptSelect(setupPersonaSelect, state.personaPrompts, currentPrompt);
            setupPersonaInput.value = normalizePersonaPrompt(currentPrompt);
            setupPersonaSelect.onchange = () => {
                setupPersonaInput.value = setupPersonaSelect.value;
            };
            D.getElementById('setup-save-persona').onclick = async () => {
                const saved = await setPersonaPrompt(setupPersonaInput.value, true);
                if (!saved) return;
                fillPersonaPromptSelect(setupPersonaSelect, saved.persona_prompts, saved.persona);
                setupPersonaInput.value = saved.persona;
                el.statusText.textContent = 'Persona prompt saved.';
            };
            D.getElementById('setup-next').onclick = async () => {
                const saved = await setPersonaPrompt(setupPersonaInput.value, true);
                if (!saved) return;
                el.personaInput.value = saved.persona;
                if (isReturningUser) {
                    el.setupOverlay.style.display = 'none';
                    el.statusText.textContent = 'Ready to chat.';
                } else {
                    step = 3;
                    displayStep();
                }
            };
        } else if (step === 3) {
            const defaultMinDepth = data.min_depth ?? 5;
            const defaultMaxDepth = data.max_depth ?? 100;
            el.setupBox.innerHTML = `<h2>Step 3: Stroke Range</h2><p>Choose the safe travel range. Release either slider or press Test to run one pass.</p><div class="slider-container"><label for="depth-min-slider">Tip / Out</label><input type="range" min="0" max="100" value="${defaultMinDepth}" id="depth-min-slider" data-requires-backend><span id="depth-min-val">${defaultMinDepth}%</span></div><div class="slider-container"><label for="depth-max-slider">Base / In</label><input type="range" min="0" max="100" value="${defaultMaxDepth}" id="depth-max-slider" data-requires-backend><span id="depth-max-val">${defaultMaxDepth}%</span></div><div class="setup-actions"><button id="test-depth-range" class="my-button" data-requires-backend>Test</button><button id="set-depth-range" class="my-button" data-requires-backend>Next</button></div>`;
            const minSlider = D.getElementById('depth-min-slider');
            const maxSlider = D.getElementById('depth-max-slider');
            const minVal = D.getElementById('depth-min-val');
            const maxVal = D.getElementById('depth-max-val');
            let minDepth = defaultMinDepth;
            let maxDepth = defaultMaxDepth;
            const normalizeDepthRange = () => {
                const a = parseInt(minSlider.value, 10);
                const b = parseInt(maxSlider.value, 10);
                minDepth = Math.min(a, b);
                maxDepth = Math.max(a, b);
                minVal.textContent = `${minDepth}%`;
                maxVal.textContent = `${maxDepth}%`;
            };
            const testDepthRange = async () => {
                normalizeDepthRange();
                const res = await apiCall('/test_depth_range', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({min_depth: minDepth, max_depth: maxDepth}),
                });
                if (res && res.status === 'busy') el.statusText.textContent = 'Depth test already running.';
            };
            minSlider.oninput = normalizeDepthRange;
            maxSlider.oninput = normalizeDepthRange;
            minSlider.onchange = testDepthRange;
            maxSlider.onchange = testDepthRange;
            D.getElementById('test-depth-range').onclick = testDepthRange;
            D.getElementById('set-depth-range').onclick = async () => {
                normalizeDepthRange();
                await apiCall('/set_depth_limits', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({min_depth: minDepth, max_depth: maxDepth}),
                });
                populateDeviceSettings({handy_key: state.myHandyKey, min_depth: minDepth, max_depth: maxDepth});
                step = 4;
                displayStep();
            };
            normalizeDepthRange();
        } else if (step === 4 || step === 5) {
            const title = step === 4 ? 'Minimum Speed' : 'Maximum Speed';
            const defaultVal = step === 4 ? setupMinSpeed : (data.max_speed ?? 80);
            el.setupBox.innerHTML = `<h2>Step ${step}: Set ${title}</h2><p>Choose your preferred ${title.toLowerCase()}.</p><div class="slider-container setup-slider"><input type="range" min="0" max="100" value="${defaultVal}" id="speed-slider" data-requires-backend><span id="speed-val">${defaultVal}%</span></div><button id="set-speed" class="my-button" data-requires-backend>Next</button>`;
            const slider = D.getElementById('speed-slider');
            slider.oninput = () => { D.getElementById('speed-val').textContent = `${slider.value}%`; };
            D.getElementById('set-speed').onclick = async () => {
                if (step === 4) {
                    setupMinSpeed = slider.value;
                    step = 5;
                    displayStep();
                } else {
                    const setupMaxSpeed = slider.value;
                    await apiCall('/set_speed_limits', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({min_speed: setupMinSpeed, max_speed: setupMaxSpeed}),
                    });
                    populateMotionSettings({min_speed: setupMinSpeed, max_speed: setupMaxSpeed});
                    el.setupOverlay.style.display = 'none';
                    el.statusText.textContent = 'Setup complete. Ready to chat.';
                }
            };
        }
        applySetupOllamaGpuWarning(data.ollama_status);
    }

    displayStep();
}

export async function startupCheck() {
    if (el.splashPrompt) el.splashPrompt.textContent = 'Loading app...';
    const stopSplashLoading = startSplashLoadingStatus();
    const data = await apiCall('/check_settings');
    stopSplashLoading();
    applyInitialSidebarState();
    if (data && data.configured) {
        setSplashLoadingStatus(100, 'Settings loaded. Opening chat...');
        el.statusText.textContent = 'Welcome back! Settings loaded.';
        state.myHandyKey = data.handy_key;
        state.myPersonaDescription = data.persona || '';
        populatePersonaPromptOptions(data.persona_prompts, data.persona);
        if (data.ai_name) {
            state.aiName = data.ai_name;
            el.aiNameInput.value = state.aiName;
            D.querySelector('#typing-indicator .speaker-name').textContent = state.aiName;
        }
        if (data.pfp) {
            el.pfpPreview.src = data.pfp;
            el.typingIndicatorPfp.src = data.pfp;
            if (el.profileMenuPfp) el.profileMenuPfp.src = data.pfp;
        }
        populateModelOptions(data.ollama_models, data.ollama_model, data.ollama_status);
        populateOllamaThinkingSetting(data.ollama_thinking_enabled);
        populateLongTermMemorySetting(data.memory_status, data.use_long_term_memory);
        populatePromptModeSetting(data.llm_prompt_mode, data.llm_prompt_mode_options);
        populateUserGenitaliaSetting(data.user_genitalia, data.user_genitalia_custom, data.user_genitalia_options);
        populateDiagnosticsSettings(data);
        updateOllamaStatus(data.ollama_status);
        populateDeviceSettings(data);
        populateMotionSettings(data);
        populateAudioSettings(data);
        populateVoiceInputSettings(data);
        if (data.elevenlabs_key) {
            el.elevenLabsKeyInput.value = data.elevenlabs_key;
            el.elevenLabsVoiceSelect.dataset.savedVoiceId = data.elevenlabs_voice_id || '';
            el.setElevenLabsKeyButton.click();
        }
        hideSplashScreen();
        renderSetup(true, data);
        refreshStartupOllamaStatus(data);
        refreshLocalTtsStatus();
    } else {
        setSplashLoadingStatus(92, 'Preparing first-run setup...');
        populatePersonaPromptOptions(data && data.persona_prompts, data && data.persona);
        populateModelOptions(data && data.ollama_models, data && data.ollama_model, data && data.ollama_status);
        populateOllamaThinkingSetting(data && data.ollama_thinking_enabled);
        populateLongTermMemorySetting(data && data.memory_status, data && data.use_long_term_memory);
        populatePromptModeSetting(data && data.llm_prompt_mode, data && data.llm_prompt_mode_options);
        populateUserGenitaliaSetting(data && data.user_genitalia, data && data.user_genitalia_custom, data && data.user_genitalia_options);
        populateDiagnosticsSettings(data || {});
        updateOllamaStatus(data && data.ollama_status);
        populateDeviceSettings(data || {});
        populateMotionSettings(data || {});
        populateLocalStyleOptions(data && (data.local_tts_style_presets || (data.local_tts_status && data.local_tts_status.style_presets)));
        populateLocalEngineOptions(
            data && (data.local_tts_engines || (data.local_tts_status && data.local_tts_status.engines)),
            data && (data.local_tts_engine || (data.local_tts_status && data.local_tts_status.engine)),
        );
        updateLocalTtsStatus(data && data.local_tts_status);
        updateAudioProviderUi();
        populateVoiceInputSettings(data || {});
        refreshStartupOllamaStatus(data || {});
        refreshLocalTtsStatus();
        fadeSplashToSetup(data || {});
    }
}
