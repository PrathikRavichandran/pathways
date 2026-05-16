"""parole_reminders service: opt-in parsing, date extraction, send loop.

The detector is intentionally conservative: we only treat a reply as a
yes-with-date when both signals are present (an affirmative keyword AND
a parseable date). This avoids opting users in to recurring SMS based on
a casual "yes" with no clear date context, which would be a TCPA risk
even with prior consent.

Supported affirmative forms:
    English:  "yes", "yes please", "yes thanks", "ok", "okay", "sure"
    Spanish:  "si", "sí", "sí por favor", "esta bien", "está bien", "claro"

Supported date forms:
    ISO        2026-03-05
    MM/DD      3/5  or 03/05  (assume current year; advance year if past)
    MM-DD      3-5
    Month DD   "march 5", "Mar 5th", "marzo 5"
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from pathways.parole_reminders.store import (
    ParoleReminder,
    get_store,
)

logger = logging.getLogger("pathways.parole_reminders")

_AFFIRM_EN = {
    "yes", "y", "ok", "okay", "sure", "yep", "yeah", "please",
    "yes please", "yes thanks", "sounds good",
}
_AFFIRM_ES = {
    "si", "sí", "ok", "claro", "esta bien", "está bien",
    "si por favor", "sí por favor",
}

_DECLINE_EN = {"no", "nope", "n", "stop", "no thanks"}
_DECLINE_ES = {"no", "no gracias"}

_MONTHS = {
    "jan": 1, "january": 1, "ene": 1, "enero": 1,
    "feb": 2, "february": 2, "febrero": 2,
    "mar": 3, "march": 3, "marzo": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "june": 6, "junio": 6,
    "jul": 7, "july": 7, "julio": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "septiembre": 9,
    "oct": 10, "october": 10, "octubre": 10,
    "nov": 11, "november": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dic": 12, "diciembre": 12,
}


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _parse_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """Extract a date from the text. Tries ISO, MM/DD, MM-DD, Month DD.

    For partial dates (no year), assumes the current year; if the
    resulting date is in the past, advances to next year so a "March 5"
    reply in April lands on next year's check-in, not the past one.
    """
    today = today or date.today()
    if not text:
        return None
    t = text.strip().lower()

    # ISO YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # MM/DD or MM/DD/YY(YY)
    m = re.search(r"(?<!\d)(\d{1,2})[/](\d{1,2})(?:[/](\d{2,4}))?(?!\d)", t)
    if m:
        try:
            month = int(m.group(1))
            day = int(m.group(2))
            year_str = m.group(3)
            if year_str:
                year = int(year_str)
                if year < 100:
                    year += 2000
            else:
                year = today.year
            d = date(year, month, day)
            if not year_str and d < today:
                d = date(year + 1, month, day)
            return d
        except ValueError:
            pass

    # MM-DD (avoid ISO false positive by requiring single/double digit on left)
    m = re.search(r"(?<!\d)(\d{1,2})-(\d{1,2})(?!\d)", t)
    if m:
        try:
            month = int(m.group(1))
            day = int(m.group(2))
            if 1 <= month <= 12 and 1 <= day <= 31:
                d = date(today.year, month, day)
                if d < today:
                    d = date(today.year + 1, month, day)
                return d
        except ValueError:
            pass

    # "Month DD" or "Month DDth"
    m = re.search(
        r"\b([a-záéíóúñ]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b", t,
    )
    if m:
        month_name = m.group(1)
        month = _MONTHS.get(month_name)
        if month:
            try:
                day = int(m.group(2))
                d = date(today.year, month, day)
                if d < today:
                    d = date(today.year + 1, month, day)
                return d
            except ValueError:
                pass

    return None


def detect_opt_in_reply(
    text: str,
    today: Optional[date] = None,
) -> tuple[bool, Optional[bool], Optional[date]]:
    """Inspect a user reply for opt-in/decline + an optional date.

    Returns (is_opt_in_response, accepted, parsed_date) where:
        is_opt_in_response is True if the reply looks like a yes OR a no
            to the reminder offer.
        accepted is True for yes-shaped, False for no-shaped, None if
            neither signal is present.
        parsed_date is the extracted date if any (only meaningful when
            accepted is True).
    """
    if not text:
        return (False, None, None)
    norm = text.strip().lower()

    # The whole-message must start with an affirmative/decline keyword.
    # This avoids a passing "yes" inside an unrelated sentence triggering opt-in.
    first_token = re.split(r"[,\s.!?]+", norm, maxsplit=1)[0]

    accepted: Optional[bool] = None
    if first_token in _AFFIRM_EN | _AFFIRM_ES:
        accepted = True
    elif first_token in _DECLINE_EN | _DECLINE_ES:
        accepted = False

    if accepted is None:
        # Also accept "yes please" (two-word affirm)
        for phrase in ("yes please", "yes thanks", "si por favor", "sí por favor",
                       "no thanks", "no gracias"):
            if norm.startswith(phrase):
                accepted = not phrase.startswith("no")
                break

    if accepted is None:
        return (False, None, None)

    parsed_date = _parse_date(text, today=today) if accepted else None
    return (True, accepted, parsed_date)


def record_reminder_if_opt_in(
    thread_id: str,
    user_message: str,
    intake_supervision_is_parole: bool,
    reminder_was_offered: bool,
    today: Optional[date] = None,
) -> Optional[tuple[bool, Optional[date]]]:
    """If conditions are right, parse the reply and write to the store.

    Returns (accepted, date) when the reply was recognized as an opt-in
    response, None otherwise. Caller updates intake state accordingly.
    Never raises.
    """
    if not (intake_supervision_is_parole and reminder_was_offered):
        return None
    is_response, accepted, parsed = detect_opt_in_reply(user_message, today=today)
    if not is_response:
        return None
    if accepted and parsed:
        try:
            get_store().upsert(ParoleReminder(
                thread_id=thread_id, check_in_date=parsed,
            ))
        except Exception:
            logger.exception("failed to persist parole reminder")
    elif not accepted:
        # Explicit decline: opt out any existing reminders for this thread.
        try:
            get_store().opt_out(thread_id)
        except Exception:
            logger.exception("failed to opt out parole reminders")
    return (bool(accepted), parsed)


# ---------------------------------------------------------------------------
# Send loop
# ---------------------------------------------------------------------------


def _resolve_phone(thread_id: str) -> Optional[str]:
    """Resolve thread_id -> phone via the forward map.

    The forward map is `pathways.sessions.phone_map`. When
    PATHWAYS_PHONE_ENCRYPTION_KEY is set on the deploy AND the SMS path
    has seen this thread before, this returns the phone the user
    originally texted from. Otherwise None, and the send loop counts a
    skipped_no_phone.
    """
    try:
        from pathways.sessions.phone_map import resolve
        return resolve(thread_id)
    except Exception:
        return None


def _send_message_body(reminder: ParoleReminder, language: str = "en") -> str:
    if language == "es":
        return (
            "Recordatorio: tienes tu cita de libertad condicional manana. "
            "Llega temprano y trae tu identificacion. - Pathways"
        )
    return (
        "Reminder: your parole check-in is tomorrow. Arrive early and "
        "bring your ID. Reply STOP to opt out. - Pathways"
    )


def run_send_loop(
    today: Optional[date] = None,
    send_fn=None,
    phone_for_thread=None,
) -> dict:
    """Scan for reminders due tomorrow, send, mark.

    Args:
        today: pin date for testability. Defaults to today (UTC).
        send_fn: callable (to_phone, body) -> bool. Defaults to the
            Twilio outbound wrapper. Tests inject a stub.
        phone_for_thread: callable thread_id -> Optional[phone]. Tests
            inject a stub; production wires the forward map.

    Returns a dict summary suitable for the admin endpoint response.
    """
    today = today or datetime.now(timezone.utc).date()
    target = today + timedelta(days=1)

    if send_fn is None:
        from pathways.twilio_client import send_sms as send_fn  # type: ignore

    if phone_for_thread is None:
        phone_for_thread = _resolve_phone

    store = get_store()
    due = store.due_on(target)

    sent = 0
    skipped_no_phone = 0
    failed = 0
    for reminder in due:
        phone = phone_for_thread(reminder.thread_id)
        if not phone:
            skipped_no_phone += 1
            continue
        body = _send_message_body(reminder)
        try:
            ok = send_fn(phone, body)
        except Exception:
            logger.exception("parole reminder send raised")
            failed += 1
            continue
        if ok:
            store.mark_sent(reminder.thread_id, reminder.check_in_date)
            sent += 1
        else:
            failed += 1

    return {
        "target_date": target.isoformat(),
        "due": len(due),
        "sent": sent,
        "skipped_no_phone": skipped_no_phone,
        "failed": failed,
    }
