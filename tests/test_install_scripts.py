import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallScriptTests(unittest.TestCase):
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
