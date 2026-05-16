"""Session, thread, and idempotency utilities for the FastAPI ingress.

These modules exist outside the graph because they wrap concerns that the
graph itself should not know about: how an inbound SMS gets keyed to a
durable conversation, how duplicate webhook deliveries are detected, and
which checkpointer backend persists graph state across turns.

The graph stays pure (state in, state out). The ingress layer handles
the operational realities of running on Twilio.
"""

from pathways.sessions.checkpointer import get_checkpointer
from pathways.sessions.idempotency import seen_message_sid, touch_session
from pathways.sessions.thread import thread_id_for_phone, thread_id_for_web

__all__ = [
    "get_checkpointer",
    "seen_message_sid",
    "touch_session",
    "thread_id_for_phone",
    "thread_id_for_web",
]
