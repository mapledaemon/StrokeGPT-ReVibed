# Local Voice Setup

The normal app setup installs `chatterbox-tts==0.1.7` and its supported dependency stack from `requirements.txt`. If that resolves to CPU-only Torch, Local Chatterbox can work but generation may be slow. For low-latency local voice on a supported NVIDIA GPU, install the matching CUDA PyTorch wheels after the normal app setup.

Chatterbox 0.1.7 requires Torch and Torchaudio 2.6.0 on the recommended Python 3.11 runtime. Do not replace them with an unpinned newer PyTorch release: that leaves the environment inconsistent even if CUDA appears available. Python 3.11 is recommended for the app.

## Windows

NVIDIA RTX 20/30/40-series or another Torch 2.6-compatible GPU (CUDA 12.6):

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade "chatterbox-tts==0.1.7"
python -m pip install --force-reinstall --no-deps torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip check
```

RTX 50-series/Blackwell GPUs require a newer PyTorch build than Chatterbox 0.1.7 officially accepts. The Windows installer refuses to replace a working Blackwell stack with incompatible Torch 2.6 wheels. Use CPU voice or ElevenLabs until Chatterbox publishes a compatible dependency set; an upstream package upgrade may change this guidance.

CPU-only fallback:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade "chatterbox-tts==0.1.7"
python -m pip install --force-reinstall --no-deps torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip check
```

## macOS

macOS does not use CUDA. Install the normal PyTorch packages:

```bash
source .venv/bin/activate
python -m pip install --upgrade "chatterbox-tts==0.1.7"
python -m pip install --force-reinstall --no-deps torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0
python -m pip check
```

The app selects CUDA when available and falls back to CPU otherwise, so macOS local voice may still be slower than an NVIDIA CUDA setup on Windows or Linux.

## Linux

NVIDIA GPU supported by Torch 2.6 (CUDA 12.6):

```bash
source .venv/bin/activate
python -m pip install --upgrade "chatterbox-tts==0.1.7"
python -m pip install --force-reinstall --no-deps torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
python -m pip check
```

CPU-only fallback:

```bash
source .venv/bin/activate
python -m pip install --upgrade "chatterbox-tts==0.1.7"
python -m pip install --force-reinstall --no-deps torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip check
```

For AMD ROCm on Linux, use the [official PyTorch selector](https://pytorch.org/get-started/locally/) and pick the matching ROCm build.

## Verify

From the activated `.venv`:

```bash
python -c "import torch; from chatterbox.tts import ChatterboxTTS; from chatterbox.tts_turbo import ChatterboxTurboTTS; device = 'cuda' if torch.cuda.is_available() else 'cpu'; probe = torch.ones(1, device=device); torch.cuda.synchronize() if device == 'cuda' else None; print('Torch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA build:', torch.version.cuda); print('Device:', torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'); print('Chatterbox imports and Torch operation: OK')"
```

If `CUDA available` is `False`, local Chatterbox will run on CPU. That works but latency may be high.

## In The App

After installing PyTorch:

1. Open **Open Settings → Voice**.
2. Click **Download / Load Local Voice Model**. First use can download several GB.
3. Use the **Chatterbox Turbo** preset for the lowest latency.

The Voice tab reports Torch/CUDA status, download/load phase, generation status, missing sample files, and the last local voice error. Longer replies are split into smaller audio chunks so playback can start sooner.

For voice cloning or style reference, click **Browse** in the Voice tab to choose a sample audio file.
