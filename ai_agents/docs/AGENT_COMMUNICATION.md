# Agent-to-Agent Communication (ADK AgentTool)

## ADK Pattern

Google ADK provides `AgentTool` for agent-to-agent communication where the calling agent retains control:

```
User → Agent A → AgentTool(Agent B) → Agent A continues → Response
```

## Architecture

```
                    ┌─────────────────┐
                    │   Root Agent    │
                    │  (entry point)  │
                    └────────┬────────┘
                             │
                    transfer_to_agent (sub-agents)
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
    ┌─────────────────┐ ┌─────────────┐ ┌─────────────┐
    │ release_readiness│ │documentation│ │ new_agent   │
    │     agent       │ │    agent    │ │             │
    └────────┬────────┘ └──────┬──────┘ └──────┬──────┘
             │                 │               │
             └─────── AgentTool ───────────────┘
                  (cross-agent queries)
```

## AgentRegistry API

```python
from core.agent_communication import AgentRegistry

# Register an agent
AgentRegistry.register(
    name="my_agent",
    description="What this agent does",
    factory=create_my_agent,
    capabilities=["cap1", "cap2"],
    example_queries=["Example question?"],
)

# Get AgentTools for cross-agent communication
tools = AgentRegistry.get_agent_tools(exclude="my_agent")

# Get tool descriptions for LLM instructions
descriptions = AgentRegistry.get_tool_descriptions(exclude="my_agent")

# List all agents
agents = AgentRegistry.list_agents()

# Get agent instance
agent = AgentRegistry.get_instance("my_agent")

# Clear cached instances (for reset)
AgentRegistry.clear_instances()
```

## Adding a New Agent

### Step 1: Create the Agent

```python
# ai_agents/my_agent/agent.py

from google.adk.agents import LlmAgent
from core.base import get_litellm_model

def create_my_agent(name: str = "my_agent"):
    model = get_litellm_model()
    
    # Get cross-agent tool descriptions
    from core.agent_communication import AgentRegistry
    cross_agent_docs = AgentRegistry.get_tool_descriptions(exclude=name)
    
    return LlmAgent(
        name=name,
        model=model,
        instruction=f"Your instruction...\n\n{cross_agent_docs}",
        description="What this agent does",
    )
```

### Step 2: Register the Agent

```python
# At the bottom of my_agent/agent.py OR in core/agent_communication.py

from core.agent_communication import AgentRegistry

AgentRegistry.register(
    name="my_agent",
    description="What this agent does",
    factory=create_my_agent,
    capabilities=["capability 1", "capability 2"],
    example_queries=["Example question?"],
)
```

**Done!** The agent is now:
- Discoverable by other agents via `AgentRegistry.list_agents()`
- Available as `AgentTool` via `AgentRegistry.get_agent_tools()`
- Included in LLM instructions via `AgentRegistry.get_tool_descriptions()`

### Step 3 (Optional): Add to Root Agent

To enable routing via `transfer_to_agent`:

```python
# ai_agents/root_agent/agent.py

from my_agent.agent import create_my_agent

def create_root_agent():
    my_agent = create_my_agent()
    
    return LlmAgent(
        name="root_agent",
        sub_agents=[release_agent, docs_agent, my_agent],
        ...
    )
```

## Files

| File | Purpose |
|------|---------|
| `core/agent_communication.py` | AgentRegistry + AgentTool creation |
| `core/runner.py` | Query execution |
| `root_agent/agent.py` | Root agent with sub-agents |
| `release_readiness_agent/agent.py` | Release tracking |
| `docs_agent/agent.py` | Documentation RAG |
