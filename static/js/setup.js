import { D, apiCall, el, state } from './context.js';
import { populateAudioSettings, populateLocalEngineOptions, populateLocalStyleOptions, updateAudioProviderUi, updateLocalTtsStatus } from './audio.js';
import { populateDeviceSettings } from './device-control.js';
import { populateMotionSettings } from './motion-control.js';
import {
    fillPersonaPromptSelect,
    normalizePersonaPrompt,
    populateDiagnosticsSettings,
    populateModelOptions,
    populatePersonaPromptOptions,
    setPersonaPrompt,
    updateOllamaStatus,
} from './settings.js';

export function renderSetup(isReturningUser = false, data = {}) {
    el.setupOverlay.style.display = 'flex';
    let step = isReturningUser ? 2 : 1;
    let setupMinSpeed = data.min_speed ?? 10;

    function displayStep() {
        if (step === 1) {
            el.setupBox.innerHTML = `<h2>Step 1: Handy Key</h2><p>Please enter your connection key from handyfeeling.com</p><input type="password" id="setup-key" class="input-text" placeholder="Handy Key" data-requires-backend><br><button id="setup-next" class="my-button" data-requires-backend>Next</button>`;
            D.getElementById('setup-next').onclick = async () => {
                const key = D.getElementById('setup-key').value.trim();
                if (!key) return;
                state.myHandyKey = key;
                await apiCall('/set_handy_key', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({key: state.myHandyKey}),
                });
                el.handyKeyInput.value = state.myHandyKey;
                el.handyKeyStatus.textContent = 'Connection key saved.';
                el.handyKeyStatus.style.color = 'var(--cyan)';
                step = 2;
                displayStep();
            };
        } else if (step === 2) {
            el.setupBox.innerHTML = `<h2>Step 2: Persona</h2><p>Choose or edit the AI prompt for this session.</p><select id="setup-persona-select" class="select-box"></select><input type="text" id="setup-persona" class="input-text" placeholder="Describe persona"><div class="voice-actions"><button id="setup-save-persona" class="my-button" data-requires-backend>Save Prompt</button><button id="setup-next" class="my-button" data-requires-backend>Continue</button></div>`;
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
    }

    displayStep();
}

export async function startupCheck() {
    const data = await apiCall('/check_settings');
    if (data && data.configured) {
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
        }
        populateModelOptions(data.ollama_models, data.ollama_model);
        populateDiagnosticsSettings(data);
        updateOllamaStatus(data.ollama_status);
        populateDeviceSettings(data);
        populateMotionSettings(data);
        populateAudioSettings(data);
        if (data.elevenlabs_key) {
            el.elevenLabsKeyInput.value = data.elevenlabs_key;
            el.elevenLabsVoiceSelect.dataset.savedVoiceId = data.elevenlabs_voice_id || '';
            el.setElevenLabsKeyButton.click();
        }
        if (localStorage.getItem('sidebar_collapsed') === 'true') {
            D.body.classList.add('sidebar-collapsed');
        }
        D.getElementById('splash-screen').style.display = 'none';
        renderSetup(true, data);
    } else {
        populatePersonaPromptOptions(data && data.persona_prompts, data && data.persona);
        populateModelOptions(data && data.ollama_models, data && data.ollama_model);
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
        const startHandler = event => {
            if (event.key === 'Enter') {
                D.removeEventListener('keydown', startHandler);
                D.getElementById('splash-screen').classList.add('hidden');
                setTimeout(() => renderSetup(false), 1000);
            }
        };
        D.addEventListener('keydown', startHandler);
    }
}
