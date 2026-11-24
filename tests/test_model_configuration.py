"""Import the configuration as a fresh clone launched from another directory."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ModelConfigurationTests(unittest.TestCase):
    def test_clone_dotenv_and_process_precedence(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            clone = Path(folder) / "clone"
            package = clone / "job_studio"
            package.mkdir(parents=True)
            for name in ("credentials.py", "__init__.py"):
                shutil.copy(root / "job_studio" / name, package)
            example = (root / ".env.example").read_text("utf-8")
            (clone / ".env").write_text(
                example.replace("INFERCOM_API_KEY=\n", "INFERCOM_API_KEY=fixture-only\n")
                .replace("INFERCOM_MODEL=gpt-oss-120b", "INFERCOM_MODEL=custom"),
                encoding="utf-8-sig",
            )
            env = dict(os.environ, PYTHONPATH=str(clone), GEMINI_MODEL="override")
            for key in ("INFERCOM_API_KEY", "INFERCOM_MODEL"):
                env.pop(key, None)
            subprocess.run(
                [sys.executable, "-c",
                 "from job_studio.credentials import get_key, model_name\n"
                 "assert get_key('INFERCOM_API_KEY') == 'fixture-only'\n"
                 "assert model_name('infercom') == 'custom'\n"
                 "assert model_name('gemini') == 'override'"],
                cwd=folder, env=env, check=True,
            )
