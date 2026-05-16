"""Opt-in parole reporting reminder.

Highest-claimed impact item from the original Phase 6 list. Missed
check-ins are the single largest driver of technical-violation recidivism
in the literature, and the typical returning citizen does not have the
calendar/phone-reminder infrastructure people on the outside take for
granted. A free SMS the day before is a small intervention with a real
floor under it.

Flow:
    1. Intake detects supervision_status == parole.
    2. Draft node, after composing its reply, appends a one-line offer:
       "Want me to text you the day before each check-in? Reply YES with
       the date (e.g., YES March 5)." This sets intake.parole_reminder_
       offered=True so we never re-offer.
    3. Next user turn: if the message starts with "yes" or "si" AND
       intake.parole_reminder_offered, the intake extractor parses a
       date from the same message and writes a row to the parole_
       reminders store.
    4. A daily external cron hits POST /admin/run-parole-reminders
       (shared-secret auth). The service scans for reminders whose
       check_in_date == tomorrow AND sent_at is null, sends an SMS via
       the Twilio outbound wrapper, and marks them sent.

The store has two backends mirroring the analytics module: postgres for
production, in-memory for tests + demo. Phone numbers are never
persisted; the store keys by the salted thread_id only. The Twilio
client uses the existing trial-aware wrapper, so unverified destinations
get a warning instead of a failed paid send.
"""

from pathways.parole_reminders.service import (
    detect_opt_in_reply,
    record_reminder_if_opt_in,
    run_send_loop,
)
from pathways.parole_reminders.store import (
    ParoleReminder,
    get_store,
    record_reminder,
    reset_store,
)

__all__ = [
    "ParoleReminder",
    "detect_opt_in_reply",
    "get_store",
    "record_reminder",
    "record_reminder_if_opt_in",
    "reset_store",
    "run_send_loop",
]
