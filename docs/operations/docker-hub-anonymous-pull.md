# Docker Hub anonymous pulls — troubleshooting

> Last updated: 2026-09-25 — issue #973.

## Symptom

The CI job `e2e` fails before the test step with one of these:

```
docker: Error response from daemon: pull access denied for minio/minio,
repository does not exist or may require 'docker login'.
```

```
HTTP/2 401
www-authenticate: Bearer realm="https://auth.docker.io/token",service="registry.docker.io",
                   scope="repository:minio/minio:pull",error="insufficient_scope"
```

`podman pull` reports the same `pull access denied`. `curl` against
`https://registry-1.docker.io/v2/<repo>/manifests/latest` returns the
`insufficient_scope` body above.

## Why

Docker Hub's anti-abuse policy now refuses to issue the
`repository:<repo>:pull` scope on anonymous bearer tokens for a growing
set of source IP ranges, especially cloud-provider addresses. The
official pull-rate-limit page
([docs.docker.com/docker-hub/usage/pulls/](https://docs.docker.com/docker-hub/usage/pulls/))
still describes the older 100-pull/6h model and only documents the `429`
response, not the `401 insufficient_scope` we observe. The cutover date
is not in Docker's public changelog as of this writing — empirically it
started affecting cloud egress IPs sometime in 2025–2026.

## Workaround for this repo

PR #981 added the `credentials:` block to the `minio` service in
`.github/workflows/ci.yml`. Add two secrets at the repo or org level
(Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `DOCKERHUB_USERNAME` | Any Docker Hub account (free tier is enough). |
| `DOCKERHUB_TOKEN` | Personal Access Token from that account (Settings → Security → New Access Token). `image:read` scope on `minio/minio` is enough. |

The job then runs as before. Once the first authenticated pull succeeds,
the digest appears in the CI log; a follow-up commit will replace
`image: minio/minio:latest` with `image: minio/minio@sha256:<digest>`
to remove the `:latest` tag pin.

## Local reproduction

```bash
# Fails on cloud egress IPs after the 2025-2026 policy change:
docker pull minio/minio:latest

# Works regardless of source IP:
echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
docker pull minio/minio:latest
```

## Other workarounds (not used here)

1. **Mirror to GHCR**: push the image to `ghcr.io/<org>/minio` once with
   auth, then reference it from GHCR (which the runner can pull without
   extra creds via the implicit `GITHUB_TOKEN`). Costs one manual
   `docker pull && docker push` round-trip and an extra gigabyte of
   GHCR storage.
2. **Switch the e2e job to an in-cluster MinIO** (the user's Coolify
   instance hosts one). Requires opening the runner's network to the
   Coolify VPC and replacing the service-container block with a step
   that runs MinIO via `docker run`. Chosen not to be done here to
   avoid expanding the CI blast radius.

## See also

- Issue #973 — original report (run 36035660912).
- PR #981 — the `credentials:` block added to `ci.yml`.
- `docs/codebase/security.md` — historical-secret allowlist protocol
  (related but separate concern).
