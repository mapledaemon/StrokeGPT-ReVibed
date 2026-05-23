# Voice input

Voice input supports two local stacks:

- **NVIDIA Parakeet** — preferred low-latency path on compatible NVIDIA CUDA
  systems. Runs in an isolated `.venv-parakeet` runtime so its CUDA wheel
  pins do not conflict with the main app's Torch install.
- **Local faster-whisper** — portable path for CPU, AMD, Apple Silicon, and
  other non-NVIDIA systems.

Push-to-talk and hands-free voice input work with either provider.

## Mobile / LAN browser access

Mobile browsers usually require HTTPS before allowing microphone capture on
LAN addresses. Start StrokeGPT with `STROKEGPT_HOST=0.0.0.0` and
`STROKEGPT_HTTPS=1`, then open the `https://` LAN URL from the mobile
browser. See [lan_https.md](lan_https.md) for the full command, local
certificate trust notes, and Mobile Chrome exact-IP troubleshooting.

## Install (Windows)

`.\scripts\install_windows.ps1` asks whether to install the isolated NVIDIA
Parakeet runtime when an NVIDIA GPU is detected. To install or repair it
manually after the normal app setup:

```powershell
.\scripts\install_parakeet.ps1
```

The installer uses the PyTorch CUDA 12.8 wheel index by default because
RTX 50-series / Blackwell cards (such as the 5070 Ti) need a newer CUDA
wheel than the older CUDA 12.1 stack. It also reapplies NeMo's sensitive
package pins, keeps ONNX's protobuf runtime compatible, and runs `pip check`
before declaring the runtime ready.

Override with `.\scripts\install_parakeet.ps1 -TorchIndexUrl
"https://download.pytorch.org/whl/cu130"` only if the official PyTorch
selector recommends it for your driver.

## In the app

The app auto-detects the repo-local `.venv-parakeet` runtime; set
`STROKEGPT_PARAKEET_PYTHON` only when using a custom runtime.

After the installer, fresh or reset settings select **NVIDIA Parakeet
(preferred on NVIDIA)** when the isolated runtime is configured and NVIDIA
tooling is detected. Existing saved settings are not changed. The Voice tab
offers two presets:

- `nvidia/parakeet-tdt-0.6b-v3` — default preset.
- `nvidia/parakeet-tdt-1.1b` — larger preset.

Use **Profile menu > Settings > Voice > Download / Load Voice Input Model**
before recording. The first load can download multi-GB model files; the
app does not fetch them at startup.

If the separate Parakeet runtime is not configured or NVIDIA tooling is not
detected, fresh or reset settings select **Local faster-whisper**.
Non-NVIDIA users retain all voice-input functionality through
faster-whisper.

## Hands-free mode-action toggle

The Voice tab's **Advanced Flow** section has an off-by-default hands-free
mode-action toggle. When Voice mode is Hands-free and transcripts are sent
through that path, this lets the local model request guarded mode actions
such as Freestyle, Edge, Milk, Legacy Auto, Stop, or an I'm Close signal.
The backend still routes those requests through the same preset-mode guard
rails as the buttons. Legacy Auto is the old scripted takeover loop; use
Freestyle for adaptive pattern selection and continuation.

The Motion tab has a separate off-by-default **Allow typed chat to request
mode actions** toggle. It gives typed chat the same guarded mode-action
path without changing reviewed voice transcript sends.

## Troubleshooting

**"CUDA error: no kernel image is available"** — the isolated Parakeet
runtime can see the GPU, but its installed PyTorch/CUDA kernels cannot run
on that GPU. RTX 50-series cards need the newer installer path; rerun
`.\scripts\install_parakeet.ps1` so `.venv-parakeet` gets the CUDA 12.8
PyTorch wheel. If that still fails, switch **Settings > Voice > Voice
input provider** to **Local faster-whisper** for the full fallback path,
or install a custom Parakeet runtime built for that GPU/CUDA stack.

**"Detected incompatible Protobuf Gencode/Runtime versions"** — the isolated
Parakeet runtime has an older protobuf runtime than the ONNX Python modules
were generated with. Rerun `.\scripts\install_parakeet.ps1` to apply the
Parakeet dependency pins again, including the protobuf runtime pin.

**"`np.sctypes` was removed in the NumPy 2.0 release"** — the isolated
Parakeet runtime picked a NumPy line newer than parts of the NeMo dependency
stack currently expect. Update the app and rerun `.\scripts\install_parakeet.ps1`
to apply the NumPy compatibility pin.
