"""Observe challenge state; a solver returning is not proof of success."""


def captcha_pending(page):
    for frame in page.frames:
        url = frame.url.lower()
        if "recaptcha" in url:
            anchor = frame.locator("#recaptcha-anchor")
            if anchor.count() and anchor.is_visible():
                if anchor.get_attribute("aria-checked") != "true":
                    return True
        if "hcaptcha" in url:
            check = frame.locator('[role="checkbox"]')
            if check.count() and check.first.is_visible():
                if check.first.get_attribute("aria-checked") != "true":
                    return True
    return bool(
        page.evaluate("""() => {
        const visible = e => !!(e.getClientRects().length);
        const tokens = [...document.querySelectorAll('[name="cf-turnstile-response"], [name="g-recaptcha-response"], [name="h-captcha-response"]')];
        if (tokens.some(e => e.value)) return false;
        return [...document.querySelectorAll('iframe[src*="challenges.cloudflare.com"], .cf-turnstile, #challenge-stage')].some(visible);
    }""")
    )
