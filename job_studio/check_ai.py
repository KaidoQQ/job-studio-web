"""Check one configured provider using a short prompt."""
import argparse

from .core import complete_prompt
from .credentials import get_key, model_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=("infercom", "gemini"),
                        nargs="?", default="infercom")
    provider = parser.parse_args().provider
    variable = "INFERCOM_API_KEY" if provider == "infercom" else "GEMINI_API"
    if not get_key(variable):
        parser.exit(1, f"Set {variable} in .env before testing {provider}.\n")
    try:
        complete_prompt("Reply with OK.", {"provider": provider, "fallback": False})
    except RuntimeError as error:
        parser.exit(1, f"{model_name(provider)}: {error}\n")
    print(f"{provider} / {model_name(provider)}: response received")


if __name__ == "__main__":
    main()
