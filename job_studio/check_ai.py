"""Small Infercom connectivity probe, without sending CV/profile data."""

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .core import get_key


def main():
    key = get_key("INFERCOM_API_KEY")
    if not key:
        print("Infercom: key not configured")
        return
    request = Request(
        "https://api.infercom.ai/v1/chat/completions",
        data=json.dumps(
            {
                "model": "gpt-oss-120b",
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 64,
            }
        ).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
        print("Infercom: connected; response received:", bool(data.get("choices")))
    except HTTPError as exc:
        print("Infercom HTTP status:", exc.code)
    except Exception as exc:
        print("Infercom:", type(exc).__name__)


if __name__ == "__main__":
    main()
