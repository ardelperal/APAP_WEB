# GitHub Self-Hosted Runner Registration (issue #223)

This runbook documents how to register, verify, and decommission the dedicated
Oracle ARM64 self-hosted runner that runs the `e2e` job in
`.github/workflows/ci.yml` and the full `e2e (self-hosted)` workflow
(`.github/workflows/e2e-self-hosted.yml`).

The runner lives on the Oracle ARM64 VPS that also hosts Cadete. It is
**strictly isolated** from Cadete: separate runner directory, separate
systemd unit, no shared credentials, no sudo access.

---

## Current production state

| Property | Confirmed value |
|---|---|
| Runner user | `ubuntu` (not root, not github-actions) |
| Runner root directory | `/home/ubuntu/github-runner/apap-web/` |
| Systemd unit | `github-runner-apap-web.service` |
| Labels (exact, required) | `self-hosted`, `Linux`, `ARM64`, `apap`, `oracle` |
| Runner group | `Default` (repository-scoped) |
| Architecture | Oracle ARM64 (Ampere Altra) |
| GitHub repo | `ardelperal/APAP_WEB` |

---

## When to trigger

Use this runbook when:

- Provisioning a **new** self-hosted runner for the first time.
- Verifying an **existing** runner after a VPS reboot.
- Re-registering a runner after the VPS hostname or IP changes.
- **Decommissioning** the runner (e.g. before a VPS rebuild).
- Running the weekly smoke-test schedule (`e2e (self-hosted)` workflow).

---

## Pre-deploy checklist

Before registering or re-registering:

- [ ] Confirm you have a working SSH connection to the Oracle ARM64 VPS as
      `ubuntu` (the sudo-capable admin user).
- [ ] Confirm the VPS is reachable from GitHub Actions (no VPN, no firewall
      blocking port 443 outbound to `github.com`).
- [ ] Retrieve the **runner registration token** from GitHub:
      `Settings → Actions → Runners → New self-hosted runner → copy the
      registration command (contains the token)`.
      The token is short-lived; complete registration within 30 minutes.
- [ ] Confirm no other runner on this VPS uses the same runner directory
      (`/home/ubuntu/github-runner/apap-web/`). Sharing the directory between
      runners causes job-assignment conflicts.
- [ ] Confirm the Cadete runner directory is untouched:
      `ls /home/ubuntu/github-runner/cadete/` exists and its unit is
      `github-runner-cadete.service`. **Never reuse Cadete's directory or unit.**
- [ ] Verify `python3 --version` on the VPS returns Python >= 3.11 (matches
      the `python-version-file: pyproject.toml` in ci.yml).
- [ ] Confirm `playwright install chromium` has been run at least once on the
      runner user account (or that the e2e job installs it at runtime — it does,
      so this is optional).

---

## Registration steps

### 1. SSH into the VPS

```bash
ssh ubuntu@<vps-ip-or-hostname>
```

### 2. Create the runner directory

```bash
sudo mkdir -p /home/ubuntu/github-runner/apap-web
sudo chown ubuntu:ubuntu /home/ubuntu/github-runner/apap-web
# Verify separation from Cadete
ls /home/ubuntu/github-runner/
# Expected output: cadete/  apap-web/
```

### 3. Download the GitHub Actions runner

```bash
cd /home/ubuntu/github-runner/apap-web
# Download the latest linux-arm64 release (check https://github.com/actions/runner/releases)
curl -L -o actions-runner-linux-arm64-latest.tar.gz \
  https://github.com/actions/runner/releases/download/v2.323.0/actions-runner-linux-arm64-2.323.0.tar.gz
tar xzf actions-runner-linux-arm64-latest.tar.gz --strip-components=1
rm actions-runner-linux-arm64-latest.tar.gz
```

> **Note:** Replace `v2.323.0` with the current release version from
> `https://github.com/actions/runner/releases`. The ARM64 binary is
> `actions-runner-linux-arm64-<version>.tar.gz`.

### 4. Configure the runner

```bash
cd /home/ubuntu/github-runner/apap-web
./config.sh \
  --url https://github.com/ardelperal/APAP_WEB \
  --token <REGISTRATION_TOKEN> \
  --labels "self-hosted,Linux,ARM64,apap,oracle" \
  --runnergroup Default \
  --work _work \
  --unattended \
  --replace
```

Key flags:
- `--labels`: must include **all five** labels exactly as shown.
  GitHub Actions matches jobs to runners by label; partial matches do **not** work.
- `--replace`: use only when re-registering an existing runner (e.g. after token
  expiry). It removes the old registration and re-registers with the new token.
- `--unattended`: prevents interactive prompts (safe for systemd use).

### 5. Install and enable the systemd service

```bash
sudo ./svc.sh install ubuntu
sudo ./svc.sh start
```

Verify:

```bash
systemctl status github-runner-apap-web.service
# Expected: active (running)
sudo journalctl -u github-runner-apap-web.service -f --since "2 minutes ago"
```

### 6. Verify the runner appears in GitHub

1. Go to `https://github.com/ardelperal/APAP_WEB → Settings → Actions → Runners`.
2. Confirm the runner `apap-web` appears under **Self-hosted runners** with
   all five labels and status **Idle** (or **Online** if a job just ran).
3. If status is **Offline**, check `journalctl` on the VPS and the
   `runner diagnostics` section below.

### 7. Run the connectivity check script

From your **local machine** (not the VPS):

```bash
./scripts/check-runner.ps1 -RunnerUrl "https://github.com/ardelperal/APAP_WEB" -Labels "self-hosted,Linux,ARM64,apap,oracle"
```

Expected output: runner is reachable, has the expected labels, and is in
**Idle** or **Online** state.

---

## Runner diagnostics

If the runner shows **Offline** in GitHub:

### On the VPS

```bash
# Check service status
systemctl status github-runner-apap-web.service

# View recent logs
sudo journalctl -u github-runner-apap-web.service -n 50 --no-pager

# Check runner process
ps aux | grep '[g]ithub-runner'

# Check network reachability
curl -s --max-time 10 https://github.com
curl -s --max-time 10 https://objects.githubusercontent.com
```

### Common fixes

**Token expired**: Re-register using `config.sh --replace` with a fresh token.

**Port 443 blocked outbound**: Configure the VPS firewall to allow outbound
TCP 443 to `github.com` and `objects.githubusercontent.com`.

**Runner directory conflict**: If Cadete's runner is also pointing to
`/home/ubuntu/github-runner/apap-web/`, its jobs will steal this runner's
assignments. Ensure Cadete's `run.sh` or `svc.sh` points to a different
directory (`/home/ubuntu/github-runner/cadete/`).

---

## Reboot recovery

The systemd service is configured to start automatically after reboot
(` WantedBy=multi-user.target` via `./svc.sh install`). To verify:

```bash
# Simulate a reboot
ssh ubuntu@<vps-ip> "sudo systemctl restart github-runner-apap-web.service"
# Wait 10 seconds
sleep 10
# Check status
ssh ubuntu@<vps-ip> "systemctl status github-runner-apap-web.service"
# Verify runner is online in GitHub Settings → Actions → Runners
```

If the runner does **not** come back online after a real VPS reboot:

1. SSH into the VPS.
2. Check `systemctl status github-runner-apap-web.service`.
3. If the service is failed, re-run `./svc.sh install && ./svc.sh start`.
4. If the process is running but GitHub shows Offline, the registration token
   may have expired — re-register with `config.sh --replace`.

---

## Deregistration / rollback

To permanently remove the runner (e.g. before a VPS rebuild):

### On the VPS

```bash
cd /home/ubuntu/github-runner/apap-web
sudo ./svc.sh stop
sudo ./svc.sh uninstall
cd ..
sudo rm -rf /home/ubuntu/github-runner/apap-web
```

### In GitHub

1. Go to `https://github.com/ardelperal/APAP_WEB → Settings → Actions → Runners`.
2. Find the `apap-web` runner.
3. Click the ellipsis menu → **Remove runner**.
   This removes the runner from GitHub's registry and prevents stale
   job assignments.

### After deregistration

- The `ci.yml` e2e job will automatically fall back to `ubuntu-latest`
  because `APAP_SELF_HOSTED_E2E_ENABLED` will no longer route jobs to the
  now-nonexistent self-hosted runner. No YAML change is needed.
- The `e2e-self-hosted.yml` workflow will skip all its jobs silently
  (its `if` condition checks `vars.APAP_SELF_HOSTED_E2E_ENABLED != ''`).

---

## Secrets and credentials

The runner requires **no additional secrets** beyond what the e2e job already
needs:

| Secret / Variable | Already exists | Used for |
|---|---|---|
| `APAP_OAUTH_CLIENT_ID` | Yes (repository variable) | OAuth gate in ci.yml e2e job |
| `APAP_GOOGLE_CLIENT_SECRET` | Yes (repository secret) | OAuth flow in e2e tests |
| `APAP_SELF_HOSTED_E2E_ENABLED` | No — **create it** | Controls `runs-on` in ci.yml e2e job |

### Creating `APAP_SELF_HOSTED_E2E_ENABLED`

In GitHub: `Settings → Actions → Variables → New variable`:

- **Name**: `APAP_SELF_HOSTED_E2E_ENABLED`
- **Value**: `1` (any non-empty string enables the self-hosted runner)
- **Description**: `Enables the self-hosted Oracle ARM64 runner for the e2e job (issue #223)`

> Without this variable, the e2e job in `ci.yml` falls back to `ubuntu-latest`
> (backwards compatible). Set it to `1` only after the runner is confirmed
> online.

---

## Cross-reference

- `.github/workflows/ci.yml` — `e2e` job with conditional `runs-on`
- `.github/workflows/e2e-self-hosted.yml` — dedicated self-hosted workflow
- `scripts/check-runner.ps1` — runner connectivity check
- `AGENTS.md` §15.1 — pre-MVP CI gate (lint, typecheck, test, build only;
  e2e remains optional in pre-MVP)
- `vps-oracle` IaC repository — provisioning code for the VPS itself
