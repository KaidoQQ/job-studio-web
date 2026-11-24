"""Single-owner browser worker. No automatic retry after an uncertain submission."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import core
from .site_bots import bot_for, diagnostics

EVENTS_COMMITTED = threading.Condition()
EVENT_WINDOW = 150

APPLICANT = {
    "first_name": "",
    "last_name": "",
    "email": "",
    "phone": "",
    "city": "",
    "country": "Poland",
    "github": "",
    "linkedin": "",
    "notice": "1 month",
    "cv_path": "",
    "salary_expectation": "",
    "hybrid_availability": "",
    "answers": {},
}
FINAL = re.compile(
    r"^(apply|apply now|submit|submit application|send application|send|aplikuj|wyślij|wyślij aplikację|wyślij zgłoszenie)$",
    re.I,
)
NEXT = re.compile(r"^(next|continue|dalej|kontynuuj)$", re.I)
OPEN = re.compile(
    r"^(apply|apply now|apply for this job|apply for this position|submit a proposal|apply to job|aplikuj|aplikuj teraz)$",
    re.I,
)
SUCCESS = re.compile(
    r"^(application received|application submitted|thank you for applying[!.]?|your application has been sent to .+|your application has been received.*|your application has been submitted.*|dziękujemy za aplikację[!.]?|dziękujemy za przesłanie aplikacji[!.]?)$",
    re.I,
)


def applicant():
    path = core.DATA / "applicant.json"
    return {
        **APPLICANT,
        **(json.loads(path.read_text("utf-8")) if path.exists() else {}),
    }


def save_applicant(data):
    clean = {k: data[k] for k in APPLICANT if k in data}
    if not isinstance(clean.get("answers", {}), dict):
        raise ValueError("Answers must map exact field labels to confirmed answers")
    core.DATA.mkdir(exist_ok=True)
    path = core.DATA / "applicant.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps({**applicant(), **clean}, ensure_ascii=False, indent=2), "utf-8"
    )
    temp.replace(path)


def normal(text):
    return (
        re.sub(r"\s+", " ", str(text).lower().replace("*", "").replace("_", " "))
        .strip()
        .rstrip(":")
    )


def answer_for(field, person, draft):
    label = normal(field["label"])
    custom = {normal(k): v for k, v in person.get("answers", {}).items()}
    if label in custom:
        return custom[label]
    mapping = {
        "first_name": ("first name", "firstname", "given name", "imię", "name"),
        "last_name": ("last name", "lastname", "surname", "family name", "nazwisko"),
        "email": ("email", "e-mail", "email address", "adres e-mail"),
        "phone": (
            "phone",
            "phone number",
            "phone numbers",
            "telephone",
            "telefon",
            "numer telefonu",
            "telefon kontaktowy",
            "contact phone",
        ),
        "city": ("city", "location", "miasto", "miejsce zamieszkania"),
        "country": ("country", "country of residence", "kraj"),
        "github": ("github", "github url", "github profile"),
        "linkedin": (
            "linkedin",
            "linkedin url",
            "linkedin profile",
            "link to linkedin account",
        ),
        "notice": (
            "notice period",
            "okres wypowiedzenia",
            "availability",
            "dostępność",
        ),
    }
    if label in (
        "full name",
        "first and last name",
        "enter your first and last name",
        "name and surname",
        "imię i nazwisko",
        "your name",
    ):
        return (person["first_name"] + " " + person["last_name"]).strip()
    if label in ("i want to attach my cv", "attach my cv"):
        return True
    if label in (
        "cover letter",
        "message",
        "yourmessage",
        "your message",
        "enter your message",
        "your message to the employer",
        "message to the employer",
        "list motywacyjny",
        "wiadomość",
    ):
        return draft
    if "okres wypowiedzenia" in label or "notice period" in label:
        if person.get("notice") in (
            "1 month",
            "1 miesiąc",
            "1 miesiac",
        ) and "Month" in field.get("options", []):
            return "Month"
        return person.get("notice")
    if "oczekiwania finansowe" in label or "salary expectation" in label:
        return (
            re.search(r"\d+", person.get("salary_expectation", "")).group()
            if field.get("type") == "number"
            and re.search(r"\d+", person.get("salary_expectation", ""))
            else person.get("salary_expectation")
        )
    if "modelu hybrydowym" in label or "hybrid work" in label:
        return person.get("hybrid_availability")
    for key, labels in mapping.items():
        if label in labels:
            return person.get(key)
    return None


def create_attempt(job_id):
    with core.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS applications (
            job_id TEXT PRIMARY KEY, state TEXT NOT NULL, message TEXT, url TEXT, updated REAL)""")
        job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise ValueError("Vacancy not found")
        previous = db.execute(
            "SELECT state FROM applications WHERE job_id=?", (job_id,)
        ).fetchone()
        if (
            job["status"] == "applied"
            or previous
            and previous["state"] not in ("failed", "cancelled")
        ):
            raise ValueError(
                "An application is active, already sent, or needs manual verification. No repeat submission."
            )
        if not job["draft"].strip():
            raise ValueError("Generate or write a letter first")
        db.execute(
            "INSERT OR REPLACE INTO applications VALUES (?,?,?,?,?)",
            (job_id, "starting", "Opening application", job["url"], time.time()),
        )
        return dict(job)


def record(job_id, state, message, url=""):
    with core.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS application_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, state TEXT,
            message TEXT, url TEXT, created REAL)""")
        db.execute(
            "INSERT INTO application_events(job_id,state,message,url,created) VALUES (?,?,?,?,?)",
            (job_id, state, message, url, time.time()),
        )
        db.execute(
            "UPDATE applications SET state=?,message=?,url=?,updated=? WHERE job_id=?",
            (state, message, url, time.time(), job_id),
        )
        if state == "submitted":
            db.execute(
                "UPDATE jobs SET status='applied',error='' WHERE id=?", (job_id,)
            )

    # Wake all readers only after the SQLite transaction has committed.
    with EVENTS_COMMITTED:
        EVENTS_COMMITTED.notify_all()


def application_events():
    with core.connect() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='application_events'"
        ).fetchone()
        return (
            [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM application_events ORDER BY id DESC LIMIT ?",
                    (EVENT_WINDOW,),
                )
            ][::-1]
            if exists
            else []
        )


def application_history():
    with core.connect() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='applications'"
        ).fetchone()
        return (
            [dict(r) for r in db.execute("SELECT * FROM applications")]
            if exists
            else []
        )


FIELDS = """() => [...(document.querySelector('[data-job-studio-scope]')||document).querySelectorAll('input,textarea,select,[contenteditable="true"],[role="combobox"],button[data-job-studio-select]')]
.filter(e => (e.type==='file' || e.getClientRects().length) && !e.disabled && (!['hidden','submit','button','reset'].includes(e.type)||e.hasAttribute('data-job-studio-select')))
.map((e,i)=>{
 e.setAttribute('data-job-studio-field',String(i));
 let label=e.getAttribute('data-job-studio-label')||[...(e.labels||[])].map(l=>l.innerText).join(' ');
 if(!label && e.hasAttribute('data-job-studio-select')) label=e.parentElement.querySelector('label')?.innerText||'';
 if(!label && e.getAttribute('aria-labelledby')) label=e.getAttribute('aria-labelledby').split(' ').map(id=>document.getElementById(id)?.innerText||'').join(' ');
 label=label||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'';
 if(!label && e.isContentEditable) label=e.closest('.form-group,.field,.input')?.querySelector('label')?.innerText||'Cover letter';
 if(!label) label=e.name||e.id||'';
 return {index:i,label:label.trim(),type:e.hasAttribute('data-job-studio-select')?'portal-select':e.type||e.getAttribute('role')||e.tagName.toLowerCase(),
 required:e.required||e.getAttribute('aria-required')==='true'||label.includes('*'),value:e.tagName==='SELECT'&&!e.selectedOptions[0]?.textContent.trim()?'':e.hasAttribute('data-job-studio-select')?(['Select','Wybierz'].includes(e.innerText.trim())?'':e.innerText.trim()):('value' in e ? e.value : e.innerText)||'',checked:!!e.checked,
 groupChecked:e.type==='radio' && [...document.querySelectorAll('input[type=radio]')].some(r=>r.name===e.name && r.checked),
 options:e.hasAttribute('data-job-studio-options')?JSON.parse(e.getAttribute('data-job-studio-options')):e.tagName==='SELECT'?[...e.options].filter(o=>o.value).map(o=>o.textContent.trim()):[],
 invalid:e.getAttribute('aria-invalid')==='true',fileCount:e.files?.length||0};
})"""


def active_form(page):
    """Prefer the visible application dialog over background job/search controls."""
    found = page.evaluate("""() => {
        document.querySelectorAll('[data-job-studio-scope]').forEach(e=>e.removeAttribute('data-job-studio-scope'));
        const visible=e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
        const dialogs=[...document.querySelectorAll('[role="dialog"],[aria-modal="true"],dialog[open]')].filter(visible);
        let root=dialogs.reverse().find(e=>e.querySelector('input,textarea'));
        if(!root) root=[...document.querySelectorAll('form')].filter(visible).find(e=>e.querySelector('input[type="file"]') || (e.querySelector('input[type="email"]') && [...e.querySelectorAll('input')].some(i=>/name|imię|nazwisko/i.test(i.name+' '+i.id+' '+i.placeholder))));
        if(!root && location.hostname==='justjoin.it') {
            const email=[...document.querySelectorAll('input[type="email"]')].find(visible);
            for(let p=email?.parentElement;p && p!==document.body;p=p.parentElement){
                if(p.innerText.includes('You apply for') && p.querySelector('button')){root=p;break;}
            }
        }
        if(root){root.setAttribute('data-job-studio-scope','true');return true;}
        return false;
    }""")
    return page.locator("[data-job-studio-scope]") if found else page


def prepare_embedded_form(page, scope, person, draft, progress):
    """Reveal optional letter and attach the CV in Just Join IT's native dialog."""
    if urlsplit(page.url).hostname != "justjoin.it":
        return
    if (
        draft
        and not scope.locator("textarea:visible,[contenteditable=true]:visible").count()
    ):
        toggle = scope.get_by_text("Attach a message for the employer", exact=True)
        if toggle.count() == 1 and toggle.is_visible():
            progress("Открываю поле сообщения работодателю")
            switch_input = (
                toggle.locator("..").locator("..").locator("input[type=checkbox]")
            )
            try:
                if switch_input.count() == 1:
                    switch_input.check(timeout=2500)
                else:
                    toggle.click(timeout=2500)
            except Exception:
                bot_for(page.url).prepare(page, progress)
                if switch_input.count() == 1:
                    switch_input.check(timeout=2500)
                else:
                    toggle.click(timeout=2500)
            try:
                page.locator(
                    "textarea:visible,[contenteditable=true]:visible"
                ).first.wait_for(state="visible", timeout=2500)
            except Exception:
                # Some portal layouts render the text separately from the actual switch.
                bot_for(page.url).prepare(page, progress)
                switch = scope.get_by_role("switch")
                if switch.count() == 1 and not switch.is_checked():
                    switch.check()
                else:
                    nearby = toggle.locator("..").locator("input[type=checkbox]")
                    if nearby.count() == 1:
                        nearby.check()
                if not page.locator(
                    "textarea:visible,[contenteditable=true]:visible"
                ).count():
                    progress(
                        "Поле письма не открылось; продолжаю с CV, если письмо необязательно"
                    )
            scope = active_form(page)
    # The native modal calls its CV field "Add document", without a Resume label.
    upload = scope.get_by_text("Add document", exact=True)
    if upload.count() == 1 and upload.is_visible():
        if scope.get_by_text(Path(person["cv_path"]).name, exact=False).count():
            return
        progress("Загружаю CV в окно Just Join IT")
        files = scope.locator("input[type=file]")
        if files.count() == 1:
            if not files.input_value():
                files.set_input_files(person["cv_path"])
        else:
            with page.expect_file_chooser(timeout=5000) as chooser:
                upload.click()
            chooser.value.set_files(person["cv_path"])
        progress("CV передано форме Just Join IT")


def is_success(page):
    # Job descriptions containing a polite closing are not a confirmation.
    if re.search(r"/(thankyou|thank-you|careers-thanks)(/|\?|$)", page.url, re.I):
        return True
    return any(
        SUCCESS.fullmatch(line.strip())
        for line in page.locator("body").inner_text().splitlines()
    )


def fill_form(page, person, draft, on_progress=None):
    progress = on_progress or (lambda message: None)
    missing = []
    fields = page.evaluate(FIELDS)
    for field in fields:
        element = page.locator(f'[data-job-studio-field="{field["index"]}"]')
        kind = field["type"]
        if kind == "file":
            if field["fileCount"]:
                continue
            # Additional attachments/portfolios are not silently replaced by a CV.
            label = normal(field["label"])
            if any(w in label for w in ("cv", "resume", "życiorys")):
                progress("Прикрепляю CV: " + field["label"])
                element.set_input_files(person["cv_path"])
                progress("CV прикреплено")
            elif field["required"]:
                missing.append(field["label"] or "Additional attachment")
            continue
        if kind in ("checkbox", "radio"):
            if field["checked"] or field.get("groupChecked"):
                continue
            # Only exact, user-saved choices. Never opt into marketing or new terms by inference.
            answer = answer_for(field, person, draft)
            if answer is True:
                try:
                    try:
                        element.check(timeout=2500)
                    except Exception:
                        labels = element.locator("..").locator("label")
                        if labels.count() != 1:
                            raise
                        labels.click(timeout=2500)
                    if not element.is_checked():
                        missing.append(field["label"])
                except Exception:
                    progress("Нужно подтвердить согласие в браузере: " + field["label"])
                    missing.append(field["label"])
            elif field["required"] or (
                urlsplit(page.url).hostname == "justjoin.it"
                and "creating an account" in normal(field["label"])
            ):
                missing.append(field["label"])
            continue
        confirmed = {normal(k): v for k, v in person.get("answers", {}).items()}
        if field["value"].strip() and (
            normal(field["label"]) not in confirmed
            or str(confirmed[normal(field["label"])]) == field["value"].strip()
        ):
            continue
        answer = answer_for(field, person, draft)
        if normal(field["label"]) == "name" and not any(
            normal(f["label"]) in ("surname", "last name", "lastname", "nazwisko")
            for f in fields
        ):
            answer = (person["first_name"] + " " + person["last_name"]).strip()
        if answer is not None and str(answer).strip():
            try:
                progress("Заполняю: " + field["label"])
                if kind in ("select-one", "select-multiple"):
                    element.select_option(label=str(answer))
                elif kind == "portal-select":
                    element.click()
                    page.get_by_role("option", name=str(answer), exact=True).click()
                elif kind == "combobox":
                    missing.append(field["label"])
                else:
                    element.fill(str(answer))
                progress("Поле обработано: " + field["label"])
            except Exception as exc:
                progress(
                    "Не удалось заполнить: "
                    + field["label"]
                    + " ("
                    + type(exc).__name__
                    + ")"
                )
                missing.append(field["label"])
        elif field["required"]:
            missing.append(field["label"] or "Required unlabelled field")
    # Includes custom validation; does not submit or dispatch synthetic clicks.
    scope = page.locator("[data-job-studio-scope]")
    invalid = (scope if scope.count() else page).locator(
        "input:invalid,select:invalid,textarea:invalid"
    )
    if any(invalid.nth(i).is_visible() for i in range(invalid.count())) and not missing:
        missing.append("Check required fields and formatting in the browser")
    return missing


class ManualCompletion(Exception):
    pass


class ApplicationRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.resume = threading.Event()
        self.cancel = threading.Event()
        self.manual_done = threading.Event()
        self.state = {
            "running": False,
            "waiting": False,
            "job_id": None,
            "message": "",
            "url": "",
            "questions": [],
        }
        self.question_cache = {}
        self.session_answers = {}

    def start(self, job_id):
        if not self.lock.acquire(False):
            raise ValueError("Finish the current application first")
        try:
            person = applicant()
            for key in ("first_name", "last_name", "email", "cv_path"):
                if not person[key]:
                    raise ValueError("Complete applicant setting: " + key)
            if not Path(person["cv_path"]).is_file():
                raise ValueError("CV file not found")
            job = create_attempt(job_id)
            self.cancel.clear()
            self.manual_done.clear()
            self.resume.clear()
            self.question_cache = {}
            self.session_answers = {}
            self.state = dict(
                running=True,
                waiting=False,
                job_id=job_id,
                message="Opening browser",
                url=job["url"],
                questions=[],
            )
            threading.Thread(target=self.run, args=(job,), daemon=True).start()
        except Exception:
            self.lock.release()
            raise

    def update(self, status, message, page=None):
        url = page.url if page else self.state["url"]
        self.state.update(message=message, url=url)
        record(self.state["job_id"], status, message, url)

    def finish_manual(self, job_id):
        if job_id != self.state["job_id"]:
            raise ValueError("Это не текущий отклик")
        if self.state["running"]:
            if not self.state["waiting"]:
                raise ValueError("Дождись остановки бота для ручного завершения")
            self.manual_done.set()
            self.resume.set()
        else:
            self.update(
                "submitted", "Отклик завершён пользователем: отправлено вручную"
            )
            self.state["questions"] = []

    def prepare_questions(self, missing, page):
        from .questions import profile_facts, suggest

        fields = page.evaluate(FIELDS)
        questions = []
        for label in dict.fromkeys(missing):
            field = next((f for f in fields if f["label"] == label), {})
            qid = hashlib.sha256(label.encode()).hexdigest()[:16]
            questions.append(
                dict(
                    id=qid,
                    label=label,
                    kind=field.get("type", "manual"),
                    options=field.get("options", []),
                    suggestion="",
                    evidence="",
                )
            )
        pending = [
            q
            for q in questions
            if q["id"] not in self.question_cache and q["kind"] != "manual"
        ]
        if pending:
            self.update(
                "answering",
                "AI проверяет неизвестные вопросы по подтверждённому профилю",
                page,
            )
            try:
                cfg = core.settings()
                person = applicant()
                facts = profile_facts(cfg, person)
                result = suggest(pending, facts, cfg)
                for q in pending:
                    self.question_cache[q["id"]] = result.get(q["id"], {})
            except Exception as exc:
                self.update(
                    "answering",
                    "AI не смог подготовить ответы ("
                    + type(exc).__name__
                    + "). Вопросы доступны для ручного ответа.",
                    page,
                )
                for q in pending:
                    self.question_cache[q["id"]] = {}
        for q in questions:
            q.update(self.question_cache.get(q["id"], {}))
        self.state["questions"] = questions

    def accept_answers(self, job_id, answers, remember=False):
        if not self.state["waiting"] or job_id != self.state["job_id"]:
            raise ValueError("Эта анкета уже не ожидает ответов")
        confirmed = {}
        for q in self.state["questions"]:
            if q["id"] not in answers or q["kind"] in ("file", "manual", "combobox"):
                continue
            value = answers[q["id"]]
            if q["kind"] in ("checkbox", "radio"):
                if value is True:
                    confirmed[q["label"]] = True
                continue
            if not isinstance(value, str) or not value.strip():
                continue
            if q["options"] and value not in q["options"]:
                raise ValueError("Выбери один из предложенных вариантов")
            confirmed[q["label"]] = value.strip()
        self.session_answers.update(confirmed)
        if remember:
            person = applicant()
            # Consent is per form and never carried into future applications.
            person["answers"].update(
                {k: v for k, v in confirmed.items() if not isinstance(v, bool)}
            )
            save_applicant(person)
        self.resume.set()

    def pause(self, message, page):
        self.resume.clear()
        self.state["waiting"] = True
        try:
            self.state["diagnostics"] = diagnostics(page)
        except Exception:
            self.state["diagnostics"] = {}
        self.update("needs_input", message, page)
        while not self.cancel.is_set():
            # Pump Playwright events so URL changes/manual completion are visible on resume.
            page.wait_for_timeout(100)
            if page.is_closed():
                raise RuntimeError("Application browser was closed while waiting")
            if self.resume.wait(0.25):
                break
        self.state["waiting"] = False
        self.state["questions"] = []
        if self.manual_done.is_set():
            raise ManualCompletion()
        if self.cancel.is_set():
            raise InterruptedError()

    def run(self, job):
        driver = None
        clicked_submit = False
        seen_form = False
        try:
            from job_studio.browser.captcha_status import captcha_pending
            from job_studio.browser.session import BaseParserPW

            class ApplicationBrowser(BaseParserPW):
                def parser(self):
                    raise NotImplementedError("Browser is driven by ApplicationRunner")

            driver = ApplicationBrowser(
                headless=False, profile_name="job_studio_applications"
            )
            driver.stop_event = self.cancel
            driver.on_step = lambda message: self.update("starting", message)
            driver._setup_driver()
            page = driver.page
            page.set_default_timeout(5000)
            page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
            for step in range(30):
                if self.manual_done.is_set():
                    raise ManualCompletion()
                if self.cancel.is_set():
                    raise InterruptedError()
                if (clicked_submit or seen_form) and is_success(page):
                    self.update("submitted", "Application confirmed by employer", page)
                    try:
                        proof = core.DATA / "application_proofs"
                        proof.mkdir(exist_ok=True)
                        page.screenshot(
                            path=str(proof / (job["id"] + ".png")), full_page=True
                        )
                    except Exception:
                        self.state["message"] += " (screenshot unavailable)"
                    return
                if clicked_submit:
                    self.pause(
                        "Submission not confirmed. Check the browser/email. No automatic resubmission.",
                        page,
                    )
                    continue
                try:
                    core.validate_url(page.url)
                except ValueError:
                    self.pause(
                        "Unsupported destination. Complete this application manually; no data filled here.",
                        page,
                    )
                    continue
                if captcha_pending(page) and not driver._handle_captcha(max_rounds=2):
                    self.pause(
                        "Complete CAPTCHA in the browser, then press Continue.", page
                    )
                    continue
                if page.locator("input[type=password]:visible").count():
                    self.pause("Sign in in the browser, then press Continue.", page)
                    continue
                bot = bot_for(page.url)
                bot.prepare(page, lambda message: self.update("opening", message, page))
                fields = page.locator(
                    "input[type=email]:visible,input[type=file],textarea:visible,[contenteditable=true]:visible"
                )
                # Listing -> application form, including external ATS links and popup windows.
                if not bot.ready(page):
                    # SPAs can render the application controls after DOMContentLoaded.
                    try:
                        page.wait_for_load_state("networkidle", timeout=6000)
                    except Exception:
                        pass
                    if not bot.ready(page):
                        if not bot.open(
                            page, lambda message: self.update("opening", message, page)
                        ):
                            self.pause(
                                "Не найдена форма отклика. Диагностика элементов доступна через MCP.",
                                page,
                            )
                            continue
                        pages = page.context.pages
                        if pages[-1] != page:
                            page = pages[-1]
                        continue
                self.update(
                    "filling", "Filling confirmed profile data and attaching CV", page
                )
                seen_form = True
                person = applicant()
                person["answers"] = {**person["answers"], **self.session_answers}
                bot.prepare_form(
                    page, person, lambda message: self.update("filling", message, page)
                )
                scope = active_form(page)
                prepare_embedded_form(
                    page,
                    scope,
                    person,
                    job["draft"],
                    lambda message: self.update("filling", message, page),
                )
                scope = active_form(page)
                missing = fill_form(
                    page,
                    person,
                    job["draft"],
                    on_progress=lambda message: self.update("filling", message, page),
                )
                if missing:
                    self.prepare_questions(missing, page)
                    self.pause(
                        "Нужно заполнить или подтвердить в браузере: "
                        + "; ".join(dict.fromkeys(missing))
                        + ". Затем нажми «Продолжить» в Job Studio.",
                        page,
                    )
                    continue
                next_buttons = scope.get_by_role("button", name=NEXT)
                next_visible = [
                    next_buttons.nth(i)
                    for i in range(next_buttons.count())
                    if next_buttons.nth(i).is_visible()
                ]
                if len(next_visible) == 1:
                    next_visible[0].click()
                    page.wait_for_timeout(1000)
                    continue
                if (urlsplit(page.url).hostname or "").endswith("upwork.com"):
                    self.pause(
                        "Форма Upwork подготовлена. Проверь ставку, условия и расход Connects, затем отправь вручную и нажми «Закончить отклик — отправил сам».",
                        page,
                    )
                    continue
                submit = scope.get_by_role("button", name=FINAL)
                visible = [
                    submit.nth(i)
                    for i in range(submit.count())
                    if submit.nth(i).is_visible() and submit.nth(i).is_enabled()
                ]
                if len(visible) != 1 or not fields.count():
                    self.pause(
                        "Cannot identify one enabled submit button. Check the form and continue.",
                        page,
                    )
                    continue
                if is_success(page):
                    self.pause(
                        "This page already looks like a confirmation; verify the application manually.",
                        page,
                    )
                    continue
                # Persist uncertainty BEFORE click: a crash cannot lead to duplicate automatic submissions.
                clicked_submit = True
                self.update(
                    "submitting", "Submitting application; awaiting confirmation", page
                )
                visible[0].click()
                for _ in range(20):
                    if is_success(page) or self.cancel.is_set():
                        break
                    page.wait_for_timeout(500)
            self.update(
                "uncertain" if clicked_submit else "failed",
                "Step limit reached; check the browser manually",
                page,
            )
        except ManualCompletion:
            self.update(
                "submitted", "Отклик завершён пользователем: отправлено вручную"
            )
        except InterruptedError:
            self.update(
                "uncertain" if clicked_submit or seen_form else "cancelled",
                "Stopped; verify any manually submitted application",
            )
        except Exception as exc:
            self.update(
                "uncertain" if clicked_submit or seen_form else "failed",
                "Browser workflow stopped: " + type(exc).__name__,
            )
            try:
                self.state["diagnostics"] = diagnostics(page)
            except Exception:
                pass
        finally:
            try:
                if driver:
                    driver.close_driver()
            finally:
                self.state.update(running=False, waiting=False)
                self.lock.release()
