# StrokeGPT-ReVibed

Local Flask web app for controlling The Handy with a local LLM (Ollama) and optional voice. Natural-language motion is filtered through a deterministic safety layer before it reaches the device, so configured speed limits and the explicit Stop button always interrupt motion regardless of what the model said.

## Status

Experimental local app, not a finished release. Expect rough edges in the UI, local voice setup, and motion tuning. Windows is the primary target; macOS and Linux work with equivalent Python steps.

- [ROADMAP.md](ROADMAP.md) — planned work, prioritized.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — current visible rough edges.
- [Changelog.txt](Changelog.txt) — pull request history.

## What You Need

- Windows: PowerShell and an internet connection. The bootstrap and installer can install Git, Python 3.11, Ollama, and optional NVIDIA voice dependencies when `winget` is available.
- macOS / Linux: Python 3.11 and [Ollama](https://docs.ollama.com/) running locally.
- A Handy connection key (the device API requires internet)
- Optional: ElevenLabs API key for hosted voice
- Optional: NVIDIA GPU with CUDA-enabled PyTorch for fast local voice
- Optional: NVIDIA NeMo for the Parakeet voice-input provider

Default Ollama model: `nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b`. Switch or download other models from **Profile menu > Settings > Model**.

## Install

### Windows: first-time setup

Open **PowerShell** from the Windows Start menu. You do not need to run it as
administrator; if `winget` installs Git, Python, Ollama, or driver-adjacent
components, Windows may show a normal UAC prompt. Paste these lines and press
Enter:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$bootstrap = "$env:TEMP\strokegpt-bootstrap.ps1"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/mapledaemon/StrokeGPT-ReVibed/master/scripts/bootstrap_windows.ps1" -OutFile $bootstrap
powershell -ExecutionPolicy Bypass -File $bootstrap
```

The bootstrap script downloads StrokeGPT-ReVibed to
`Documents\StrokeGPT-ReVibed`, installs Git for Windows when needed so future
updates work, and then starts `scripts\install_windows.ps1`. The installer
creates `.venv`, installs Python 3.11 when missing, installs app dependencies,
asks whether to install Ollama when it is missing, offers to download one of the
default Ollama models with live `ollama pull` progress, and asks whether to
install optional NVIDIA CUDA / Parakeet voice components. Voice model downloads
stay inside the app so progress is visible there.

If you do not want to use the bootstrap script, download the repository from
GitHub with **Code > Download ZIP**, extract it, open PowerShell inside the
extracted `StrokeGPT-ReVibed` folder, and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install_windows.ps1
```

### macOS / Linux prerequisites

- **macOS:** [Python](https://www.python.org/downloads/macos/) and [Ollama](https://docs.ollama.com/macos). Open Ollama once after install so the `ollama` command is on PATH.
- **Linux (Debian/Ubuntu):**

  ```bash
  sudo apt update
  sudo apt install python3 python3-venv python3-pip curl
  curl -fsSL https://ollama.com/install.sh | sh
  ```

  Use your distro's equivalent packages if you are not on Debian or Ubuntu.

### macOS / Linux setup

From the `StrokeGPT-ReVibed` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This creates `.venv` and installs `requirements.txt`. Model downloads start from inside the app so the UI can show progress.

### Update an existing checkout

Close the app, then run the updater from the `StrokeGPT-ReVibed` folder:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\update_windows.ps1
```

The updater fast-forwards the Git checkout, updates `.venv` dependencies, and
keeps model downloads inside the app so progress stays visible. It refuses to
overwrite tracked local edits; commit or stash code changes first. Untracked
local settings such as `my_settings.json` are left alone. Use
`.\scripts\update_windows.ps1 -UpdateParakeet` when you also want to refresh the
isolated NVIDIA Parakeet runtime.

### Ollama GPU acceleration

The Windows installer can download one of the four default Ollama model options:

| Model | Size |
| --- | ---: |
| `huihui_ai/granite4.1-abliterated:3b` | 2.1 GB |
| `nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e2b` | 4.4 GB |
| `huihui_ai/granite4.1-abliterated:8b` | 5.3 GB |
| `nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b` | 6.3 GB |

The installer prints detected NVIDIA VRAM when `nvidia-smi` is available. Model
size is only the model file size; context and runtime overhead need additional
memory. If a model is close to or above GPU VRAM, Ollama may partially run it in
system memory and chat can be slow.

The app checks Ollama's running-model status and warns during setup when the selected model is loaded but reports no VRAM use. A nonzero `/api/ps` `size_vram` value is treated as GPU use, even when it is lower than total loaded model memory. The check is only definitive after Ollama has loaded the selected model at least once; send one chat message or run `ollama ps` after loading a model if the status is still unknown. For exact CPU/GPU split details, use the `ollama ps` Processor column.

Ollama GPU setup depends on the hardware path. NVIDIA and Apple systems use their usual Ollama GPU backends when supported. AMD/Radeon support may use ROCm for listed cards, while additional Windows/Linux GPU support is available through Ollama's experimental Vulkan runner. If this app reports CPU-only Ollama use on AMD/Radeon or Intel-class hardware that should have GPU acceleration, update the vendor GPU driver, set `OLLAMA_VULKAN=1` for the Ollama server, restart Ollama, and see the official [Ollama hardware support](https://docs.ollama.com/gpu) notes. `GGML_VK_VISIBLE_DEVICES` can select or disable Vulkan GPUs when multiple devices are present.

### 3. Start the app

**Windows:**

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

**macOS / Linux:**

```bash
source .venv/bin/activate
python app.py
```

Open the URL printed in the terminal (usually <http://127.0.0.1:5000>). If port 5000 is busy, the app picks the next free local port.

StrokeGPT-ReVibed is currently a single-operator local controller: one trusted
local browser session, one Flask process, one Handy controller, and one shared
settings file. Multiple tabs share queues and device state, so use one active
tab while controlling hardware. The browser warns when it sees another recent
StrokeGPT tab.

## First Run

1. Paste your Handy connection key in **Profile menu > Settings > Device**.
2. Pick a model in **Profile menu > Settings > Model**. Click **Download Model** if it isn't installed yet (this can pull several GB through Ollama).
3. Optional: run **Profile menu > Settings > Diagnostics > Run Setup Checks** to verify Ollama, selected-model GPU use, optional voice dependencies, and CUDA visibility.
4. Optional: enable voice in **Profile menu > Settings > Voice**. See [Local Voice](#local-voice) below if you want low-latency local voice on a GPU.
5. Start chatting. The Handy responds to natural-language motion ("slow tip teasing", "deep slow stroke", "milk me"), named patterns (*flick*, *flutter*, *pulse*, *wave*, *ramp*, *ladder*, *surge*, *sway*, *tease*), and soft-anchor loops between *tip*, *shaft*, and *base*.

Start conservatively. The Handy can be intense even at low speed values.

## Configuration

Everything is in **Profile menu > Settings**. Tabs:

- **Persona** — change the AI persona prompt and display name.
- **Model** — pick, download, add, or delete saved Ollama model options; switch the active model; see install state, model sizes, and GPU/VRAM status. The default options include the current Gemma preset plus `huihui_ai/granite4.1-abliterated:3b` (2.1 GB) and `huihui_ai/granite4.1-abliterated:8b` (5.3 GB).
- **Voice** — pick ElevenLabs or local Chatterbox, configure voice samples, see Torch/CUDA status.
- **Device** — Handy key, stroke range, range test.
- **Motion** — speed limits, motion backend (Continuous position is the default; HAMP remains a legacy fallback), Auto/Edge/Milk timings, motion pattern enable/disable, weights, import/export, thumbs feedback.
- **Diagnostics** — setup checks, runtime latency tests for Ollama/loaded voice paths, and diagnostics verbosity.
- **Advanced** — **Reset All Settings** (clears the saved settings file, stops motion, returns to setup).

The motion connector accepts direct numeric moves from the model and named cues like `tip`, `shaft`, `base`, `full`, `flick`, `flutter`, `pulse`, `wave`, `ramp`, `ladder`, `surge`, `sway`, `tease`. It also accepts any enabled fixed pattern id from Motion Pattern Preferences, including Edge and Milk patterns. Soft anchor loops are supported with 2–6 anchors (e.g., `tip → shaft → base`) plus tempo and softness. All cues route through the deterministic motion layer so configured speed limits, smoothing, and stop behavior are preserved.

Thumbs up raises a fixed pattern's weight, thumbs down lowers it, three thumbs down auto-disables it. Disabled or zero-weight patterns are hidden from the model but stay visible in Motion settings so you can re-enable them.

## Local Voice

The normal app setup installs the local voice package stack from `requirements.txt`. If that resolves to CPU-only Torch, Local Chatterbox can work but generation may be slow.

On Windows, `.\scripts\install_windows.ps1` asks whether to install
CUDA-enabled PyTorch for faster local Chatterbox voice when an NVIDIA GPU is
detected. For manual or non-Windows setup, see [docs/local_voice_setup.md](docs/local_voice_setup.md).

In the app, click **Profile menu > Settings > Voice > Download / Load Local Voice Model** before testing. First use can download several GB. Use the **Chatterbox Turbo** preset for the lowest latency. The Voice tab reports download/load phase, generation status, missing sample files, and the last error.

Voice input supports two local stacks. **NVIDIA Parakeet** is the preferred low-latency path on compatible NVIDIA CUDA systems. **Local faster-whisper** remains the portable path for CPU, AMD, Apple Silicon, and non-NVIDIA systems; push-to-talk and hands-free voice input work with either provider.

On Windows, `.\scripts\install_windows.ps1` asks whether to install the
isolated NVIDIA Parakeet runtime when an NVIDIA GPU is detected. To install or
repair it manually after the normal app setup:

```powershell
.\scripts\install_parakeet.ps1
```

The installer uses the PyTorch CUDA 12.8 wheel index by default because RTX 50-series / Blackwell cards such as the 5070 Ti need a newer CUDA wheel than the old CUDA 12.1 stack. It also reapplies NeMo's sensitive package pins and runs `pip check` before declaring the runtime ready. Override with `.\scripts\install_parakeet.ps1 -TorchIndexUrl "https://download.pytorch.org/whl/cu130"` only if the official PyTorch selector recommends it for your driver. The app auto-detects the repo-local `.venv-parakeet` runtime; set `STROKEGPT_PARAKEET_PYTHON` only when using a custom runtime. After the installer, fresh or reset settings select **NVIDIA Parakeet (preferred on NVIDIA)** when the isolated runtime is configured and NVIDIA tooling is detected. Existing saved settings are not changed. The Voice tab offers the default `nvidia/parakeet-tdt-0.6b-v3` preset and the larger `nvidia/parakeet-tdt-1.1b` preset. Use **Profile menu > Settings > Voice > Download / Load Voice Input Model** before recording. The first load can download multi-GB model files; the app does not fetch them at startup.

The Voice tab's **Advanced Flow** section has an off-by-default hands-free
mode-action toggle. When Voice mode is Hands-free and transcripts are sent
through that path, this lets the local model request guarded mode actions such
as Freestyle, Edge, Milk, Legacy Auto, Stop, or an I'm Close signal. The
backend still routes those requests through the same preset-mode guard rails
as the buttons. Legacy Auto is the old scripted takeover loop; use Freestyle
for adaptive pattern selection and continuation.

The Motion tab has a separate off-by-default **Allow typed chat to request
mode actions** toggle. It gives typed chat the same guarded mode-action path
without changing reviewed voice transcript sends.

If the separate Parakeet runtime is not configured or NVIDIA tooling is not detected, fresh or reset settings select **Local faster-whisper**. Non-NVIDIA users retain all voice-input functionality through faster-whisper.

## Troubleshooting

- **Port 5000 in use** — the app picks the next free local port automatically. Watch the terminal for the actual URL.
- **Ollama download fails inside the app** — make sure Ollama is running, then pull manually:

  ```bash
  ollama pull nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b
  ```

- **Local voice is slow / "CPU-only Torch" warning** — install CUDA PyTorch (see [docs/local_voice_setup.md](docs/local_voice_setup.md)), use **Chatterbox Turbo**, or switch to ElevenLabs.
- **Parakeet reports "CUDA error: no kernel image is available"** — the isolated Parakeet runtime can see the GPU, but its installed PyTorch/CUDA kernels cannot run on that GPU. RTX 50-series cards need the newer installer path; rerun `.\scripts\install_parakeet.ps1` so `.venv-parakeet` gets the CUDA 12.8 PyTorch wheel. If that still fails, switch **Settings > Voice > Voice input provider** to **Local faster-whisper** for the full fallback path, or install a custom Parakeet runtime built for that GPU/CUDA stack.
- **Chatterbox install fails on Python 3.12+** — recreate `.venv` with Python 3.11.
- **Windows blocks the install script** — the `Set-ExecutionPolicy` command above only relaxes the script policy for that PowerShell process; close and reopen if you need it back to default.
- **Settings appear blocked or show connection errors** — confirm `python app.py` is still running. When the backend is unreachable, the browser shows a connection-lost banner and locks backend-required controls until a request succeeds again.
- **Disk fills up unexpectedly** — Ollama and Chatterbox model weights are large. Make sure the drive used by Ollama has several GB free.
- **Chat replies or status messages appear in the wrong tab** - use one active browser tab while controlling hardware. The app is a single-operator local controller; tabs share chat/update queues, settings, mode state, and the same Handy connection, and it warns when another recent tab is open.
- **Lost saved settings** — `my_settings.json` lives in the project root. Keep it private; it can hold API keys and the Handy key.

## Development

Contributors should start with [AGENTS.md](AGENTS.md) — it is the canonical handoff for both human and coding-agent contributors and covers architecture, conventions, the test/PR workflow, and current focus areas.

Quick checks:

```bash
python -m unittest discover -s tests
python -m py_compile app.py strokegpt/*.py tests/*.py
```

GitHub Actions runs the same tests on Python 3.11 for pushes to `master` or `main` and for pull requests. Local Chatterbox is intentionally not exercised in CI because the stack is large and hardware-sensitive.

## Attribution

Derived from [StrokeGPT](https://github.com/StrokeGPT/StrokeGPT), but has diverged radically at this point. This fork preserves attribution and repository history but is not affiliated with the original maintainers. The original repository did not include a local license file at the time this fork was prepared, but the original maintainer states that the code is "fully open-source". See [here](https://web.archive.org/web/20260423111210/https://discuss.eroscripts.com/t/strokegpt-a-free-customisable-chatbot-for-the-handy-that-invents-funscripts-and-fucks-you-in-real-time/271231/257).

## Support Development

This project is free and open source, developed and maintained in my spare time. If you find pleasure in this program, please consider donating, no matter how small.

Donations cover token costs, which currently limit development speed in the ongoing compute shortage, and help with hardware replacements. To request support for a different stroker or toy, open an issue and donate enough to cover the device. Any toys that work on men (including insertables) are fine, nothing larger than a VacuGlide.

These wallets are only for this project, so I will know what it is for.

<p align="center">
  <strong>Ethereum</strong><br>
  <img src="./static/ethereum-qr.svg" alt="Ethereum donation QR code" width="132" height="132"><br>
  <code>0x1319841646b196F81283<br>a1bf08d8a0256Cdd414B</code>
</p>

<p align="center">
  <strong>Bitcoin</strong><br>
  <img src="./static/bitcoin-qr.svg" alt="Bitcoin donation QR code" width="132" height="132"><br>
  <code>bc1pwqvmmzhdnmgp3px7l0<br>ltsrrjk7hzlppnhhk6fm3e2l24<br>xdvgpd7srm5zg6</code>
</p>
