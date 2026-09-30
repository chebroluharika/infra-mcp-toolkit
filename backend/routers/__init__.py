"""
FastAPI Routers Package
=======================

Modular endpoint organization for the QE Agentic Dashboard API.

Routers:
    - ai_chat: AI conversational interface
    - dev_insights: Developer insights (workload, knowledge gaps, digest)
    - docs_updates: Documentation updates tracking
    - escalation_analysis: Customer escalation analysis
    - github: GitHub commit tracking
    - index: FAISS index management
    - jenkins: Jenkins pipelines & TFA
    - jira: JIRA bugs & escalations
    - on_call_calendar: On-call rotation schedule
    - overview: Dashboard, RRS, releases config
    - pdv: PDV (Post-Deployment Validation) status
    - rancher: Rancher kubeconfig management
    - release_calendar: Release calendar with milestone dates
    - release_risk: Release risk prediction
    - slack: Slack notifications
    - testrail: TestRail integration
"""

from . import (
    ai_chat,
    dev_insights,
    docs_updates,
    escalation_analysis,
    github,
    index,
    jenkins,
    jira,
    on_call_calendar,
    overview,
    pdv,
    rancher,
    release_calendar,
    release_risk,
    slack,
    testrail,
)

__all__ = [
    "ai_chat",
    "dev_insights",
    "docs_updates",
    "escalation_analysis",
    "github",
    "index",
    "jenkins",
    "jira",
    "on_call_calendar",
    "overview",
    "pdv",
    "rancher",
    "release_calendar",
    "release_risk",
    "slack",
    "testrail",
]
