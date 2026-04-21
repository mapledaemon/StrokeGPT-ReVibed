# StrokeGPT-ReVibed

StrokeGPT-ReVibed is a work-in-progress refactor of StrokeGPT for controlling The Handy through a local web app, an Ollama language model, and optional voice output.

The current focus is reliability, visibility, and local-first control:

- Keep Handy speed limits and stop behavior reliable while improving motion
  expressiveness.
- Make LLM-to-motion mapping more visible, especially tip/base, stroke length,
  range, and smooth alternation.
- Improve UI formatting so chat, settings, model downloads, and device controls
  stay readable at common window sizes.
- Keep model downloads explicit and user-triggered.
- Continue local-first voice work; hosted speech-to-text is not a near-term
  target.
- Add user-visible preference and memory controls so LLM motion adjustments can
  be reviewed, edited, and reset.

See [ROADMAP.md](ROADMAP.md) for planned work such as local voice control,
Handy position visualization, motion style preferences, and preference/memory
editing.

## Status

This is not a finished release. Expect rough edges in the UI, local voice setup,
motion preference handling, and documentation.

The app currently targets Windows first, with equivalent Python setup instructions for macOS and Linux.

## Requirements

- Python, preferably Python 3.11 for local Chatterbox voice support
- Ollama
- A Handy connection key
- Internet access for The Handy API
- Optional: ElevenLabs API key for ElevenLabs voice output

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

## Tips And Pitfalls

- The app prints the URL to open. If port `5000` is already blocked, it will try the next free local port.
- Ollama and Chatterbox model weights can be several GB. Use **Open Settings -> Model -> Download Model** for Ollama models and **Open Settings -> Voice -> Download / Load Local Voice Model** for Chatterbox.
- Python 3.11 is the safest choice for local Chatterbox voice. If Chatterbox fails on a newer Python, recreate `.venv` with Python 3.11.
- Local Chatterbox voice is slow with CPU-only Torch, even on a high-end CPU. For low-latency local voice, use **Chatterbox Turbo** and install CUDA-enabled PyTorch from the [official PyTorch selector](https://pytorch.org/get-started/locally/).
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

For low-latency local voice, use **Chatterbox Turbo** and a CUDA-enabled PyTorch install. If the Voice tab reports CPU-only Torch, local voice generation may be slow even on a high-end CPU. Click **Download / Load Local Voice Model** before testing local voice; first use can download several GB. Longer replies are split into smaller audio chunks so playback can start sooner.

## Motion Settings

Motion settings are in **Open Settings -> Motion**.

You can adjust:

- Speed limits
- Auto mode timing
- Edging mode timing
- Milking mode timing

The motion connector accepts direct numeric movement requests from the model and named cues such as tip, base, full, flick, pulse, wave, ramp, and tease. Those cues are translated into Handy movement targets while preserving the configured speed limits and stop behavior.

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
ROADMAP.md             Planned local voice, motion, device, and UI work
requirements.txt        Python dependencies
strokegpt/              Backend package
strokegpt/motion_patterns.py
                        Normalized reusable motion pattern shapes
tests/                  Regression tests
static/app.css          Web UI styles
static/app.js           Web UI behavior
static/                 Static images
scripts/                Utility scripts
```

## Attribution

StrokeGPT-ReVibed is derived from StrokeGPT:

<https://github.com/StrokeGPT/StrokeGPT>

This fork preserves attribution and repository history. It is not affiliated with the original project maintainers.

The original repository did not include a local license file at the time this fork was prepared.
