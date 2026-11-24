"""One real vacancy + draft smoke test. Uses the saved profile and provider."""

from unittest.mock import patch

from . import core

if __name__ == "__main__":
    cfg = core.settings()
    cfg["sources"] = [s for s in cfg["sources"] if "peopleforce.io" in s["url"]]
    cfg["limit"] = 1
    runner = core.Runner()
    runner.lock.acquire()
    with patch.object(core, "settings", return_value=cfg):
        runner.run(True)
    for event in runner.state["events"]:
        print(event)
    with core.connect() as db:
        print(
            "Saved drafts:",
            db.execute("SELECT count(*) FROM jobs WHERE draft<>''").fetchone()[0],
        )
