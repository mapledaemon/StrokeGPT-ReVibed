# StrokeGPT-ReVibed

StrokeGPT-ReVibed is a work-in-progress refactor of StrokeGPT for controlling The Handy through a local web app, an Ollama language model, and optional voice output.

The current focus is reliable local control with visible, editable motion
behavior:

- Keep Handy speed limits and stop behavior reliable while improving motion
  expressiveness.
- Make LLM-to-motion mapping more visible, especially tip/base, stroke length,
  range, smooth alternation, speed wording, and the resulting live motion path.
- Keep current motion state visible through compact speed/depth bars and a
  sidebar Handy position indicator.
- Keep motion pattern preferences user-visible through settings weights,
  thumbs feedback, enable/disable controls, and shareable pattern files.
- Keep HAMP continuous motion as the default while preserving the experimental
  flexible position/script backend for pattern testing.
- Improve UI formatting so chat, settings, model downloads, and device controls
  stay readable at common window sizes.
- Keep model downloads explicit and user-triggered.
- Continue local-first voice work; hosted speech-to-text is not a near-term
  target.
- Add user-visible preference and memory controls so LLM motion adjustments can
  be reviewed, edited, and reset.

See [ROADMAP.md](ROADMAP.md) for planned work such as deeper motion training
editing, soft-anchor authoring, motion style preferences, local voice control,
and preference/memory editing. See [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) for
current visible rough edges that are not blocking the active branch.

## Status

This is an experimental local app, not a finished release. Expect rough edges in
the UI, local voice setup, motion tuning, and real-device validation.

The app currently targets Windows first, with equivalent Python setup instructions for macOS and Linux.

## Requirements

- Python, preferably Python 3.11 for local Chatterbox voice support
- Ollama
- A Handy connection key
- Internet access for The Handy API
- Optional: ElevenLabs API key for ElevenLabs voice output
- Optional: CUDA-enabled PyTorch for faster local Chatterbox voice output

Default Ollama model:

```powershell
nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b
```

You can add, switch, and download models later in the app under **Open Settings -> Model**.

## Install On Windows

1. Install [Python](https://www.python.org/downloads/windows/) and [Ollama](https://docs.ollama.com/windows).

   During Python install, enable **Add python.exe to PATH**. Ollama should be left running in the background after install.

2. Open PowerShell in the `StrokeGPT-ReVibed` folder and run setup.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install_windows.ps1
```

This creates `.venv` and installs `requirements.txt`. Model downloads are started from the app so the UI can show what is being downloaded.

3. Start the app.

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Open the URL printed by the app. It is usually:

```text
http://127.0.0.1:5000
```

## Install On macOS

1. Install [Python](https://www.python.org/downloads/macos/) and [Ollama](https://docs.ollama.com/macos).

   Open Ollama once after installing it so the `ollama` command is available in Terminal.

2. Open Terminal in the `StrokeGPT-ReVibed` folder and run setup.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Start the app.

```bash
source .venv/bin/activate
python app.py
```

Open the URL printed by the app. It is usually:

```text
http://127.0.0.1:5000
```

## Install On Linux

1. Install Python, venv support, pip, curl, and [Ollama](https://docs.ollama.com/linux).

   Debian/Ubuntu example:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip curl
curl -fsSL https://ollama.com/install.sh | sh
```

Use your distro's equivalent packages if you are not on Debian or Ubuntu.

2. Open a terminal in the `StrokeGPT-ReVibed` folder and run setup.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. Start the app.

```bash
source .venv/bin/activate
python app.py
```

Open the URL printed by the app. It is usually:

```text
http://127.0.0.1:5000
```

## Install PyTorch For Local Voice

The app can run without manually installing PyTorch, but **Local Chatterbox**
voice is slow with CPU-only Torch. Install PyTorch inside `.venv` after the
normal app setup if you want local voice output, especially on an NVIDIA GPU.

Use the [official PyTorch selector](https://pytorch.org/get-started/locally/)
if these commands stop matching your driver or platform. As of the current
PyTorch stable selector, Python 3.10 or newer is required.

### Windows

For an NVIDIA GPU, install the CUDA 12.8 wheel:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip uninstall -y torch torchvision torchaudio
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

For CPU-only fallback:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### macOS

macOS does not use CUDA. Install the normal PyTorch packages:

```bash
source .venv/bin/activate
python -m pip install torch torchvision torchaudio
```

The current app selects CUDA when available and otherwise falls back to CPU, so
macOS local voice may still be slower than an NVIDIA CUDA setup.

### Linux

For an NVIDIA GPU, install the CUDA 12.8 wheel:

```bash
source .venv/bin/activate
python -m pip uninstall -y torch torchvision torchaudio
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

For CPU-only fallback:

```bash
source .venv/bin/activate
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

For AMD ROCm on Linux, use the official PyTorch selector and choose the ROCm
build that matches your system.

### Verify PyTorch

Run this from the activated `.venv`:

```bash
python -c "import torch; print('Torch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA build:', torch.version.cuda); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

If `CUDA available` is `False`, local Chatterbox voice will run on CPU. That can
work, but latency may be high.

## Tips And Pitfalls

- The app prints the URL to open. If port `5000` is already blocked, it will try the next free local port.
- Ollama and Chatterbox model weights can be several GB. Use **Open Settings -> Model -> Download Model** for Ollama models and **Open Settings -> Voice -> Download / Load Local Voice Model** for Chatterbox.
- Python 3.11 is the safest choice for local Chatterbox voice. If Chatterbox fails on a newer Python, recreate `.venv` with Python 3.11.
- Local Chatterbox voice is slow with CPU-only Torch, even on a high-end CPU. For low-latency local voice, use **Chatterbox Turbo** and the PyTorch install section above.
- Ollama must be running before the app can talk to or download local models. If app-based download fails, run `ollama pull nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b` manually.
- The default Ollama model is large. Make sure the drive used by Ollama has enough free space.
- The Handy needs a connection key and internet access for the Handy API.
- Windows PowerShell may block scripts. The install command above only relaxes script policy for the current PowerShell process.
- Keep `my_settings.json` private. It stores local settings and may contain API keys or device credentials.

## Voice Output

Voice settings are in **Open Settings -> Voice**.

Available providers:

- **ElevenLabs API**: external API voice output
- **Local Chatterbox**: local ML voice output

Local Chatterbox is heavier than the rest of the app. Python 3.11 is recommended. If installation fails on a newer Python version, install Python 3.11 and rerun the installer.

For local Chatterbox voice cloning/style reference, use **Browse** in the Voice tab to choose a sample audio file.

For low-latency local voice, use **Chatterbox Turbo** and a CUDA-enabled PyTorch install. See **Install PyTorch For Local Voice** above. If the Voice tab reports CPU-only Torch, local voice generation may be slow even on a high-end CPU. Click **Download / Load Local Voice Model** before testing local voice; first use can download several GB. The Voice tab reports download/load phase, elapsed time, generation status, missing sample files, and the last local voice error. Longer replies are split into smaller audio chunks so playback can start sooner.

## Motion Settings

Motion settings are in **Open Settings -> Motion**.

You can adjust:

- Speed limits
- Motion backend selection
- Auto mode timing
- Edging mode timing
- Milking mode timing
- Motion pattern enablement, import/export, feedback-derived weights, and
  inline fixed-pattern LLM weight controls

The motion connector accepts direct numeric movement requests from the model and named cues such as tip, shaft, base, full, flick, flutter, pulse, wave, ramp, ladder, surge, sway, and tease. It can also accept any enabled fixed pattern id listed in Motion Pattern Preferences, including the Edge and Milk mode patterns exposed in the Motion Patterns menu. Soft anchor loops are supported too, where the model provides 2-6 anchors such as tip, shaft/middle, and base plus simple feel controls like tempo and softness. Those cues are translated into Handy movement targets while preserving the configured speed limits and stop behavior.

Named motion patterns are prepared through a small funscript-style action pipeline before they are sent to the motion controller. The app sorts and deduplicates action points, smooths sparse patterns with eased intermediate points, repeats reusable shapes without stopping at the seam, limits large position jumps, and removes redundant straight-line points.

Soft anchor loops use robotics-style trajectory ideas: anchors are treated as soft waypoints, Catmull-Rom or minimum-jerk interpolation fills the path between them, and the existing large-step limiter keeps target changes bounded. This is intended for commands like "soft bounce between tip, shaft, and base" without turning the movement into a hard two-point bounce.

Area-only focus commands use moderate default speeds instead of inheriting a previous maximum speed. When a redirect lowers speed and changes the Handy range, the app sends the lower velocity before the new slide bounds so the device does not lurch into the new area at the old speed.

Speed wording sent to the LLM is derived from the configured speed range.
For example, "as fast as you can" maps to the current Motion tab max speed
instead of a hardcoded global value.

The fixed motion patterns shown to the LLM have simple 0-100 weights. Thumbs up
raises a matching fixed pattern's weight, thumbs down lowers it, and three
thumbs down ratings disable that pattern in settings. Disabled fixed patterns
and fixed patterns at weight 0 are not offered to the model for `move.pattern`,
but users can re-enable or raise their weight from **Open Settings -> Motion**.

The app motion backend defaults to **HAMP continuous** for smoother ongoing
movement. **Flexible position/script** is available in Motion settings as an
experimental backend for testing spatial pattern fidelity.

Start conservatively. The Handy can be intense even at low speed values.

## Device Settings

Device settings are in **Open Settings -> Device**.

You can adjust:

- Handy connection key
- Stroke range
- Range test

## Reset Settings

Reset is in **Open Settings -> Advanced**.

**Reset All Settings** clears the saved local settings file, stops active motion, and sends the app back through setup.

## Model Settings

Model settings are in **Open Settings -> Model**.

You can:

- Select a saved Ollama model
- Add a new model name
- Switch the model used by the app
- Download the selected or typed model through Ollama

The app reports whether the current model is installed. **Download Model** uses Ollama and can download several GB. If needed, pull models manually with:

```bash
ollama pull model-name:tag
```

## Development

Run the test suite:

```bash
python -m unittest discover -s tests
```

Compile-check Python files:

```bash
python -m py_compile app.py strokegpt/*.py tests/*.py
```

GitHub Actions runs these checks on Python 3.11 for pushes to `master` or `main` and for pull requests. The CI job installs the lightweight dependencies needed by the current regression tests (`Flask`, `requests`, and `elevenlabs`) and intentionally does not install `chatterbox-tts`; local Chatterbox checks stay opt-in because that stack is large and hardware-sensitive.

## Project Layout

```text
app.py                  Launcher
index.html              Web UI markup
docs/                   Follow-up implementation prompts and planning notes
ROADMAP.md             Planned local voice, motion, device, and UI work
requirements.txt        Python dependencies
strokegpt/              Backend package
strokegpt/pattern_library.py
                        Shareable motion pattern registry and import/export
strokegpt/motion_patterns.py
                        Normalized reusable motion pattern shapes
tests/                  Regression tests
static/app.css          Web UI styles
static/app.js           Web UI entrypoint
static/js/              Web UI behavior modules
static/                 Static images
scripts/                Utility scripts
```

## Attribution

StrokeGPT-ReVibed is derived from StrokeGPT:

<https://github.com/StrokeGPT/StrokeGPT>

This fork preserves attribution and repository history. It is not affiliated with the original project maintainers.

The original repository did not include a local license file at the time this fork was prepared.


## Support Development

This project is free and open source, developed and maintained in my spare time by [me](https://github.com/mapledaemon/). If you find pleasure in this program, please consider donating, no matter how small.

Your donation mainly helps cover token cost, which heavily limits development speed at the moment given the compute shortage. It also helps me afford hardware replacements in this challenging environment. If you want me to integrate support for a different stroker or toy, submit an issue and donate enough to cover the cost. I'll gladly implement it. Any toys for men (including insertables) are fine, just nothing as large as a hismith, vacuglide or smaller.

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
