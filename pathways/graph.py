"""
Pathways state machine — explicit LangGraph wiring.

This is the central architectural artifact of the repo. The decision to
write the graph explicitly (rather than as a thin coordinator over a
single multi-tool agent) buys three things:

1. **Auditability.** Every transition is named and traceable. When a
   conversation goes sideways, the trace tells you which node decided
   what, in what order. A monolithic prompt that "decides everything"
   doesn't give you that.

2. **Targeted intervention.** Failure modes have addresses. Low retrieval
   confidence is a retrieve-node concern; tone drift is a draft-node
   concern; uncited claims are an audit-node concern. We can iterate one
   node at a time, with one eval at a time, without re-validating the
   whole system.

3. **Bounded capability per stage.** The audit node doesn't get to retrieve.
   The retrieve node doesn't get to draft. Each node has the minimum
   capability to do its job. This mirrors the sub-agent bounded-capability
   pattern at the graph layer.

Topology
--------

    START
      │
      ▼
    ┌──────┐  (crisis fired by hook)  ┌──────────┐
    │intake├─────────────────────────▶│ escalate │──▶ END
    └──┬───┘                          └──────────┘
       │ (normal path)
       ▼
    ┌──────────┐
    │ retrieve │
    └────┬─────┘
         ▼
    ┌──────┐
    │match │
    └──┬───┘
       ▼
    ┌──────┐
    │ draft│◀─────────────┐
    └──┬───┘              │ (soft_block + budget remaining)
       ▼                  │
    ┌──────┐              │
    │ audit├──────────────┘
    └──┬───┘
       │ (pass)            (hard_block | budget exhausted)
       ▼                          ▼
    ┌──────┐                ┌──────────┐
    │ send │──▶ END         │ escalate │──▶ END
    └──────┘                └──────────┘

Notes on revision loop
----------------------
The draft ⇄ audit loop is bounded by state.MAX_AUDIT_REVISIONS (default 2).
Past that, the conversation is escalated to a human navigator rather than
allowed to ship a marginal response. The bound is a hard property of the
graph topology, not the model's discretion.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph

from pathways.nodes import audit as audit_node
from pathways.nodes import draft as draft_node
from pathways.nodes import escalate as escalate_node
from pathways.nodes import intake as intake_node
from pathways.nodes import match as match_node
from pathways.nodes import retrieve as retrieve_node
from pathways.nodes import send as send_node
from pathways.state import PathwaysState


def _route_after_intake(state: PathwaysState) -> Literal["retrieve", "escalate"]:
    return "escalate" if state.next_node == "escalate" else "retrieve"


def _route_after_audit(state: PathwaysState) -> Literal["draft", "send", "escalate"]:
    if state.next_node == "draft":
        return "draft"
    if state.next_node == "send":
        return "send"
    return "escalate"


def build_graph():
    """Build and compile the Pathways state machine.

    Returns a compiled LangGraph app. Call `app.invoke(state)` to run it,
    or `app.stream(state)` to observe node-by-node execution (useful for
    LangSmith tracing and for the FastAPI streaming endpoint).
    """
    workflow = StateGraph(PathwaysState)

    workflow.add_node("intake", intake_node.run)
    workflow.add_node("retrieve", retrieve_node.run)
    workflow.add_node("match", match_node.run)
    workflow.add_node("draft", draft_node.run)
    workflow.add_node("audit", audit_node.run)
    workflow.add_node("escalate", escalate_node.run)
    workflow.add_node("send", send_node.run)

    workflow.set_entry_point("intake")

    # intake → retrieve OR escalate (crisis short-circuit)
    workflow.add_conditional_edges(
        "intake",
        _route_after_intake,
        {"retrieve": "retrieve", "escalate": "escalate"},
    )

    # Linear retrieve → match → draft
    workflow.add_edge("retrieve", "match")
    workflow.add_edge("match", "draft")

    # draft → audit (always)
    workflow.add_edge("draft", "audit")

    # audit → send (pass) OR draft (soft_block, budget remaining) OR escalate
    workflow.add_conditional_edges(
        "audit",
        _route_after_audit,
        {"draft": "draft", "send": "send", "escalate": "escalate"},
    )

    workflow.add_edge("send", END)
    workflow.add_edge("escalate", END)

    return workflow.compile()


# Singleton — instantiate lazily so test environments can import the
# module without paying graph-compile cost.
_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP
