# Oracle VPS topology

Facts verified 2026-08-11. Re-verify before citing; the host changes.

## Host

| | |
|---|---|
| SSH | `ssh oracle` (alias in `~/.ssh/config`, key `~/.ssh/oracle.key`) |
| Hostname | `vinc-ardelperal` |
| Arch / kernel | `aarch64`, Linux 6.17 `-oracle` |
| Capacity | 4 vCPU, 23 GiB RAM |
| Disk | `/dev/sda1` 194 G, was 67 % used |
| Runtimes | Docker 29.6.2 **and** podman 4.9.3 |

From Git Bash on the Windows workstation the alias needs explicit flags,
because that shell resolves a different `HOME`:

```sh
ssh -F /c/Users/adm1/.ssh/config \
    -o UserKnownHostsFile=/c/Users/adm1/.ssh/known_hosts \
    oracle '<command>'
```

## Runner inventory

All runners are Coolify **services** on this single host. Coolify here is
**4.1.2**, below 4.2, so `service action=list_containers` and
`logs resource=service` return `Not found` over MCP — read container state over
SSH instead.

| Repo | Coolify service | Image |
|---|---|---|
| `ardelperal/APAP_WEB` | `apap-github-runner` | `ghcr.io/actions/actions-runner:latest` |
| `DysTelefonica/access2web-blueprint` | `a2w-blueprint-runner` | `myoung34/github-runner:ubuntu-noble` |
| `planhub` | `planhub-runner` | `myoung34/github-runner:latest` |

Both images accept a PAT. `myoung34` reads it from `ACCESS_TOKEN` natively;
`actions-runner` needs the mint-at-start command in
`assets/runner-compose.yml`. Either way the rule is the same: no static
`RUNNER_TOKEN`.

## Labels currently in use

| Runner | Labels |
|---|---|
| `apap-coolify-noble` | `self-hosted,Linux,ARM64,apap,oracle,coolify,noble` |
| `apap-web-oracle-arm64` | `self-hosted,Linux,ARM64,apap,oracle` |

The second one matches **no job** in APAP_WEB: every job requires `coolify` and
`noble`, which it lacks. It reads as redundancy on the runners page while
providing none. Treat a runner that cannot match any job as absent.

## Workspace paths

One directory per runner under `/data/runners/`. Sharing one between two
instances makes two branches check out over each other.

## Billing context

`ardelperal/APAP_WEB` is **private**, so GitHub-hosted minutes are billed and
were exhausted — that is why every job moved here. `access2web-blueprint` lives
in the DysTelefonica org with separate billing, so routing some of its gates
back to `ubuntu-24.04` is viable there and is **not** portable to APAP_WEB.
Check repo visibility and the owning account before copying a routing decision
between repos.
