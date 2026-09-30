# Contributing to infra-mcp-toolkit

Thanks for your interest in contributing! This toolkit thrives on community input — new MCP servers, better docs, bug fixes, and integrations with other CI/CD or issue-tracking tools are all welcome.

## Ways to contribute

- **Report a bug** → open an issue using the Bug Report template
- **Suggest a feature** → open an issue using the Feature Request template
- **Add a new MCP server** → see [Adding a new MCP server](#adding-a-new-mcp-server)
- **Improve docs** → typos, clarifications, examples — no PR is too small
- **Add a language pack for the AI agents** → prompts and instructions currently assume English
- **Look at `good first issue` labels** → tagged tickets are triaged and scoped for newcomers

## Before you start work on a large change

Open an issue first to discuss the approach. Nobody wants to write 500 lines of code just to find out it doesn't fit the architecture.

## Development setup

Follow the Manual Setup section in the [README](README.md). TL;DR:

```bash
git clone https://github.com/<owner>/infra-mcp-toolkit.git
cd infra-mcp-toolkit
cp .env.example .env         # fill in only what you need
make build && make up        # or run backend/frontend/streamlit manually
```

## Pull request checklist

Before you open a PR:

- [ ] `make build` succeeds locally
- [ ] Backend tests pass: `cd backend && pytest` (if you added tests)
- [ ] Frontend builds cleanly: `npm run build`
- [ ] `docker logs qe-dashboard-backend` shows no new warnings on startup
- [ ] You've updated the README or `docs/` for any user-facing change
- [ ] Your commits are signed off (`git commit -s`) — this is our DCO
- [ ] No credentials, tokens, or company-internal URLs in the diff
- [ ] PR description explains **what** changed and **why**

## Sign off your commits

We use the [Developer Certificate of Origin](https://developercertificate.org/). Every commit must be signed off:

```bash
git commit -s -m "Add support for GitLab MCP server"
```

That adds a `Signed-off-by: Your Name <you@example.com>` trailer, which is a lightweight way of stating that you have the right to submit the code under this project's license.

## Adding a new MCP server

Servers live in `mcp_servers/<name>-mcp-server/`. Follow the pattern of an existing one (e.g. `jira-mcp-server`):

1. Create `mcp_servers/<name>-mcp-server/server.py` using FastMCP
2. Add tool functions with clear docstrings — the docstring is the LLM's prompt
3. Add the corresponding service client in `backend/services/<name>_client.py`
4. Create the API router in `backend/routers/<name>.py`
5. Register the router in `backend/main.py` (`app.include_router(...)`)
6. Add env vars to `.env.example`
7. Update the README's MCP servers table
8. Add basic tests

## Coding style

- **Python**: PEP 8, type hints on new public functions, `black` for formatting
- **JavaScript/React**: Prettier defaults, functional components, hooks over class components
- **Docstrings on MCP tools are prompts** — write them for the LLM audience, not just for humans

## Reporting security issues

**Please do not open a public issue for security vulnerabilities.** See [SECURITY.md](SECURITY.md) for the disclosure process.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.

## Questions?

Open a [Discussion](https://github.com/<owner>/infra-mcp-toolkit/discussions) — good for anything that isn't clearly a bug or a feature request.
