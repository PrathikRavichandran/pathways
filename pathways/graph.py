"""
Pathways state machine: explicit LangGraph wiring.

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

Topology (Phase 1, with slot-filling exit)
------------------------------------------

    START
      │
      ▼
    ┌──────┐  (crisis fired by hook)   ┌──────────┐
    │intake├──────────────────────────▶│ escalate │──▶ END
    └──┬───┘                           └──────────┘
       │ (slot still missing)
       └──────────────────────────────────────────▶ END  (slot prompt shipped)
       │ (all slots filled)
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

Phase 1 added the third intake exit ("slot still missing → END"). Before
Phase 1, intake always continued to retrieve on the first turn. Now it
can short-circuit back to the user with a slot prompt and resume on the
next turn (the checkpointer remembers what slots were filled).

Checkpointing
-------------
The compiled graph is checkpointer-aware. The checkpointer backend is
chosen by `PATHWAYS_CHECKPOINT_BACKEND` env var:
    memory (default), sqlite, postgres
See pathways/sessions/checkpointer.py for the factory.

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
from pathways.sessions.checkpointer import get_checkpointer
from pathways.state import PathwaysState


def _route_after_intake(state: PathwaysState) -> Literal["retrieve", "escalate", "END"]:
    """Three exits: continue normally, escalate, or short-circuit to END
    when intake shipped a slot-filling prompt to the user."""
    if state.next_node == "escalate":
        return "escalate"
    if state.next_node == "END":
        return "END"
    return "retrieve"


def _route_after_audit(state: PathwaysState) -> Literal["draft", "send", "escalate"]:
    if state.next_node == "draft":
        return "draft"
    if state.next_node == "send":
        return "send"
    return "escalate"


def build_graph(use_checkpointer: bool = True):
    """Build and compile the Pathways state machine.

    Args:
        use_checkpointer: If True (default), compile with the
            configured checkpointer so multi-turn conversations
            persist between invocations. Pass False in unit tests
            that want a stateless one-shot graph.

    Returns a compiled LangGraph app. Call:
        app.invoke({"user_message": "...", "crisis": ...},
                   config={"configurable": {"thread_id": tid}})
    for multi-turn.
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

    # intake → retrieve OR escalate (crisis) OR END (slot-filling)
    workflow.add_conditional_edges(
        "intake",
        _route_after_intake,
        {"retrieve": "retrieve", "escalate": "escalate", "END": END},
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

    if use_checkpointer:
        return workflow.compile(checkpointer=get_checkpointer())
    return workflow.compile()


# Singleton, instantiated lazily so test environments can import the
# module without paying graph-compile cost or hitting the DB.
_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


def reset_app() -> None:
    """Test helper: drop the cached compiled app so the next
    get_app() call rebuilds with current env settings."""
    global _APP
    _APP = None
