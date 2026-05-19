# StrokeGPT-ReVibed

Local Flask web app for controlling The Handy with a local Ollama model,
deterministic motion guardrails, and optional voice input/output.

## What it does

- **Natural-language Handy control** through a local Ollama model.
- **Adaptive Freestyle, preset modes, named patterns, and soft-anchor loops**
  between *tip*, *shaft*, and *base*.
- **Deterministic motion safety** for speed limits, smoothing, and stop
  behavior before commands reach hardware.
- **Motion Pattern Studio** for funscript import, drawing, crop/edit,
  preview, and save.
- **Programs (funscripts)** for saving, playing, and clipping long authored
  timelines separately from short LLM-selectable loop patterns.
- **Optional voice** with ElevenLabs or local Chatterbox for output, plus
  Parakeet or faster-whisper for input.
- **Single-operator local app:** one trusted browser session, one Handy, no
  hosted account.

## Status

Experimental local app, not a finished release. Expect rough edges in the
UI, local voice setup, and motion tuning. Windows is the primary target;
macOS and Linux work with equivalent Python steps.

- [ROADMAP.md](ROADMAP.md) — planned work, prioritized.
- [KNOWN_PROBLEMS.md](KNOWN_PROBLEMS.md) — current visible rough edges.
- [Changelog.txt](Changelog.txt) — pull request history.

## What you need

- A Handy connection key (the device API requires internet).
- **Windows:** PowerShell and an internet connection. The installer can
  install Git, Python 3.11, Ollama, and optional voice dependencies when
  `winget` is available.
- **macOS / Linux:** Python 3.11 and [Ollama](https://docs.ollama.com/)
  running locally.
- Optional: ElevenLabs API key for hosted voice.
- Optional: NVIDIA GPU with CUDA-enabled PyTorch for fast local voice.

Default LLM: `nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b` (a
6.3 GB uncensored Gemma 4 finetune). Swap it for any other Ollama model
from **Profile menu > Settings > Model**.

## Install (Windows)

Open **PowerShell** from the Start menu — no admin needed, though `winget`
may show a normal UAC prompt while installing Git, Python, Ollama, or
driver-adjacent components. Paste this command and press Enter:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; $bootstrap = Join-Path $env:TEMP "strokegpt-bootstrap.ps1"; Invoke-WebRequest -Uri "https://raw.githubusercontent.com/mapledaemon/StrokeGPT-ReVibed/master/scripts/bootstrap_windows.ps1" -OutFile $bootstrap; powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap
```

The leading `Set-ExecutionPolicy ... -Scope Process` only relaxes script
policy for that one PowerShell window; close the window and the default
is restored.

The bootstrap script:

- Downloads StrokeGPT-ReVibed to `Documents\StrokeGPT-ReVibed`.
- Installs Git for Windows when missing.
- Creates `.venv` and installs app dependencies.
- Offers Python 3.11, Ollama, a default Ollama model, CUDA-enabled
  PyTorch, and the isolated NVIDIA Parakeet runtime when useful.

After install, double-click **`Run StrokeGPT-ReVibed.cmd`** in the install
folder to start the app — it launches the venv and opens the browser once
the local port is chosen. Leave that launcher window open while using the
app.

For LAN/mobile voice, double-click **`Run StrokeGPT-ReVibed HTTPS.bat`**
instead. It starts the app on port 5011 with HTTPS enabled so mobile
browsers can request microphone permission.

**Prefer to install manually?** Download the repo with **Code > Download
ZIP**, extract it, open PowerShell inside the extracted folder, and run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\scripts\install_windows.ps1
```

## Install (macOS / Linux)

Install **Python 3.11** and **Ollama** first.

- **macOS:** [python.org](https://www.python.org/downloads/macos/) and
  [Ollama for macOS](https://docs.ollama.com/macos). Open Ollama once
  after install so the `ollama` command is on PATH.
- **Debian / Ubuntu:**

  ```bash
  sudo apt update
  sudo apt install python3 python3-venv python3-pip curl
  curl -fsSL https://ollama.com/install.sh | sh
  ```

  Use your distro's equivalent packages on other Linux systems.

Then from the `StrokeGPT-ReVibed` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open the URL printed in the terminal (usually `http://127.0.0.1:5000`).
If port 5000 is busy, the app picks the next free local port.

## First run

1. Paste your Handy connection key in **Profile menu > Settings > Device**.
2. Pick a model in **Settings > Model**. Click **Download Model** if it
   isn't installed yet (can pull several GB through Ollama).
3. Optional: **Settings > Diagnostics > Run Setup Checks** verifies Ollama,
   model GPU use, and voice dependencies.
   From PowerShell you can also run `.\scripts\verify_setup.ps1` before
   launching the app. It checks Python, required imports, Ollama reachability,
   Torch/CUDA, local port availability, and writable runtime folders without
   downloading models.
4. Optional: enable voice in **Settings > Voice**. See
   [docs/voice_input.md](docs/voice_input.md) and
   [docs/local_voice_setup.md](docs/local_voice_setup.md) for low-latency
   local voice.
5. Start chatting. Try "slow tip teasing", "milk me", "deep slow stroke",
   or a named pattern like *flick* or *ramp*.

**Start conservatively.** The Handy can be intense even at low speed
values.

StrokeGPT-ReVibed is a single-operator local controller: one browser tab,
one Flask process, one Handy. Multiple tabs share queues and device state,
so keep one active tab while controlling hardware. The browser warns when
it sees another recent tab.

## Use from another device on LAN

For LAN/mobile voice, double-click **`Run StrokeGPT-ReVibed HTTPS.bat`**
on Windows, then open `https://<PC-LAN-IP>:5011` from the other device.
Mobile browser microphone capture needs HTTPS. Full setup, certificate
trust, mobile Chrome, and slow-chat checks live in
[docs/lan_https.md](docs/lan_https.md).

## Settings tour

Everything is in **Profile menu > Settings**. Tabs:

- **Persona** - AI persona prompt and display name.
- **Model** - active Ollama model, editable model list, install state,
  sizes, thinking toggle, and GPU/VRAM status.
- **Voice** - TTS provider, voice samples, Torch/CUDA status, microphone
  selection, and ASR provider. See [docs/voice_input.md](docs/voice_input.md)
  for Parakeet/faster-whisper setup and mode-action toggles.
- **Device** - Handy key, firmware v3/v4 path, stroke range, and range
  test.
- **Motion** - speed limits, backend, preset timing, pattern weights,
  pattern/program import/export/rename/playback, Program section clipping, and
  thumbs feedback.
- **Prompts** - read-only view of the system prompts sent to the local
  model.
- **Diagnostics** - setup checks, runtime latency tests, system/app status,
  and motion transport capture for real-device sessions.
- **Advanced** - **Reset All Settings** stops motion, clears saved settings,
  and returns to setup.

## Update an existing install

Close the app, then from the `StrokeGPT-ReVibed` folder run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\scripts\update_windows.ps1
```

The updater fast-forwards the Git checkout, refreshes `.venv`
dependencies, and keeps model downloads inside the app so progress stays
visible. It refuses to overwrite tracked local edits — commit or stash
code changes first. Untracked local settings such as `my_settings.json`
are left alone. Use `.\scripts\update_windows.ps1 -UpdateParakeet` to also
refresh the isolated NVIDIA Parakeet runtime.

On macOS / Linux, from inside the `.venv`: `git pull` and then
`python -m pip install -r requirements.txt --upgrade`.

## GPU and model sizing

Model file size is not the whole runtime memory cost. If chat is slow or
Ollama reports CPU-only execution, see
[docs/ollama_gpu.md](docs/ollama_gpu.md) for model sizing, GPU/VRAM checks,
AMD/Intel/Vulkan setup, and multi-GPU notes.

For fast local Chatterbox TTS on NVIDIA, the Windows installer can install
CUDA-enabled PyTorch automatically. For manual or non-Windows setup, see
[docs/local_voice_setup.md](docs/local_voice_setup.md).

## Troubleshooting

- **Port 5000 in use** — the app picks the next free local port
  automatically. Watch the terminal for the actual URL.
- **LAN page does not load** - start with `STROKEGPT_HOST=0.0.0.0`, use
  the host PC's IPv4 address, allow Python through the firewall for
  private networks, and see [docs/lan_https.md](docs/lan_https.md).
- **Voice input fails on mobile LAN** - mobile browsers usually require
  HTTPS or `localhost` before allowing microphone capture. Use the HTTPS
  launcher and see [docs/lan_https.md](docs/lan_https.md).
- **Mobile Chrome refuses the HTTPS LAN page** - make sure the URL uses the
  exact PC IPv4 address; Chrome-specific certificate steps are in
  [docs/lan_https.md](docs/lan_https.md).
- **Ollama download fails inside the app** — make sure Ollama is running,
  then pull manually:

  ```bash
  ollama pull nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b
  ```

- **Local voice is slow / "CPU-only Torch" warning** — install CUDA
  PyTorch (see [docs/local_voice_setup.md](docs/local_voice_setup.md)),
  use **Chatterbox Turbo**, or switch to ElevenLabs.
- **Parakeet reports "CUDA error: no kernel image is available"** — see
  [docs/voice_input.md](docs/voice_input.md). RTX 50-series cards need the
  CUDA 12.8 wheel; rerun `.\scripts\install_parakeet.ps1`. If that still
  fails, switch **Settings > Voice > Voice input provider** to **Local
  faster-whisper**.
- **Chatterbox install fails on Python 3.12+** — recreate `.venv` with
  Python 3.11.
- **Windows blocks the install script** — the `Set-ExecutionPolicy`
  command above relaxes script policy for that PowerShell window only;
  close it and the default is restored.
- **Settings appear blocked or show connection errors** — confirm
  `python app.py` is still running. The browser shows a connection-lost
  banner and locks backend-required controls until a request succeeds
  again.
- **Disk fills up unexpectedly** — Ollama and Chatterbox model weights are
  large. Make sure the drive used by Ollama has several GB free.
- **Chat replies appear in the wrong tab** — use one active browser tab
  while controlling hardware. The app shares chat queues, settings, mode
  state, and the same Handy connection across tabs, and it warns when
  another recent tab is open.
- **`my_settings.json`** — saved settings live in the project root. Keep
  it private; it can hold API keys and the Handy key.

## Development

Contributors should start with [AGENTS.md](AGENTS.md) — it is the
canonical handoff for both human and coding-agent contributors and covers
architecture, conventions, the test/PR workflow, and current focus areas.

Quick checks:

```bash
python -m unittest discover -s tests
python -m py_compile app.py strokegpt/*.py tests/*.py
```

GitHub Actions runs the same tests on Python 3.11 for pushes to `master`
or `main` and for pull requests. Local Chatterbox is intentionally not
exercised in CI because the stack is large and hardware-sensitive.

## Attribution

Derived from [StrokeGPT](https://github.com/StrokeGPT/StrokeGPT), but has
diverged radically at this point. This fork preserves attribution and
repository history but is not affiliated with the original maintainers.
The original repository did not include a local license file at the time
this fork was prepared, but the original maintainer states that the code
is "fully open-source"
([archived discussion](https://web.archive.org/web/20260423111210/https://discuss.eroscripts.com/t/strokegpt-a-free-customisable-chatbot-for-the-handy-that-invents-funscripts-and-fucks-you-in-real-time/271231/257)).

## Support Development

This project is free and open source, developed and maintained in my
spare time. If you find pleasure in this program, please consider
donating, no matter how small.

Donations cover token costs (which currently limit development speed in
the ongoing compute shortage) and help with hardware replacements. To
request support for a different stroker or toy, open an issue and donate
enough to cover the device. Any toys that work on men (including
insertables) are fine, nothing larger than a VacuGlide.

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
