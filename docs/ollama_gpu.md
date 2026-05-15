# Ollama GPU acceleration

GPU acceleration depends on the hardware path. NVIDIA and Apple Silicon use
their usual Ollama GPU backends when supported. AMD/Radeon may use ROCm for
listed cards, and additional Windows/Linux GPU support is available through
Ollama's experimental Vulkan runner.

## Choosing a model that fits your GPU

The Windows installer prints detected NVIDIA VRAM when `nvidia-smi` is
available. Model size in the installer table is only the model file size;
context and runtime overhead need additional memory. If a model is close to
or above GPU VRAM, Ollama may partially run it in system memory and chat
slows down.

The app checks Ollama's running-model status during setup and warns when the
selected model is loaded but reports no VRAM use. A nonzero `/api/ps`
`size_vram` value is treated as GPU use, even when it is lower than total
loaded model memory. The check is only definitive after Ollama has loaded
the selected model at least once; send one chat message or run
`ollama ps` after loading a model if the status is still unknown. For exact
CPU/GPU split details, use the `ollama ps` Processor column.

## AMD / Intel / non-default GPU paths

If StrokeGPT-ReVibed reports CPU-only Ollama use on hardware that should
have GPU acceleration:

1. Update the vendor GPU driver.
2. Set `OLLAMA_VULKAN=1` for the Ollama server.
3. Restart Ollama.
4. See the official [Ollama hardware support](https://docs.ollama.com/gpu)
   notes.

### Windows Vulkan setup

On Windows, set the Vulkan flag as a **user environment variable** so the
Ollama desktop/tray process sees it when it starts. A temporary PowerShell
variable usually is not enough because Ollama may already be running outside
that terminal.

PowerShell:

```powershell
setx OLLAMA_VULKAN 1
```

Then fully restart Ollama: quit it from the tray icon, stop any existing
`ollama.exe` process if needed, and start Ollama again. Restart Windows if
you are not sure the old process exited.

GUI path:

1. Open **Edit environment variables for your account** from the Start menu.
2. Under **User variables**, add `OLLAMA_VULKAN` with value `1`.
3. Close every Ollama process and start Ollama again.

To undo the setting later, delete `OLLAMA_VULKAN` from the same User
variables screen or run:

```powershell
reg delete HKCU\Environment /v OLLAMA_VULKAN /f
```

After restarting Ollama, load a model and check `ollama ps`; the Processor
column should show GPU/Vulkan use instead of CPU-only execution when the
runner supports your hardware.

`GGML_VK_VISIBLE_DEVICES` can select or disable Vulkan GPUs when multiple
devices are present. On Windows, set it as a user environment variable the
same way if you need it.
