"""Exercise the React UI against an isolated Job Studio server with local test data."""
import os
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright


def test_browser():
    with tempfile.TemporaryDirectory() as data:
        os.environ["JOB_STUDIO_DATA"] = data
        from job_studio import core

        core.put(dict(title="Python Engineer", company="Example", location="Remote",
                      url="https://justjoin.it/job-offer/example", source="Fixture",
                      description="Test role"))
        process = subprocess.Popen([sys.executable, "-m", "job_studio.server", "--no-browser"],
                                   stdout=subprocess.PIPE, text=True)
        try:
            url = process.stdout.readline().strip()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=os.getenv("STUDIO_TEST_BROWSER"))
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(url, wait_until="domcontentloaded")
                page.get_by_role("button", name="Настройки", exact=True).click()
                profile = page.get_by_label("Подтверждённый опыт для генерации писем")
                profile.fill("Test profile")
                page.get_by_role("button", name="Сохранить настройки").click()
                expect(page.get_by_text("Настройки сохранены", exact=True)).to_be_visible()
                page.get_by_role("button", name="Parse plus").click()
                page.get_by_label("Ссылка на вакансию").fill("https://justjoin.it/job-offer/example")
                expect(page.get_by_role("button", name="Разобрать и подготовить письмо")).to_be_enabled()
                page.get_by_role("button", name="Вакансии", exact=True).click()
                page.get_by_role("button", name="Python Engineer", exact=False).click()
                letter = page.get_by_label("Черновик письма")
                letter.fill("First draft")
                with page.expect_response(lambda response: response.url.endswith("/api/state")):
                    page.get_by_role("button", name="Активность", exact=True).click()
                page.get_by_role("button", name="Вакансии", exact=True).click()
                expect(letter).to_have_value("First draft")
                page.get_by_role("button", name="Сохранить", exact=True).click()
                expect(page.get_by_text("Сохранено", exact=True)).to_be_visible()
                page.reload(wait_until="domcontentloaded")
                page.get_by_role("button", name="Python Engineer", exact=False).click()
                expect(letter).to_have_value("First draft")
                page.get_by_role("button", name="Настройки", exact=True).click()
                expect(profile).to_have_value("Test profile")
                assert not errors, errors
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    test_browser()

