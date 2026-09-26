# MinIO replica for CI — `ghcr.io/ardelperal/minio`

> Last updated: 2026-09-26 — issue #973.

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

## The replica strategy

`.github/workflows/minio-replica.yml` builds the image from pinned MinIO
source and publishes it to this repository's GHCR namespace:

1. It checks out `https://github.com/minio/minio` at a pinned release tag
   and builds with `docker build` from the official Dockerfile in that
   repository.
2. The pinned release is `RELEASE.2025-10-15T17-29-55Z`, verified on
   2026-09-26 with `git ls-remote --tags https://github.com/minio/minio`
   as the highest existing `RELEASE.2025-*` tag.
3. It pushes two tags: `ghcr.io/ardelperal/minio:<RELEASE_TAG>` (immutable
   pin) and `ghcr.io/ardelperal/minio:ci` (moving tag the e2e job pulls).
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

The e2e job currently pulls the moving `ghcr.io/ardelperal/minio:ci` tag.
The digest pin is the follow-up, not a prerequisite:

1. Dispatch `minio-replica.yml` once; the job summary records the digest.
2. Replace `image: ghcr.io/ardelperal/minio:ci` in ci.yml with
   `image: ghcr.io/ardelperal/minio@sha256:<digest>`, following the
   repository's digest-pinning rule (issue #338).
3. After each future `RELEASE_TAG` bump, re-run the workflow and update the
   digest in the same commit. The `:ci` tag and the digest always refer to
   the same image content at that point.

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
