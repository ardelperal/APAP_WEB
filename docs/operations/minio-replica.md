# MinIO replica for CI — `ghcr.io/ardelperal/minio`

> Last updated: 2026-09-27 — issue #973 (digest pin landed).

## Recorded digest

The first successful replica build
([36249625652](https://github.com/ardelperal/APAP_WEB/actions/runs/36249625652))
published the image pinned by digest in the e2e job:

- Image: `ghcr.io/ardelperal/minio@sha256:6140fe7015bd97e4e6340c9a8ead775c09bc1a226b7c36e41d24852f839dae8f`
  (both tags `RELEASE.2025-10-15T17-29-55Z` and `ci` point to this digest).
- The digest is pinned in two places, which must move together:
  `.github/workflows/ci.yml` (e2e `minio` service `image:` line) and
  `MINIO_REPLICA_DIGEST` in `tests/test_ci_workflow.py`.

## Why this exists

The e2e job in `.github/workflows/ci.yml` needs a MinIO service container.
It can no longer pull one from upstream:

- MinIO Community Edition went source-only in late 2025. The binary images
  were removed from Docker Hub and quay.io, and the public mirrors
  (mirror.gcr.io, public.ecr.aws, third-party mirrors) return 404.
- Upstream confirmed the move in
  [minio/minio#21662](https://github.com/minio/minio/issues/21662).
- `docker pull minio/minio:latest` fails with `pull access denied` no matter
  how it is authenticated. That made the earlier workaround — the Docker Hub
  `credentials:` block from PR #981 — unfixable by design, and this guide
  replaces `docs/operations/docker-hub-anonymous-pull.md`.
- Building from the upstream repository directly is also a dead end, for two
  independent reasons (observed in the first live replica run,
  [36247204251](https://github.com/ardelperal/APAP_WEB/actions/runs/36247204251)):

  1. The upstream `Dockerfile` at the pinned tag is a thin wrapper —
     `FROM minio/minio:latest` — over the exact image that no longer exists,
     so `docker build` of the checked-out source fails at its first
     instruction.
  2. The binary-download path of upstream's `Dockerfile.release` is dead too:
     the MinIO community download host returns HTTP 410 for community
     release archives.

  The only viable build is from source.

## The replica strategy

`.github/workflows/minio-replica.yml` builds the image from pinned MinIO
source and publishes it to this repository's GHCR namespace:

1. It checks out `https://github.com/minio/minio` at a pinned release tag
   and builds it from source with an inline multi-stage Dockerfile that the
   workflow writes into the runner workspace. Stage 1 (`golang:1.24-alpine`)
   compiles the binary with the same flags as the upstream Makefile
   (`CGO_ENABLED=0 go build -tags kqueue -trimpath` plus the generated
   ldflags). Stage 2 (`ubuntu:24.04`) installs `curl` and `ca-certificates`
   (the e2e healthcheck in ci.yml probes the service with `curl`), copies
   the compiled binary and the upstream `dockerscripts/docker-entrypoint.sh`,
   exposes 9000/9001 and declares the `/data` volume.
2. The pinned release is `RELEASE.2025-10-15T17-29-55Z`, verified on
   2026-09-26 with `git ls-remote --tags https://github.com/minio/minio`
   as the highest existing `RELEASE.2025-*` tag.
3. It pushes two tags: `ghcr.io/ardelperal/minio:<RELEASE_TAG>` (immutable
   pin) and `ghcr.io/ardelperal/minio:ci` (moving convenience tag). The
   e2e job does not pull the moving tag: it pulls the image by digest.
4. Login uses the ephemeral `GITHUB_TOKEN` of the run — no personal access
   token, no repository secret.

The GHCR package is private, so the e2e service container authenticates its
pull with `github.actor` / `github.token`, and the e2e job grants
`packages: read` (permissions are scoped per job since issue #879).

## Rebuild or refresh the replica

1. Bump the `RELEASE_TAG` env value in `.github/workflows/minio-replica.yml`
   to the new upstream release tag.
2. Dispatch the workflow: `gh workflow run minio-replica.yml`.
3. Read the image digest from the run's job summary (it is also exposed as
   the `digest` step output of the push step).

## How the digest pin gets updated

The e2e job pulls `ghcr.io/ardelperal/minio@sha256:6140fe...dae8f`,
recorded from build run 36249625652 (issue #973). To refresh it:

1. Dispatch `minio-replica.yml`; the job summary records the new digest.
2. Replace the pinned digest in `.github/workflows/ci.yml`
   (e2e `minio` service `image:` line) and in `MINIO_REPLICA_DIGEST`
   (`tests/test_ci_workflow.py`) in the same commit, following the
   repository's digest-pinning rule (issue #338).

## Rollback

- There is no upstream fallback: `minio/minio` images no longer exist on
  any public registry, so reverting ci.yml to the old service block would
  only reintroduce a pull that always fails.
- If a replica build fails, restore the previous `RELEASE_TAG` value in
  `minio-replica.yml` and dispatch again. GHCR keeps every previously
  pushed `RELEASE.*` tag, so the old image stays pullable.
- If GHCR itself is unavailable, the e2e job fails at pull time. It fails
  closed rather than running the suite without an object store.

## See also

- Issue #973 — original report and root-cause investigation.
- PR #981 — the Docker Hub credentials attempt this design replaces.
- [minio/minio#21662](https://github.com/minio/minio/issues/21662) —
  upstream issue confirming the source-only move.
- `docs/codebase/security.md` — historical-secret allowlist protocol
  (related but separate concern).
