# Local Development Setup

This document explains how to set up a local development environment for the APAP project. It covers the InsForge MCP integration and the per-developer secret management that keeps the repo clean.

## Prerequisites

- Python 3.11+ (per the architecture doc)
- Node.js 18+ (for the InsForge MCP server, which runs under npx)
- OpenCode CLI (the project's preferred AI coding agent)
- A free InsForge account at <https://insforge.app>

## One-time setup

### 1. Clone and enter the repo

```powershell
git clone <repo-url>
cd APAP_WEB
```

### 2. Configure the InsForge MCP

The repo ships with `opencode.json.example` (a template with placeholder values) and `.gitignore` already excludes the real `opencode.json`. To enable the InsForge MCP for your local sessions:

```powershell
# Copy the template to the real config location
Copy-Item opencode.json.example opencode.json

# Edit opencode.json and replace the placeholders with your own credentials
notepad opencode.json
```

In `opencode.json`, replace:

| Placeholder | Replace with |
|-------------|--------------|
| `ik_replace_me_with_your_insforge_admin_api_key` | Your InsForge admin API key (from the InsForge dashboard, project settings) |
| `https://your-app-region.insforge.app` | Your InsForge project URL (region is in the URL, e.g. `c3uc9dk6.eu-central.insforge.app`) |

`opencode.json` stays untracked by git. Each developer keeps their own copy with their own credentials.

### 3. Where to get the credentials

- **Admin API key**: InsForge dashboard → your project → Settings → API keys → Create admin key. Copy the value once and store it in a password manager. If the value ever appears in a tracked file or in a commit, revoke it immediately and create a new one.
- **API base URL**: InsForge dashboard → your project → the URL shown at the top of the page (format: `https://<id>.<region>.insforge.app`).

### 4. Verify the MCP works

```powershell
# In the project directory
opencode mcp list
```

You should see `insforge` listed as a configured MCP server. To test a tool:

```powershell
# Example: inspect configured backend metadata
opencode mcp call insforge get-backend-metadata
```

### 5. (Optional) Configure git so accidental commits of opencode.json are rejected

Even though the file is gitignored, a defensive `pre-commit` hook can catch the case where someone runs `git add -f opencode.json`:

```bash
# .git/hooks/pre-commit (or via husky/lefthook)
if git diff --cached --name-only | grep -q '^opencode\.json$'; then
  echo "ERROR: opencode.json is gitignored. Use opencode.json.example as the template."
  exit 1
fi
```

## Why is this pattern?

The `opencode.json` file contains an admin API key, which is a **secret**. Admin keys in the wrong hands let an attacker read and modify your entire InsForge project (database, storage, auth, functions). The pattern used here:

1. **Template committed** (`opencode.json.example`) — anyone can see the structure and copy it.
2. **Real config gitignored** (`opencode.json`) — secrets never reach the remote.
3. **Rotation is easy** — when a key is exposed, revoke the old one in the InsForge dashboard and create a new one. No code changes needed.
4. **No "real" config in environment-specific deploys** — the GitHub Actions workflow for `ci-cd-foundation` injects the secrets from GitHub Actions secrets, not from a tracked file.

## Related

- `.gitignore` — contains the rule that ignores `opencode.json`
- `opencode.json.example` — the template
- `docs/architecture-insforge-stack.md` § Stack — the canonical architecture doc
- `openspec/changes/ci-cd-foundation/` — the SDD change that plans the deploy pipeline (PR 2 needs `INSFORGE_API_KEY` and `INSFORGE_API_BASE_URL` as GitHub Actions secrets)
