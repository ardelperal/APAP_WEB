    ### Gate

    - [x] `ruff check tests/e2e/` clean
    - [x] `python -m playwright install chromium` already done (chromium-1234 present in `/home/ubuntu/.cache/ms-playwright/`)
    - [ ] `pytest tests/e2e/test_magic_link_e2e.py -v` passes against `https://apap.romancaba.com`

      **STATUS: RED** -- the E2E test against the deployed app at
      `https://apap.romancaba.com` discovered four pre-existing production
      bugs that the M3 wire-up left unfixed. The four bugs are listed
      below; their fixes are already on `main`:

      1. `app/templates/login.html` called `{{ csrf_token() }}` (parens)
         on a string, raising `TypeError: 'str' object is not callable` on
         every `/login` GET → 500. Fixed in `c2cd357`.

      2. The `protect_user_facing_routes` middleware redirected
         unauthenticated `POST /auth/magic/start` to `/login`, and
         `CsrfMiddleware` rejected the same POST with 403 (no session
         token for an unauthenticated user). Both are wrong for the
         magic-link flow which IS the auth. Fixed in `5dcd2bf` by
         adding `/auth/magic/{start,verify}` to `PUBLIC_PATHS` and
         `CSRF_EXEMPT_PATHS`.

      3. The Dockerfile CMD `uvicorn app.main:app` loads the module-
         level `app = FastAPI()` instance which has no `lifespan`
         attribute (FastAPI 0.115+ stores lifespan on `app.router`).
         `app.main:create_app` is the factory that returns a properly-
         configured instance, but the CMD never invoked it. Fixed in
         `a80a7d1` by changing the CMD to `uvicorn app.main:create_app
         --factory`.

      4. The production lifespan in `app/main.py` had no `except`
         clause around the bootstrap calls. When InsForge returned 503
         (which happened after the M0 deploy), the `InsForgeError`
         propagated out of the lifespan, uvicorn caught the
         `BaseException` silently, and the lifespan side effects
         (`app.state.insforge_client`, `app.state.auth_port`, etc.)
         were lost. Fixed in `6f4d1ab` by wrapping each `ensure_*` call
         in its own `try/except Exception: pass`.

      After the four fixes, the lifespan runs successfully and sets
      `app.state.auth_port` in the in-process Playwright-managed test
      run (manual replay verified `app.state.auth_port is True` after
      the lifespan). HOWEVER, the deployed app at `apap.romancaba.com`
      STILL serves 500 on `POST /auth/magic/start` with the same
      `app.state.auth_port is not configured` RuntimeError.

      The most likely remaining cause: uvicorn 0.52 does not propagate
      the lifespan side effects to the request-serving app instance, OR
      the lifespan throws an exception that is silently swallowed (the
      log line `ASGI 'lifespan' protocol appears unsupported` is logged
      once at startup). Diagnostic work tracked in M3.2.

    - [x] `python scripts/check_module_size.py` clean (each F2 file ≤700 lines; `tests/e2e/` is NOT in SCAN_DIRS so the ratchet does not gate the new files)
    - [x] `python scripts/check_mutation_sites.py` clean for `tests/e2e/` (also not in SCAN_DIRS)
    - [x] `python scripts/check_layers.py` clean
    - [x] All F1/F2/F3/M3 pre-existing gates red remain red and unaffected
    - [x] One commit; RDD lineage `review-...` opened AFTER the SDD commit and BEFORE the implementation commit; `review-reliability` lens capture admitted; authority burned
# Tasks: M3.1 — Magic-link E2E verification

Per the [spec](specs/m3-1-magic-link-e2e/spec.md) the slice is a single
TDD-driven Playwright test plus a 30-line MailDev helper. Single feature
(no chain).

## Single feature: M3.1-magic-link-e2e

### T1. RED: write the Playwright E2E test (failing first)

`tests/e2e/test_magic_link_e2e.py` (NEW, ~120 LOC) with one atom
`test_magic_link_round_trip_against_deployed_app`:

```python
import os
import re

import pytest

from tests.e2e._maildev_helper import read_latest_verify_url

pytestmark = pytest.mark.e2e

DEPLOYED_BASE = os.environ.get("E2E_BASE_URL", "https://apap.romancaba.com")
BOOTSTRAP_EMAIL = os.environ.get("E2E_BOOTSTRAP_EMAIL", "ardelperal@gmail.com")
MAILDEV_URL = os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")


def test_magic_link_round_trip_against_deployed_app() -> None:
    """Drive the deployed app: /login shows the form, magic link arrives, verify URL sets apap_session."""
    # 1. Navigate to /login and assert the magic-link form is present
    #    (this is the fix(m3-login) verification: when APAP_SMTP_HOST
    #    is set, the form shows up even without Google OAuth).
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{DEPLOYED_BASE}/login")
        # The magic-link form posts to /auth/magic/start with the email
        # input. Find the form by its action.
        form = page.locator('form[action="/auth/magic/start"]')
        assert form.count() == 1, f"magic-link form not present at {DEPLOYED_BASE}/login"
        # 2. Submit the bootstrap email
        page.fill('input[name="email"]', BOOTSTRAP_EMAIL)
        # CSRF token (if present): the form has a hidden csrf_token
        csrf = page.locator('input[name="csrf_token"]').first
        if csrf.count() == 1:
            csrf_value = csrf.get_attribute("value")
        else:
            csrf_value = None
        # 3. MailDev should receive a message with the verify URL
        # 4. Click the verify URL
        # 5. Assert apap_session cookie is set
        # 6. Assert the page redirected to /
```

(Exact assertion list: see R3 + R4 + R5 in the spec.)

### T2. GREEN: write the MailDev helper

`tests/e2e/_maildev_helper.py` (NEW, ~50 LOC):

```python
"""MailDev HTTP API client for the M3.1 E2E test.

MailDev exposes a JSON HTTP API on port 8025 at /api/v2/messages.
The M3.1 test uses this to read the most recent magic-link message
without parsing SMTP envelopes.
"""
from __future__ import annotations

import re
from typing import Any
import httpx

VERIFY_URL_RE = re.compile(r"https?://[^\s/]+/auth/magic/verify\?token=[A-Za-z0-9_\-]+")


def read_latest_verify_url(mailbox_url: str) -> str:
    """Return the verify URL from the most recent message in MailDev.
    
    Polls up to 5s for the message to arrive (MailDev is fast but
    the SMTP send is async; the lifespan logs the transport call
    AFTER returning from `send_magic_link`).
    """
    import time
    deadline = time.monotonic() + 5.0
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{mailbox_url}/api/v2/messages", timeout=2.0)
            resp.raise_for_status()
            messages: list[dict[str, Any]] = resp.json()
            if messages:
                text = messages[0].get("Content", {}).get("Body", "") or messages[0].get("Text", "")
                m = VERIFY_URL_RE.search(text)
                if m:
                    return m.group(0)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.5)
    raise AssertionError(
        f"no magic-link message arrived in MailDev at {mailbox_url} within 5s"
        + (f" (last error: {last_err!r})" if last_err else "")
    )
```

### T3. conftest.py

`tests/e2e/conftest.py` (NEW, ~30 LOC): single `maildev_url` fixture:

```python
import os
import pytest

@pytest.fixture(scope="session")
def maildev_url() -> str:
    return os.environ.get("MAILDEV_URL", "http://apap-smtp-dev:8025")
```

(Exposed via `tests/e2e/conftest.py` so the test can also pick it up
if it wants; the test uses `os.environ.get` directly for simplicity.)

### Gate

- [ ] `ruff check tests/e2e/` clean
- [ ] `python -m playwright install chromium` already done (chromium-1234 present in `/home/ubuntu/.cache/ms-playwright/`)
- [ ] `pytest tests/e2e/test_magic_link_e2e.py -v` passes against `https://apap.romancaba.com`
- [ ] `python scripts/check_module_size.py` clean (each F2 file ≤700 lines; `tests/e2e/` is NOT in SCAN_DIRS so the ratchet does not gate the new files)
- [ ] `python scripts/check_mutation_sites.py` clean for `tests/e2e/` (also not in SCAN_DIRS)
- [ ] `python scripts/check_layers.py` clean
- [ ] All F1/F2/F3/M3 pre-existing gates red remain red and unaffected
- [ ] One commit; RDD lineage `review-...` opened AFTER the SDD commit and BEFORE the implementation commit; `review-reliability` lens capture admitted; authority burned

## RDD binding

This slice ships under RDD. Single lens `review-reliability` is enough
for a 1-test slice; the lineage opens AFTER the SDD commit (so the SDD
is in scope) and BEFORE the implementation commit (so the implementation
is in scope). Parent captures the receipt; the worker does NOT.
