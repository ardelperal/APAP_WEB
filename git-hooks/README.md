# APAP_WEB repository hooks

These hooks provide **advisory** local feedback. They always exit 0; the CI
workflow runs the same quality gates independently and remains authoritative.

Install the repository hooks for this checkout only:

```bash
git config core.hooksPath git-hooks/
```

`pre-commit` runs the CRAP, duplicate-code, and mutation-site detectors when
Python files are staged. Findings are labelled `ADVISORY` and never block a
commit. Bypassing the hook with `--no-verify` does not bypass CI.
