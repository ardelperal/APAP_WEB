# Proposal: M3.1 — Magic-link E2E verification (TDD + RDD)

The previous M3 production deploy succeeded (commit `9b057b7` on `main`), the app at
`https://apap.romancaba.com/healthz` returns 200 OK, and the magic-link lifespan
is wired. What is still missing is a TDD-driven end-to-end Playwright test that
exercises the full magic-link round-trip against the deployed app.

The slice adds one Playwright test plus a 50-line MailDev helper, and binds the
work to a single burned RDD lineage.

Forecast ≤200 LOC. Single feature (no chain).
