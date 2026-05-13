import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
    def test_windows_installer_prompts_for_optional_runtime_dependencies(self):
        script = (PROJECT_ROOT / "scripts" / "install_windows.ps1").read_text(encoding="utf-8")

        self.assertIn('[string]$InstallPython = "Prompt"', script)
        self.assertIn('[string]$InstallOllama = "Prompt"', script)
        self.assertIn('[string]$InstallCudaTorch = "Prompt"', script)
        self.assertIn('[string]$InstallParakeet = "Prompt"', script)
        self.assertIn('[string]$DownloadOllamaModel = "Prompt"', script)
        self.assertIn('Python.Python.3.11', script)
        self.assertIn('Install-PythonIfRequested', script)
        self.assertIn('Refresh-PathFromRegistry', script)
        self.assertIn('winget install --id $PythonWingetId', script)
        self.assertIn("Read-Host", script)
        self.assertIn("winget install --id Ollama.Ollama", script)
        self.assertIn("Default Ollama model choices", script)
        self.assertIn("VRAM capacity warning", script)
        self.assertIn('Id = "GemmaE4B"', script)
        self.assertIn('if ($ChoiceId -eq "Default")', script)
        self.assertIn("nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e4b", script)
        self.assertIn("nexusriot/Gemma-4-Uncensored-HauhauCS-Aggressive:e2b", script)
        self.assertIn("huihui_ai/granite4.1-abliterated:3b", script)
        self.assertIn("huihui_ai/granite4.1-abliterated:8b", script)
        self.assertIn("6.3 GB", script)
        self.assertIn("4.4 GB", script)
        self.assertIn("2.1 GB", script)
        self.assertIn("5.3 GB", script)
        self.assertIn("& $ollamaCommand pull $choice.Model", script)
        self.assertIn("https://download.pytorch.org/whl/cu128", script)
        self.assertIn("install_parakeet.ps1", script)
        self.assertIn("Legacy model download switch detected", script)

    def test_windows_updater_fast_forwards_without_model_downloads(self):
        script = (PROJECT_ROOT / "scripts" / "update_windows.ps1").read_text(encoding="utf-8")

        self.assertIn('Invoke-Git @("fetch", "origin")', script)
        self.assertIn('Invoke-Git @("merge", "--ff-only", $upstreamRef)', script)
        self.assertIn("status --porcelain --untracked-files=no", script)
        self.assertIn("-NonInteractive", script)
        self.assertIn("-InstallOllama No", script)
        self.assertIn("-InstallCudaTorch No", script)
        self.assertIn("-InstallParakeet No", script)
        self.assertIn("-DownloadOllamaModel No", script)
        self.assertIn("-UpdateParakeet", script)
        self.assertIn("[switch]$RunValidation", script)
        self.assertNotIn("ollama pull", script)

    def test_windows_bootstrap_downloads_or_clones_repo_and_runs_installer(self):
        script = (PROJECT_ROOT / "scripts" / "bootstrap_windows.ps1").read_text(encoding="utf-8")
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('Git.Git', script)
        self.assertIn('git clone', script)
        self.assertIn('archive/refs/heads/master.zip', script)
        self.assertIn('Expand-Archive', script)
        self.assertIn('install_windows.ps1', script)
        self.assertIn('Administrator PowerShell is not required', script)
        self.assertIn('Documents")) "StrokeGPT-ReVibed"', script)
        self.assertIn('raw.githubusercontent.com/mapledaemon/StrokeGPT-ReVibed/master/scripts/bootstrap_windows.ps1', readme)
        self.assertIn('You do not need to run it as', readme)

    def test_parakeet_installer_defaults_to_blackwell_capable_pytorch_wheels(self):
        script = (PROJECT_ROOT / "scripts" / "install_parakeet.ps1").read_text(encoding="utf-8")

        self.assertIn('$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"', script)
        self.assertNotIn("/whl/cu121", script)
        self.assertIn("--force-reinstall --index-url $TorchIndexUrl torch torchvision torchaudio", script)
        self.assertIn("--force-reinstall --no-deps --index-url $TorchIndexUrl torch torchvision torchaudio", script)

    def test_parakeet_installer_preserves_nemo_dependency_pins(self):
        script = (PROJECT_ROOT / "scripts" / "install_parakeet.ps1").read_text(encoding="utf-8")
        requirements = (PROJECT_ROOT / "requirements-parakeet.txt").read_text(encoding="utf-8")

        self.assertIn("fsspec==2024.12.0", requirements)
        self.assertIn("setuptools>=79.0.0", requirements)
        self.assertIn('pip install "fsspec==2024.12.0" "setuptools>=79.0.0"', script)
        self.assertIn("-m pip check", script)


if __name__ == "__main__":
    unittest.main()
