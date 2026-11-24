"""Deterministic, synthetic input. Browser routes never reach these hosts."""

from datetime import datetime, timedelta, timezone
import json

LETTER = "I build fixture services in Python."
QUESTION = "Preferred fixture rotation"
ANSWER = "Morning"
EMAIL = "candidate@example.invalid"


def feed():
    anchor = datetime(2025, 6, 1, tzinfo=timezone.utc)
    jobs = []
    for index in range(100):
        # Last two requisitions intentionally share a company and title.
        label = min(index, 98)
        job = dict(
            title=f"Python engineer {label:03}",
            company=f"Fixture team {label % 12:02}",
            source="M0",
            url=f"https://fixture.traffit.com/public/job/{index:03}",
            description=(
                "Build Python services and test data pipelines. " * 24
            ).strip(),
            location="Remote",
            published_at=(anchor - timedelta(hours=index)).isoformat(),
            expires_at="2020-01-01" if index == 97 else "2099-01-01",
        )
        jobs.append(job)
    return [
        *jobs,
        {
            **jobs[30],
            "description": "Revised specification.",
            "expires_at": "2099-02-01",
        },
    ]


def form(index):
    return f"""<!doctype html><title>Application {index}</title>
      <form><label>Email<input type=email required></label>
      <label>CV<input type=file required></label>
      <label>{QUESTION}<input required></label>
      <label>Cover letter<textarea required></textarea></label>
      <button>Submit application</button></form>
      <script>document.querySelector('form').onsubmit = event => {{
        event.preventDefault();
        const [email, file, rotation, letter] = event.target.elements;
        if (email.value === {json.dumps(EMAIL)} && file.files[0]?.name === 'fixture.pdf'
            && rotation.value === {json.dumps(ANSWER)} && letter.value === {json.dumps(LETTER)})
          document.body.textContent = "Application received";
      }};</script>"""
