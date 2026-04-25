# StrokeGPT-ReVibed

Local Flask web app for controlling The Handy with a local LLM (Ollama) and optional voice. Natural-language motion is filtered through a deterministic safety layer before it reaches the device, so configured speed limits and the explicit Stop button always interrupt motion regardless of what the model said.

## Status

Experimental local app, not a finished release. Expect rough edges in the UI, local voice setup, and motion tuning. Windows is the primary target; macOS and Linux work with equivalent Python steps.

- [ROADMAP.md](ROADMAP.md) — planned work, prioritized.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — current visible rough edges.
- [Changelog.txt](Changelog.txt) — pull request history.

## What You Need

- Python 3.11 (recommended, especially for local voice)
- [Ollama](https://docs.ollama.com/) running locally
- A Handy connection key (the device API requires internet)
- Optional: ElevenLabs API key for hosted voice
- Optional: NVIDIA GPU with CUDA-enabled PyTorch for fast local voice

Default Ollama model: `nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b`. Switch or download other models from **Open Settings → Model**.

## Install

### 1. Install Python and Ollama

- **Windows:** [Python](https://www.python.org/downloads/windows/) (enable *Add python.exe to PATH*) and [Ollama](https://docs.ollama.com/windows). Leave Ollama running in the background.
- **macOS:** [Python](https://www.python.org/downloads/macos/) and [Ollama](https://docs.ollama.com/macos). Open Ollama once after install so the `ollama` command is on PATH.
- **Linux (Debian/Ubuntu):**

  ```bash
  sudo apt update
  sudo apt install python3 python3-venv python3-pip curl
  curl -fsSL https://ollama.com/install.sh | sh
  ```

  Use your distro's equivalent packages if you are not on Debian or Ubuntu.

### 2. Set up the project

From the `StrokeGPT-ReVibed` folder:

**Windows (PowerShell):**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\install_windows.ps1
```

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This creates `.venv` and installs `requirements.txt`. Model downloads start from inside the app so the UI can show progress.

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

## First Run

1. Paste your Handy connection key in **Open Settings → Device**.
2. Pick a model in **Open Settings → Model**. Click **Download Model** if it isn't installed yet (this can pull several GB through Ollama).
3. Optional: enable voice in **Open Settings → Voice**. See [Local Voice](#local-voice) below if you want low-latency local voice on a GPU.
4. Start chatting. The Handy responds to natural-language motion ("slow tip teasing", "deep slow stroke", "milk me"), named patterns (*flick*, *flutter*, *pulse*, *wave*, *ramp*, *ladder*, *surge*, *sway*, *tease*), and soft-anchor loops between *tip*, *shaft*, and *base*.

Start conservatively. The Handy can be intense even at low speed values.

## Configuration

Everything is in **Open Settings**. Tabs:

- **Persona** — change the AI persona prompt and display name.
- **Model** — pick or download Ollama models, switch the active model, see install state.
- **Voice** — pick ElevenLabs or local Chatterbox, configure voice samples, see Torch/CUDA status.
- **Device** — Handy key, stroke range, range test.
- **Motion** — speed limits, motion backend (HAMP continuous is the default; flexible position/script is experimental), Auto/Edge/Milk timings, motion pattern enable/disable, weights, import/export, thumbs feedback.
- **Advanced** — diagnostics verbosity and **Reset All Settings** (clears the saved settings file, stops motion, returns to setup).

The motion connector accepts direct numeric moves from the model and named cues like `tip`, `shaft`, `base`, `full`, `flick`, `flutter`, `pulse`, `wave`, `ramp`, `ladder`, `surge`, `sway`, `tease`. It also accepts any enabled fixed pattern id from Motion Pattern Preferences, including Edge and Milk patterns. Soft anchor loops are supported with 2–6 anchors (e.g., `tip → shaft → base`) plus tempo and softness. All cues route through the deterministic motion layer so configured speed limits, smoothing, and stop behavior are preserved.

Thumbs up raises a fixed pattern's weight, thumbs down lowers it, three thumbs down auto-disables it. Disabled or zero-weight patterns are hidden from the model but stay visible in Motion settings so you can re-enable them.

## Local Voice

The normal app setup installs the local voice package stack from `requirements.txt`. If that resolves to CPU-only Torch, Local Chatterbox can work but generation may be slow.

For low-latency local voice on an NVIDIA GPU, install a CUDA-enabled PyTorch wheel after the normal setup. See [docs/local_voice_setup.md](docs/local_voice_setup.md) for platform-specific commands and verification steps.

In the app, click **Open Settings → Voice → Download / Load Local Voice Model** before testing. First use can download several GB. Use the **Chatterbox Turbo** preset for the lowest latency. The Voice tab reports download/load phase, generation status, missing sample files, and the last error.

## Troubleshooting

- **Port 5000 in use** — the app picks the next free local port automatically. Watch the terminal for the actual URL.
- **Ollama download fails inside the app** — make sure Ollama is running, then pull manually:

  ```bash
  ollama pull nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b
  ```

- **Local voice is slow / "CPU-only Torch" warning** — install CUDA PyTorch (see [docs/local_voice_setup.md](docs/local_voice_setup.md)), use **Chatterbox Turbo**, or switch to ElevenLabs.
- **Chatterbox install fails on Python 3.12+** — recreate `.venv` with Python 3.11.
- **Windows blocks the install script** — the `Set-ExecutionPolicy` command above only relaxes the script policy for that PowerShell process; close and reopen if you need it back to default.
- **Settings appear to save but don't persist** — the browser tab can look responsive while the backend has stopped. Confirm `python app.py` is still running. (Tracked in [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md).)
- **Disk fills up unexpectedly** — Ollama and Chatterbox model weights are large. Make sure the drive used by Ollama has several GB free.
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

Derived from [StrokeGPT](https://github.com/StrokeGPT/StrokeGPT), but has diverged radically at this point. This fork preserves attribution and repository history but is not affiliated with the original maintainers. The original repository did not include a local license file at the time this fork was prepared, but the original maintainer states that the code is free to use. See [here](https://discuss.eroscripts.com/t/strokegpt-a-free-customisable-chatbot-for-the-handy-that-invents-funscripts-and-fucks-you-in-real-time/271231/257).

## Support Development

This project is free and open source, developed and maintained in my spare time. If you find pleasure in this program, please consider donating, no matter how small.

Donations cover token costs, which currently limit development speed in the ongoing compute shortage, and help with hardware replacements. To request support for a different stroker or toy, open an issue and donate enough to cover the device. Any toys that work on men (including insertables) are fine, nothing larger than a VacuGlide.

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
