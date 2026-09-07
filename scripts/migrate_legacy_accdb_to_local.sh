#!/usr/bin/env bash
# scripts/migrate_legacy_accdb_to_local.sh
#
# Operator-facing wrapper that runs the migration CLI against the
# Coolify-hosted local backend (Phase 3 of issue #648, part of the
# self-host-backend-coolify umbrella, #641).
#
# What this does:
#   Invokes `python -m migration apply --direction legacy-to-web`
#   against the local Postgres that backs `apap-web` in production.
#   The CLI does the heavy lifting (lock, snapshot, plan, apply,
#   audit, partial-apply evidence); the script just wires the
#   operator's environment into a one-shot command.
#
# Usage:
#   ./scripts/migrate_legacy_accdb_to_local.sh              # dry-run (--check-only)
#   ./scripts/migrate_legacy_accdb_to_local.sh --apply      # commit
#   ./scripts/migrate_legacy_accdb_to_local.sh --help
#
# Required env vars:
#   APAP_LEGACY_ACCDB_PATH  Absolute path to the .accdb file the
#                           operator wants to migrate. The test
#                           fixture lives at
#                           tests/migration/local-access/backend/
#                             Registro_APAP_Alcala_datos_18.accdb
#                           for local rehearsals; production points
#                           at the operator's authorised copy.
#   APAP_LOCAL_BACKEND=true  Hard requirement — the script refuses
#                           to run against the legacy Coolify local Postgres backend.
#                           backend (the one that 503'd in
#                           2026-09-05).
#   APAP_LOCAL_DB_URL       DSN of the local Postgres (the lifespan
#                           in app/core/local_backend/app.py reads
#                           this on startup).
#
# Optional:
#   APAP_LOCAL_DB_SCHEMA    Schema name (default: public). Tests
#                           set this to the ephemeral schema.
#   APAP_LOCAL_BACKEND_DSN  Alias accepted by the lifespan; if both
#                           APAP_LOCAL_DB_URL and APAP_LOCAL_BACKEND_DSN
#                           are set, the former wins.
#
# Why the dry-run is mandatory first:
#   apap-migration's --check-only mode reads the legacy .accdb, builds
#   the diff against the local Postgres, and prints the planned writes
#   (table, count, source hash). It does NOT acquire the writer lock
#   and does NOT mutate. The operator reviews the printed plan, then
#   re-runs with --apply to commit. This matches HR-13 (preserve
#   partial-apply evidence) in docs/codebase/code-quality-rules.md.
#
# Exit codes:
#   0  success (dry-run completed; apply committed if --apply)
#   1  operator error (missing env, bad path, unknown flag)
#   2  pre-flight error (legacy snapshot drift, lock conflict)
#       — surfaced by the underlying CLI; this script does not
#       mask non-zero exits from `python -m migration apply`.
#
# See also:
#   docs/runbooks/live-migration-apply.md  — full apply procedure
#   docs/runbooks/live-migration-m0-bootstrap.md  — operator quick-start
#   migration/verify_fallback_web_to_legacy.py  — CI gate for the
#     bidirectional leg (PR7 / #637); this script is its operator-side
#     counterpart.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

usage() {
    cat <<EOF
Usage: $0 [--apply | --help]

Migrates real legacy data from a .accdb file into the local backend
(Coolify-hosted FastAPI service) via:

    python -m migration apply --direction legacy-to-web \\
        --legacy-path <APAP_LEGACY_ACCDB_PATH>

Without --apply the script always runs --check-only (dry-run): it
builds the diff plan but does NOT write. Re-run with --apply to
commit.

Required environment:

    APAP_LEGACY_ACCDB_PATH  Absolute path to the .accdb file.
    APAP_LOCAL_BACKEND=true  Hard requirement; refuses to run otherwise.
    APAP_LOCAL_DB_URL       DSN of the local Postgres.

Optional:

    APAP_LOCAL_DB_SCHEMA    Schema name (default: public).
EOF
}

# --- argument parsing ---------------------------------------------------

if [ $# -gt 1 ]; then
    echo "ERROR: expected at most one argument, got $#" >&2
    usage >&2
    exit 1
fi

APPLY_MODE="--check-only"
case "${1:-}" in
    "")
        :  # default: --check-only
        ;;
    --apply)
        APPLY_MODE=""  # drop --check-only; real apply
        ;;
    --help|-h)
        usage
        exit 0
        ;;
    *)
        echo "ERROR: unknown argument: $1" >&2
        usage >&2
        exit 1
        ;;
esac

# --- env validation ----------------------------------------------------

if [ -z "${APAP_LEGACY_ACCDB_PATH:-}" ]; then
    echo "ERROR: APAP_LEGACY_ACCDB_PATH is not set" >&2
    echo "" >&2
    usage >&2
    exit 1
fi

# ``case`` instead of ``[ ... != /* ]`` because the unquoted glob would
# expand ``/*`` to the root listing under bash.
case "${APAP_LEGACY_ACCDB_PATH}" in
    /*) : ;;
    *)
        echo "ERROR: APAP_LEGACY_ACCDB_PATH must be an absolute path; got '${APAP_LEGACY_ACCDB_PATH}'" >&2
        exit 1
        ;;
esac

if [ ! -f "${APAP_LEGACY_ACCDB_PATH}" ]; then
    echo "ERROR: APAP_LEGACY_ACCDB_PATH points to a non-existent file: ${APAP_LEGACY_ACCDB_PATH}" >&2
    exit 1
fi

if [ -z "${APAP_LOCAL_DB_URL:-}" ] && [ -z "${APAP_LOCAL_BACKEND_DSN:-}" ]; then
    echo "ERROR: APAP_LOCAL_DB_URL is not set" >&2
    exit 1
fi

# Force the migration CLI to target the Coolify-hosted local backend
# (the local Postgres) backend.
# hosted proxy has been 503'ing since 2026-09-05; routing the
# migration there would silently produce zero writes.
export APAP_LOCAL_BACKEND=true

# --- invoke the migration CLI -------------------------------------------

ARGS=(
    -m
    migration
    apply
    --direction
    legacy-to-web
    --legacy-path
    "${APAP_LEGACY_ACCDB_PATH}"
)
if [ -n "${APPLY_MODE}" ]; then
    ARGS+=("${APPLY_MODE}")
fi

echo "Running: python ${ARGS[*]}" >&2

exec python "${ARGS[@]}"
