---
name: cadete-devops
description: Trigger: DevOps Cadete, Quay, OpenShift, despliegue, vulnerabilidad, CVE. Operate Cadete builds, releases, networking and rollback.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 1.0
  last_verified: 2026-09-05
  scope: ['cadete']
  auto_invoke: ['working on Cadete CI/CD']
  tiers: ['cadete']
---



# Cadete DevOps

## Activation Contract

Use this skill for Cadete image changes caused by CVEs, base-image updates, or application code releases. Operate from `C:\00repos\codigo\00_CADETE` unless the user explicitly provides another Cadete worktree.

## Hard Rules

- Never print tokens, `.env`, `quay_auth.json`, pull secrets, or decoded secret content.
- Production build uses root `Dockerfile`; never use `Dockerfile.local` for Quay/OCP.
- Quay authfile lives in this skill as a placeholder: `resources/quay_auth.json` (see also `quay_auth.json.example`). Generate the real authfile locally on the target environment with `podman login --authfile <path> <registry>`; never commit it — `.gitignore` blocks `resources/quay_auth.json`.
- Quay/OCP traffic must go through the corporate path (`10.14.x.x`, gateway `10.14.7.4`). Chat/Internet may use WiFi (`192.168.x.x`). If curl/push goes via WiFi, bind/route to the corporate interface.
- Before touching production, ask the user to run `oc login` for PRO. Do not paste or execute tokens yourself.
- Cadete frontend allows only one pod: always scale to `0`, change image, then scale to `1`.
- Capture rollback image before changes.

## Decision Gates

| Situation | Action |
|---|---|
| CVE in `nginx-filesystem` requires `1.26` | Enable `nginx:1.26` alongside `php:8.1` before installing packages. |
| Quay push times out from Podman VM | Verify Quay resolves to `10.139.40.18`; pin `/etc/hosts` in Podman machine if needed. |
| Route curl times out | Use `curl --interface 10.14.7.122` or the current corporate source IP. |
| Pullsecret found in OCP | Treat as pull-only unless proven otherwise; do not use it for push. |

## Execution Steps

1. Verify tooling and network: `podman version`, `oc version`, `Test-NetConnection quay.apps.ocgc4tools.mgmt.dc.es.telefonica -Port 443`.
2. Build with a traceable tag, e.g. `VNN-cve-YYYY-NNNNN` or `VNN-code-change`:
   `podman build --no-cache -t quay.apps.ocgc4tools.mgmt.dc.es.telefonica/wcdy/cadete:<TAG> -f Dockerfile .`
3. For CVE fixes, prove the RPM inside the local image before pushing, e.g. `podman run --rm <IMAGE> rpm -q nginx-filesystem`.
4. Push with the bundled authfile:
   `podman push --tls-verify=false <IMAGE> --authfile="C:\Proyectos\skills\cadete-devops\resources\quay_auth.json"`.
5. Ask the user to perform PRO login: `oc login --token=<TOKEN_PRO> --server=https://api.ocgc4pgpro01.mgmt.dc.es.telefonica:6443`.
6. Capture production state: deployment `cadetefrt`, container `container`, namespace `wcdy-prod-frt`, current image for rollback.
7. Deploy safely: `oc scale deployment/cadetefrt --replicas=0 -n wcdy-prod-frt`; wait until old pod is gone; `oc set image deployment/cadetefrt container=<IMAGE> -n wcdy-prod-frt`; `oc scale deployment/cadetefrt --replicas=1 -n wcdy-prod-frt`; wait for rollout.
8. Verify: pod `Ready 1/1`, zero restarts, `oc exec ... rpm -q nginx-filesystem` for CVEs, internal `curl http://127.0.0.1:8080/`, and external `curl -k --interface <corporate-ip> https://cadete.es.telefonica/`.

## Output Contract

Report: tag pushed, old image, new image, rollout result, pod name, RPM evidence for CVEs, internal curl HTTP code, external SiteMinder/curl result, and exact rollback command.

## References

- `references/cadete-cve-2026-42945.md` — captured incident notes and known-good commands.
