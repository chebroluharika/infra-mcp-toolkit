# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial public release of infra-mcp-toolkit
- 7 MCP servers: JIRA, TestRail, Jenkins, GitHub, GSheets, Release Calendar, Release Risk
- FastAPI backend (port 8000) with 18 routers + 7 background schedulers
- React 18 dashboard (port 8080 in Docker, 3000 in dev)
- Streamlit AI chat (port 8501) with Google ADK + LiteLLM (Ollama, OpenAI, Gemini, Anthropic providers)
- Docker Compose setup with automatic OS detection (bridge networking on Mac/Windows, host networking on Linux)
- OSS repository files: LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue & PR templates
- GitHub Actions CI: Python syntax check, frontend build, full Docker stack boot, secrets scan

## [0.1.0] — TBD

- First tagged release.
