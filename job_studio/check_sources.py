"""Read-only connectivity check: python -m job_studio.check_sources."""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from .core import DEFAULT, fetch, job_link, public_feed


def check(source):
    try:
        feed = public_feed(source)
        if feed is not None:
            return source["name"], len(feed)
        doc = fetch(source["url"])
        count = sum(job_link(urljoin(source["url"], url)) for url, _ in doc.links)
        return source["name"], count
    except Exception as exc:
        return source["name"], type(exc).__name__


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, result in pool.map(check, DEFAULT["sources"]):
            print(name, result)
