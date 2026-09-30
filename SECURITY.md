# Security Policy

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

If you discover a security issue, report it privately using one of the following:

1. **GitHub Security Advisories** (preferred) — go to the repository's **Security** tab → **Report a vulnerability**. This creates a private thread with the maintainers.
2. **Email**: send details to **opensource-security@netskope.com** with the subject `[infra-mcp-toolkit] Security Issue`.

Please include, if possible:

- A description of the issue and its potential impact
- Steps to reproduce, or proof-of-concept code
- Affected version(s) or commit SHA
- Suggested remediation, if you have one

## Response process

- We acknowledge every report within **3 business days**.
- We investigate and confirm the issue within **10 business days**.
- We aim to release a fix within **30 days** for high/critical severity issues, longer for lower severity.
- We publish a security advisory and credit the reporter (unless they prefer to remain anonymous) once a fix is released.

## Supported versions

Only the latest tagged release on the `main` branch receives security fixes. Users on older versions are expected to upgrade.

| Version | Supported |
|---|---|
| `main` / latest release | ✅ |
| Older tagged releases | ❌ |

## Scope

This policy covers the code in this repository. It does **not** cover:

- Third-party integrations (JIRA, Jenkins, TestRail, GitHub, etc.) — report those upstream
- User misconfiguration (e.g. exposing a `.env` file with credentials publicly)
- Self-hosted deployments where the operator has modified the code

## Safe-harbor

We support good-faith security research. If you follow this policy, we will not pursue legal action against you for your research activities.
