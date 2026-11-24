"""Process an explicitly selected shortlist, newest eligible vacancy first."""

import argparse
import json
import time

from .mcp_server import request


def run(selected):
    state = request("/api/state")
    while state["application"]["running"]:
        time.sleep(2)
        state = request("/api/state")
    jobs = [
        job
        for job in state["jobs"]
        if job["id"] in selected and job["status"] not in ("applied", "archived")
    ]
    jobs.sort(key=lambda job: job.get("published_at") or "", reverse=True)
    for job in jobs:
        try:
            request("/api/apply", {"id": job["id"]})
        except ValueError as error:
            print(job["title"], str(error), flush=True)
            continue
        while True:
            state = request("/api/state")
            current = state["application"]
            if current["job_id"] != job["id"]:
                raise RuntimeError("Application changed in Job Studio")
            if current["waiting"]:
                print(
                    json.dumps(
                        {"job": job["title"], "waiting": current["message"]},
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                # Leave the live form available to the operator. Resume the queue
                # automatically after the operator answers or skips this vacancy.
                while current["running"] and current["waiting"]:
                    time.sleep(2)
                    current = request("/api/state")["application"]
            if not current["running"]:
                print(
                    json.dumps(
                        {"job": job["title"], "result": current["message"]},
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
                break
            time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_ids", nargs="+")
    run(set(parser.parse_args().job_ids))
