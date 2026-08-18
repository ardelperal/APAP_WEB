# Lint Policy Decision: TRY003 and PLR2004 (Issue #389)

Date: 2026-08-01  
Status: Accepted / Policy Decision  
Scope: `TRY003` (raise-vanilla-args) and `PLR2004` (magic-value-comparison)

---

## Executive Summary

As part of the 2026-08-01 static-analysis sweep, `TRY003` (175 occurrences) and `PLR2004` (39 occurrences) were evaluated for remediation strategy vs policy exclusion.

**Decision**: Keep both `TRY003` and `PLR2004` under the **extended-ruff shrink-only ratchet** (`scripts/check_ruff_ratchet.py`). Do not perform bulk refactoring to eliminate pre-existing instances, and do not remove the rules from the ratchet `SELECT` list.

---

## Rule Analysis & Policy Rationale

### 1. `TRY003` — `raise-vanilla-args` (175 findings)

- **What it flags**: Raising standard exception classes with long message strings (e.g. `raise ValueError("Invalid parameter 'x' provided for item")`).
- **Evaluation**: In FastAPI routes and service layers, exception messages translate directly into API error responses or form validation user feedback. Forcing custom exception subclasses for every unique error message creates hundreds of single-use classes, increasing boilerplate and memory overhead without architectural benefit.
- **Policy Decision**:
  - Pre-existing 175 findings remain grandfathered in `check_ruff_ratchet.py` `BASELINE["TRY003"] = 175`.
  - New code must not introduce new `TRY003` violations (the ratchet will block CI if count > 175).
  - High-traffic domain errors should use typed domain exceptions where recovery logic exists; simple validation errors may use standard exceptions as long as the ratchet count does not increase.

### 2. `PLR2004` — `magic-value-comparison` (39 findings)

- **What it flags**: Comparing variables against numeric literals without defining named constants (e.g. `if status == 200:` or `if len(items) > 5:`).
- **Evaluation**: The 39 pre-existing occurrences in `app/` and `migration/` represent well-understood HTTP status codes (200, 404, 302), standard array indexing (0, 1), or fixed protocol constants. Defining single-use constants for every HTTP status code or index in internal helpers adds noise.
- **Policy Decision**:
  - Pre-existing 39 findings remain grandfathered in `check_ruff_ratchet.py` `BASELINE["PLR2004"] = 39`.
  - New code should use named constants for domain-specific thresholds (e.g., page limits, timeouts).
  - The ratchet enforces that `PLR2004` count cannot exceed 39.

---

## Verification & Guard

- Both rules are checked by `scripts/check_ruff_ratchet.py`.
- Running `python scripts/check_ruff_ratchet.py` verifies `TRY003 <= 175` and `PLR2004 <= 39`.
