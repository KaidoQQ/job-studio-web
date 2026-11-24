"""Portal-specific navigation. Only semantic, visible controls are clicked."""

import re
from urllib.parse import urlsplit

FORM = """() => [...document.querySelectorAll('form,[role="dialog"],[aria-modal="true"],dialog[open]')].some(e => e.getClientRects().length && (e.querySelector('input[type="file"]') || (e.querySelector('input[type="email"]') && [...e.querySelectorAll('input')].some(i=>/name|imię|nazwisko/i.test(i.name+' '+i.id+' '+i.placeholder)))))"""


class PortalBot:
    name = "Generic ATS"
    open_pattern = re.compile(
        r"^(apply|apply now|apply for this job|apply for this position|aplikuj|aplikuj teraz)$",
        re.I,
    )

    def ready(self, page):
        return bool(page.evaluate(FORM))

    def prepare(self, page, progress):
        banner = page.locator("#cookiescript_injected_wrapper")
        decline = banner.get_by_text("DECLINE ALL", exact=True)
        if decline.count() == 1 and decline.is_visible():
            decline.click()
        # Consent to optional tracking is not needed for recruitment.
        for label in (
            "Reject all",
            "Reject All",
            "Decline Optional Cookies",
            "Reject optional cookies",
            "Odrzuć wszystkie",
            "Tylko niezbędne",
        ):
            button = page.get_by_role("button", name=label, exact=True)
            if button.count() == 1 and button.is_visible():
                button.click()
                break

    def prepare_form(self, page, person, progress):
        pass

    def open(self, page, progress):
        controls = page.get_by_role("button", name=self.open_pattern).or_(
            page.get_by_role("link", name=self.open_pattern)
        )
        for index in range(controls.count()):
            item = controls.nth(index)
            if item.is_visible() and item.is_enabled():
                progress(self.name + ": открываю анкету")
                item.click()
                page.wait_for_timeout(1500)
                return True
        return False


class JustJoinBot(PortalBot):
    name = "Just Join IT"


class NoFluffBot(PortalBot):
    name = "No Fluff Jobs"
    open_pattern = re.compile(
        r"^(apply|apply now|apply with cv|apply for this job|aplikuj|aplikuj teraz|aplikuj z cv)$",
        re.I,
    )


class TraffitBot(PortalBot):
    name = "Traffit"

    def ready(self, page):
        return bool(
            page.locator("input[type=email]:visible").count()
            and page.locator("input[type=file]").count()
        )


class AshbyBot(PortalBot):
    name = "Ashby"

    def ready(self, page):
        return super().ready(page) or bool(
            "/application" in page.url
            and page.locator("input[type=email]:visible").count()
        )

    open_pattern = re.compile(
        r"^(apply|apply now|apply for this job|application)$", re.I
    )

    def open(self, page, progress):
        tab = page.get_by_role("tab", name="Application", exact=True)
        if (
            tab.count() == 1
            and tab.is_visible()
            and tab.get_attribute("aria-selected") != "true"
        ):
            progress("Ashby: открываю вкладку Application")
            tab.click()
            page.wait_for_timeout(1000)
            return True
        return super().open(page, progress)


class WorkableBot(PortalBot):
    name = "Workable"
    open_pattern = re.compile(
        r"^(apply|apply now|apply for this job|apply for this position|apply to this job)$",
        re.I,
    )


class PeopleForceBot(PortalBot):
    name = "PeopleForce"
    open_pattern = re.compile(
        r"^(apply|apply now|apply for position|apply for this position|aplikuj|aplikuj teraz)$",
        re.I,
    )


class RecruitifyBot(PortalBot):
    name = "Recruitify"

    def prepare_form(self, page, person, progress):
        page.locator(".form-group").evaluate_all(
            "groups=>groups.forEach(g=>{const label=g.querySelector(':scope > label');if(label){g.querySelectorAll('input,textarea,select').forEach(e=>e.setAttribute('data-job-studio-label',label.innerText))}})"
        )


class ERecruiterBot(PortalBot):
    name = "eRecruiter"

    def prepare_form(self, page, person, progress):
        files = page.locator("input[type=file]")
        if files.count() == 1:
            files.evaluate("e=>e.setAttribute('data-job-studio-label','CV')")
        buttons = page.locator('button[data-test-id^="Select-"]')
        for i in range(buttons.count()):
            button = buttons.nth(i)
            if not button.is_visible():
                continue
            button.evaluate("e=>e.setAttribute('data-job-studio-select','true')")
            if button.inner_text().strip() not in ("Select", "Wybierz"):
                continue
            button.click()
            options = page.locator("[role=option]:visible")
            options.first.wait_for(state="visible", timeout=5000)
            labels = options.all_inner_texts()
            button.evaluate(
                "(e,options)=>e.setAttribute('data-job-studio-options',JSON.stringify(options.filter(x=>!['Select','Wybierz'].includes(x))))",
                labels,
            )
            page.keyboard.press("Escape")


def bot_for(url):
    host = (urlsplit(url).hostname or "").lower()
    for domain, cls in [
        ("recruitify.ai", RecruitifyBot),
        ("erecruiter.pl", ERecruiterBot),
        ("justjoin.it", JustJoinBot),
        ("nofluffjobs.com", NoFluffBot),
        ("traffit.com", TraffitBot),
        ("ashbyhq.com", AshbyBot),
        ("workable.com", WorkableBot),
        ("peopleforce.io", PeopleForceBot),
    ]:
        if host == domain or host.endswith("." + domain):
            return cls()
    return PortalBot()


def diagnostics(page):
    """Visible controls only; excludes values, scripts, cookies and hidden tokens."""
    return page.evaluate(
        """() => ({title:document.title,controls:[...document.querySelectorAll('button,a,input,textarea,select,[role="tab"],[role="checkbox"]')].filter(e=>e.getClientRects().length).map(e=>({tag:e.tagName,role:e.getAttribute('role'),type:e.type,label:(e.innerText||e.getAttribute('aria-label')||[...(e.labels||[])].map(l=>l.innerText).join(' ')||e.getAttribute('placeholder')||e.name||'').slice(0,350),disabled:!!e.disabled})).filter(e=>e.label||['INPUT','TEXTAREA','SELECT'].includes(e.tag)).slice(-60)})"""
    )
