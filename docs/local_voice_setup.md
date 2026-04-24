# Local Voice Setup

The normal app setup installs the local voice package stack from `requirements.txt`. If that resolves to CPU-only Torch, Local Chatterbox can work but generation may be slow. For low-latency local voice on an NVIDIA GPU, install a CUDA PyTorch wheel after the normal app setup.

If these commands stop matching your driver or platform, use the [official PyTorch selector](https://pytorch.org/get-started/locally/). Python 3.10 or newer is required by current PyTorch builds; Python 3.11 is recommended for the rest of the app.

## Windows

NVIDIA GPU (CUDA 12.8):

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip uninstall -y torch torchvision torchaudio
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

CPU-only fallback:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

## macOS

macOS does not use CUDA. Install the normal PyTorch packages:

```bash
source .venv/bin/activate
python -m pip install torch torchvision torchaudio
```

The app selects CUDA when available and falls back to CPU otherwise, so macOS local voice may still be slower than an NVIDIA CUDA setup on Windows or Linux.

## Linux

NVIDIA GPU (CUDA 12.8):

```bash
source .venv/bin/activate
python -m pip uninstall -y torch torchvision torchaudio
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

CPU-only fallback:

```bash
source .venv/bin/activate
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

For AMD ROCm on Linux, use the [official PyTorch selector](https://pytorch.org/get-started/locally/) and pick the matching ROCm build.

## Verify

From the activated `.venv`:

```bash
python -c "import torch; print('Torch:', torch.__version__); print('CUDA available:', torch.cuda.is_available()); print('CUDA build:', torch.version.cuda); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

If `CUDA available` is `False`, local Chatterbox will run on CPU. That works but latency may be high.

## In The App

After installing PyTorch:

1. Open **Open Settings → Voice**.
2. Click **Download / Load Local Voice Model**. First use can download several GB.
3. Use the **Chatterbox Turbo** preset for the lowest latency.

The Voice tab reports Torch/CUDA status, download/load phase, generation status, missing sample files, and the last local voice error. Longer replies are split into smaller audio chunks so playback can start sooner.

For voice cloning or style reference, click **Browse** in the Voice tab to choose a sample audio file.
