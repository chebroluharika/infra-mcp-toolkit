# AI Agents Module

Multi-agent AI system for the Agentic Insights Portal using Google ADK (Agent Development Kit) with MCP tools.

## Architecture

```
ai_agents/
├── root_agent/          # Root Agent (entry point)
│   └── agent.py         # Routes queries to sub-agents
├── release_readiness_agent/  # Release Readiness Agent
│   ├── agent.py         # Release status, bugs, tests
│   └── tools/
│       └── mcp_tools.py # MCP server integration
├── docs_agent/          # Documentation Agent (RAG)
│   ├── agent.py         # Documentation search
│   └── tools/
│       ├── scraper.py   # Web scraper for docs
│       ├── chunker.py   # Text chunking
│       ├── embeddings.py # Embedding providers
│       ├── vector_store.py # FAISS vector store
│       └── rag_pipeline.py # Full RAG pipeline
├── core/
│   ├── base.py          # LiteLLM integration
│   └── runner.py        # Agent execution engine
├── config.py            # LLM configuration
├── streamlit_app.py     # Chat UI
└── requirements.txt     # Dependencies
```

## MCP Servers

All tools are provided by MCP servers:
- **jira-mcp-server**: Bugs, escalations, release status
- **release-calendar-mcp-server**: Release dates, milestones
- **testrail-mcp-server**: Test execution status
- **jenkins-mcp-server**: CI/CD pipeline status
- **github-mcp-server**: Commit tracking

```bash
# Start the chat UI (MCP servers auto-connect)
streamlit run streamlit_app.py
```

## Quick Start

```bash
# Install dependencies
cd ai_agents
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start Ollama (if using local LLM)
ollama pull llama3.2:latest

# Run the chat UI
streamlit run streamlit_app.py
```

## Configuration

Set via environment variables or `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `ADK_LLM_PROVIDER` | ollama | Provider: ollama, openai, gemini, anthropic |
| `ADK_LLM_MODEL` | llama3.2:latest | Model name |
| `ADK_OLLAMA_BASE_URL` | http://localhost:11434 | Ollama server URL |
| `ADK_OPENAI_API_KEY` | - | OpenAI API key (if using OpenAI) |
| `GOOGLE_API_KEY` | - | Google API key (if using Gemini) |

## Agents

### Root Agent
Entry point that routes queries to specialized sub-agents (ADK pattern):
- Greetings → Direct response
- Release/bugs/stories → Release Readiness Agent
- Documentation → Documentation Agent

### Release Readiness Agent
Handles queries about:
- Release status and health
- Bug tracking (P0, P1, blockers)
- Story progress
- Milestone timelines
- Assignee workload

### Documentation Agent (In Progress)
Uses RAG pipeline for:
- Product documentation search
- How-to guides
- Configuration help

## Usage Examples

```python
from ai_agents import create_root_agent_async, get_runner

# Create root agent with MCP tools (async)
root_agent, cleanup = await create_root_agent_async()

# Get the runner for agent execution
runner = get_runner()

# Run a query
response = await runner.run(
    agent=root_agent,
    message="Is R134 looking green?",
    session_id="user-123",
)
print(response.content)

# Cleanup MCP connections when done (optional)
await cleanup()
```

## Agent-to-Agent Communication

Agents can communicate with each other:

```python
# From within an agent, query another agent
result = await ask_docs_agent("How to configure proxy?")
result = await ask_release_agent("What's blocking R134?")
```

See `docs/AGENT_COMMUNICATION.md` for details.
