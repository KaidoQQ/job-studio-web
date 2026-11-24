import os
from pathlib import Path

from dotenv import load_dotenv

# The MCP client can launch the server from an unrelated working directory.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False,
            interpolate=False, encoding="utf-8-sig")


def model_name(provider):
    defaults = {"infercom": "gpt-oss-120b", "gemini": "gemini-2.5-flash-lite"}
    return os.environ.get(f"{provider.upper()}_MODEL") or defaults[provider]


def get_key(name):
    if os.environ.get(name):
        return os.environ[name]
    import keyring

    try:
        return keyring.get_password("UpWorkAITool", name)
    except keyring.errors.NoKeyringError:
        return None
