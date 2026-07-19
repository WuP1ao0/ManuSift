# Security Policy

## Supported versions

| Version   | Supported |
|-----------|-----------|
| 0.1.x β   | Yes       |

## Reporting a vulnerability

Please **do not** open a public issue for security problems that could
expose user data, secrets, or allow remote code execution.

Prefer one of:

1. GitHub **Private vulnerability reporting** (Security tab → Advisories), if enabled
2. Open a private report to the maintainer account that owns this repository

Include: affected version/commit, impact, reproduction steps, and any
suggested fix. You should receive an acknowledgement within a few days.

## Secrets and local config

- Never commit `.env` or API keys. Use `.env.example` as a template.
- Offline screening (`manusift screen --no-llm`) does **not** require cloud keys.
- Dependency audit: `pip install pip-audit && pip-audit` (see also `docs/SECURITY.md`).

## Scope notes

ManuSift processes user-supplied PDFs and may write job artifacts under
`data/jobs/` (or `MANUSIFT_WORKSPACE_DIR`). Treat those paths as sensitive on
shared machines.
