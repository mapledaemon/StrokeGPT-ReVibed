# StrokeGPT-ReVibed

StrokeGPT-ReVibed is a work-in-progress refactor of StrokeGPT for controlling The Handy through a local web app, an Ollama language model, and optional voice output.

The current focus is stability:

- Safer motion interpretation and smoothing
- A cleaner Python package layout
- A unified settings UI
- Ollama model selection
- Optional ElevenLabs or local Chatterbox voice output
- Regression tests for the new control layer

## Status

This is not a finished release. Expect rough edges in the UI, local voice setup, and documentation.

The app currently targets Windows first. Generic Python instructions are included for advanced users.

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

You can add or switch models later in the app under **Open Settings -> Model**.

## Windows Install

1. Install Python.

   Download Python from <https://www.python.org/downloads/windows/>.

   During install, enable **Add python.exe to PATH**.

2. Install Ollama.

   Download Ollama from <https://ollama.com/download/windows>.

3. Open PowerShell in the project folder.

   In File Explorer, open the `StrokeGPT-ReVibed` folder, click the address bar, type `powershell`, and press Enter.

4. Run the installer script.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install_windows.ps1
```

The script will:

- Create `.venv`
- Install Python dependencies from `requirements.txt`
- Pull the default Ollama model if `ollama` is available

5. Start the app.

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

6. Open the app.

Go to:

```text
http://127.0.0.1:5000
```

## Generic Python Install

Use these instructions if you do not want to use the Windows script.

1. Create a virtual environment.

```bash
python -m venv .venv
```

2. Activate the environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

3. Install dependencies.

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

4. Pull the default Ollama model.

```bash
ollama pull nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b
```

5. Run the app.

```bash
python app.py
```

6. Open:

```text
http://127.0.0.1:5000
```

## Running Later

After installation, you only need:

Windows PowerShell:

```powershell
cd path\to\StrokeGPT-ReVibed
.\.venv\Scripts\Activate.ps1
python app.py
```

Then open:

```text
http://127.0.0.1:5000
```

## Voice Output

Voice settings are in **Open Settings -> Voice**.

Available providers:

- **ElevenLabs API**: external API voice output
- **Local Chatterbox**: local ML voice output

Local Chatterbox is heavier than the rest of the app. Python 3.11 is recommended. If installation fails on a newer Python version, install Python 3.11 and rerun the installer.

For local Chatterbox voice cloning/style reference, use **Browse** in the Voice tab to choose a sample audio file.

## Motion Settings

Motion settings are in **Open Settings -> Motion**.

You can adjust:

- Speed limits
- Auto mode timing
- Edging mode timing
- Milking mode timing

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

The model must already be available in Ollama. Pull new models with:

```bash
ollama pull model-name:tag
```

## Development

Run the test suite:

```bash
python -m unittest test_audio_service.py test_motion_control.py test_configuration.py test_handy_controller.py test_motion_scripts.py test_web_static_assets.py
```

Compile-check Python files:

```bash
python -m py_compile app.py strokegpt/*.py test_*.py
```

GitHub Actions runs these checks on Python 3.11 for pushes to `master` or `main` and for pull requests. The CI job installs the lightweight dependencies needed by the current regression tests (`Flask`, `requests`, and `elevenlabs`) and intentionally does not install `chatterbox-tts`; local Chatterbox checks stay opt-in because that stack is large and hardware-sensitive.

## Project Layout

```text
app.py                  Launcher
index.html              Web UI
requirements.txt        Python dependencies
strokegpt/              Backend package
test_*.py              Regression tests
static/                 Static images
scripts/                Utility scripts
```

## Attribution

StrokeGPT-ReVibed is derived from StrokeGPT:

<https://github.com/StrokeGPT/StrokeGPT>

This fork preserves attribution and repository history. It is not affiliated with the original project maintainers.

The original repository did not include a local license file at the time this fork was prepared.
