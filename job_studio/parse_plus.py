"""Single-link workflow, independent of the daily source collection."""

import threading
from urllib.parse import urlsplit

from . import core


class ParsePlus:
    def __init__(self, applications):
        self.applications = applications
        self.lock = threading.Lock()
        self.state = dict(
            running=False,
            message="Вставь ссылку на конкретную вакансию",
            job_id=None,
            events=[],
        )

    def log(self, message):
        self.state["message"] = message
        self.state["events"] = (self.state["events"] + [message])[-50:]

    def start(self, url, title="", apply=False):
        core.validate_url(url)
        if not self.lock.acquire(False):
            raise ValueError("Parse plus уже работает")
        self.state = dict(
            running=True, message="Открываю вакансию", job_id=None, events=[]
        )
        threading.Thread(target=self.run, args=(url, title, apply), daemon=True).start()

    def run(self, url, title, apply):
        try:
            canonical = core.canonical(url)
            with core.connect() as db:
                row = db.execute(
                    "SELECT * FROM jobs WHERE url=?", (canonical,)
                ).fetchone()
            if row:
                job = dict(row)
                self.log("Вакансия уже есть — использую сохранённую карточку")
            else:
                self.log("Читаю вакансию: " + urlsplit(url).netloc)
                parsed = core.detail(
                    url,
                    title.strip() or "Вакансия · " + urlsplit(url).netloc,
                    "Parse plus",
                    on_progress=self.log,
                )
                core.put(parsed)
                with core.connect() as db:
                    row = db.execute(
                        "SELECT * FROM jobs WHERE url=?",
                        (core.canonical(parsed["url"]),),
                    ).fetchone()
                    if not row and parsed["company"]:
                        row = db.execute(
                            "SELECT * FROM jobs WHERE lower(company)=lower(?) AND lower(title)=lower(?)",
                            (parsed["company"], parsed["title"]),
                        ).fetchone()
                if not row:
                    raise ValueError("Не удалось сохранить вакансию")
                job = dict(row)
            self.state["job_id"] = job["id"]
            if job["status"] == "applied":
                self.log("Этот отклик уже отмечен отправленным. Повторно не отправляю.")
                return
            if not job["draft"].strip():
                self.log("Готовлю письмо через выбранного AI-провайдера")
                draft = core.generate(job, core.settings())
                with core.connect() as db:
                    db.execute(
                        "UPDATE jobs SET draft=?,status='draft',error='' WHERE id=? AND draft=''",
                        (draft, job["id"]),
                    )
            else:
                self.log("Сохранённое письмо оставлено без изменений")
            if apply:
                self.log("Запускаю заполнение формы")
                self.applications.start(job["id"])
                self.log("Вакансия готова. Ход заполнения — в блоке «Отклик».")
            else:
                self.log(
                    "Вакансия и письмо готовы. Открой карточку для просмотра или отклика."
                )
        except Exception as exc:
            self.log(
                "Не удалось завершить: "
                + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
                + ". Сохранённая карточка доступна ниже, если сбор завершился."
            )
        finally:
            self.state["running"] = False
            self.lock.release()
