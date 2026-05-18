"""Phase 6 tests: opt-in parole reporting reminder.

Covers:
    - Date parser (ISO / MM-DD / MM/DD / Month DD; current year + past
      handling that advances to next year)
    - detect_opt_in_reply: yes/no/neither, with/without date, English+Spanish
    - Draft node appends the offer when supervision=parole and not yet
      offered (single-shot; never re-offers)
    - Intake node captures opt-in reply on the NEXT turn after the offer
    - record_reminder_if_opt_in writes to the store
    - run_send_loop respects "due tomorrow", marks sent, skips no-phone
    - Admin endpoint requires the bearer token, returns the summary
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PATHWAYS_REMINDERS_BACKEND", raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "parole-test-salt")
    from pathways.parole_reminders import reset_store as reset_rem
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    reset_rem()
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    yield
    reset_rem()


# ---------------------------------------------------------------------------
# Date parser
# ---------------------------------------------------------------------------


def test_parse_date_iso():
    from pathways.parole_reminders.service import _parse_date
    assert _parse_date("see you 2026-03-05") == date(2026, 3, 5)


def test_parse_date_mmdd_advances_past_year():
    from pathways.parole_reminders.service import _parse_date
    today = date(2026, 5, 16)
    # 3/5 is in the past for today
    parsed = _parse_date("3/5", today=today)
    assert parsed == date(2027, 3, 5)
    # 8/5 is in the future
    assert _parse_date("8/5", today=today) == date(2026, 8, 5)


def test_parse_date_month_name_english():
    from pathways.parole_reminders.service import _parse_date
    today = date(2026, 1, 10)
    assert _parse_date("yes March 5", today=today) == date(2026, 3, 5)
    assert _parse_date("yes mar 5th", today=today) == date(2026, 3, 5)


def test_parse_date_month_name_spanish():
    from pathways.parole_reminders.service import _parse_date
    today = date(2026, 1, 10)
    assert _parse_date("si marzo 5", today=today) == date(2026, 3, 5)


def test_parse_date_returns_none_for_no_date():
    from pathways.parole_reminders.service import _parse_date
    assert _parse_date("yes please") is None
    assert _parse_date("") is None


# ---------------------------------------------------------------------------
# Opt-in detector
# ---------------------------------------------------------------------------


def test_detect_opt_in_reply_yes_with_date():
    from pathways.parole_reminders.service import detect_opt_in_reply
    is_resp, accepted, parsed = detect_opt_in_reply(
        "YES March 5", today=date(2026, 1, 1),
    )
    assert is_resp is True
    assert accepted is True
    assert parsed == date(2026, 3, 5)


def test_detect_opt_in_reply_spanish_yes_with_date():
    from pathways.parole_reminders.service import detect_opt_in_reply
    is_resp, accepted, parsed = detect_opt_in_reply(
        "si marzo 5", today=date(2026, 1, 1),
    )
    assert (is_resp, accepted, parsed) == (True, True, date(2026, 3, 5))


def test_detect_opt_in_reply_no():
    from pathways.parole_reminders.service import detect_opt_in_reply
    is_resp, accepted, parsed = detect_opt_in_reply("no thanks")
    assert is_resp is True
    assert accepted is False
    assert parsed is None


def test_detect_opt_in_reply_random_message():
    from pathways.parole_reminders.service import detect_opt_in_reply
    is_resp, accepted, _ = detect_opt_in_reply("I need housing too")
    assert is_resp is False
    assert accepted is None


def test_detect_opt_in_reply_yes_no_date_still_recognized():
    """User says yes but doesn't give a date. We still recognize the
    opt-in response (caller will follow up); the parsed_date is None."""
    from pathways.parole_reminders.service import detect_opt_in_reply
    is_resp, accepted, parsed = detect_opt_in_reply("yes please")
    assert (is_resp, accepted, parsed) == (True, True, None)


# ---------------------------------------------------------------------------
# Draft node appends offer when supervision=parole
# ---------------------------------------------------------------------------


def test_draft_appends_parole_offer_when_supervision_is_parole(monkeypatch):
    from pathways.nodes import draft as draft_node
    from pathways.state import (
        IntakeProfile, PathwaysState, SupervisionStatus, TopNeed,
    )

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    state = PathwaysState(
        session_id="t1",
        user_message="I have to report to my PO next week",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
        ),
    )
    out = draft_node.run(state)
    assert "Reply YES" in out["draft_response"]
    # Draft no longer commits the durable flag; that moved to the send
    # node so audit-revision passes don't strip the offer. Verify draft
    # is not setting it here.
    assert "intake" not in out


def test_draft_does_not_reoffer_when_already_offered():
    from pathways.nodes import draft as draft_node
    from pathways.state import (
        IntakeProfile, PathwaysState, SupervisionStatus, TopNeed,
    )

    state = PathwaysState(
        session_id="t1",
        user_message="ok thanks",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            parole_reminder_offered=True,
        ),
    )
    out = draft_node.run(state)
    assert "Reply YES" not in out["draft_response"]
    # When we don't append, we don't return an updated intake either
    assert "intake" not in out


def test_draft_reappends_offer_on_audit_revision():
    """If draft runs twice in one turn (audit soft-block then revision)
    AND the intake.parole_reminder_offered flag has NOT been set yet
    (because draft no longer sets it), the second pass must still append
    the offer. The append is also idempotent so running it twice on a
    draft that already contains the offer leaves the offer untouched."""
    from pathways.nodes import draft as draft_node
    from pathways.state import (
        IntakeProfile, PathwaysState, SupervisionStatus, TopNeed,
    )

    state = PathwaysState(
        session_id="t1",
        user_message="thanks, that helps",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            # offered=False, mirroring the post-fix state mid-turn
        ),
    )
    out_pass_1 = draft_node.run(state)
    assert "Reply YES" in out_pass_1["draft_response"]
    # Simulate a second pass with the same un-committed offered=False
    # but a draft that now has the offer in it (audit revision returns
    # the prior draft unchanged in worst case).
    state2 = state.model_copy(update={"draft_response": out_pass_1["draft_response"]})
    out_pass_2 = draft_node.run(state2)
    # Idempotent: count of marker should still be 1
    assert out_pass_2["draft_response"].count("Reply YES with the date") == 1


def test_send_marks_parole_offered_when_offer_in_final_draft():
    """Send commits the durable parole_reminder_offered flag when the
    offer made it into the final reply."""
    from pathways.nodes import send as send_node
    from pathways.state import (
        IntakeProfile, PathwaysState, SupervisionStatus, TopNeed,
    )

    state = PathwaysState(
        session_id="t1",
        user_message="thanks",
        draft_response=(
            "Here is the help. One more thing: Reply YES with the date "
            "(e.g., YES March 5)."
        ),
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            parole_reminder_offered=False,
        ),
    )
    out = send_node.run(state)
    assert out["final_response"] == state.draft_response
    assert "intake" in out
    assert out["intake"].parole_reminder_offered is True


def test_send_marks_offered_for_spanish_offer_too():
    from pathways.nodes import send as send_node
    from pathways.state import (
        IntakeProfile, PathwaysState, SupervisionStatus, TopNeed,
    )

    state = PathwaysState(
        session_id="t1",
        user_message="gracias",
        draft_response="Hola. Responde SI con la fecha (por ejemplo, SI marzo 5).",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            language="es",
            parole_reminder_offered=False,
        ),
    )
    out = send_node.run(state)
    assert out["intake"].parole_reminder_offered is True


def test_send_does_not_overwrite_intake_when_no_offer_in_draft():
    """Plain draft with no parole offer should not cause send to
    return an intake update at all."""
    from pathways.nodes import send as send_node
    from pathways.state import IntakeProfile, PathwaysState, TopNeed

    state = PathwaysState(
        session_id="t1",
        user_message="hi",
        draft_response="Hello. Here are some shelter options near you.",
        intake=IntakeProfile(top_need=TopNeed.HOUSING),
    )
    out = send_node.run(state)
    assert "intake" not in out


def test_draft_spanish_offer_when_language_is_es():
    from pathways.nodes import draft as draft_node
    from pathways.state import (
        IntakeProfile, PathwaysState, SupervisionStatus, TopNeed,
    )

    state = PathwaysState(
        session_id="t1",
        user_message="necesito ayuda con mi PO",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            language="es",
        ),
    )
    out = draft_node.run(state)
    assert "Responde SI" in out["draft_response"]


# ---------------------------------------------------------------------------
# Intake captures the opt-in on the next turn
# ---------------------------------------------------------------------------


def test_intake_captures_opt_in_writes_to_store():
    from pathways.nodes import intake as intake_node
    from pathways.parole_reminders import get_store
    from pathways.state import (
        IntakeProfile, IntakeStage, PathwaysState, SupervisionStatus,
        TopNeed,
    )

    state = PathwaysState(
        session_id="thread-abc",
        user_message="YES March 5",
        intake=IntakeProfile(
            name="Eval",
            zipcode="77002",
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            parole_reminder_offered=True,
        ),
        intake_complete=True,
        intake_stage=IntakeStage.DONE,
    )
    out = intake_node.run(state)
    assert out["intake"].parole_reminder_opt_in is True
    assert out["intake"].parole_check_in_date is not None

    rows = get_store().all()
    assert len(rows) == 1
    assert rows[0].thread_id == "thread-abc"


def test_intake_decline_opts_out_existing_reminders():
    from pathways.nodes import intake as intake_node
    from pathways.parole_reminders import get_store, record_reminder
    from pathways.state import (
        IntakeProfile, IntakeStage, PathwaysState, SupervisionStatus,
        TopNeed,
    )

    record_reminder("thread-abc", date(2026, 6, 1))
    state = PathwaysState(
        session_id="thread-abc",
        user_message="no thanks",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            parole_reminder_offered=True,
        ),
        intake_complete=True,
        intake_stage=IntakeStage.DONE,
    )
    out = intake_node.run(state)
    assert out["intake"].parole_reminder_opt_in is False
    rows = get_store().all()
    assert all(r.opted_out for r in rows if r.thread_id == "thread-abc")


def test_intake_ignores_non_response_text_after_offer():
    """Random next turn that doesn't look like yes/no should not flip
    parole_reminder_opt_in."""
    from pathways.nodes import intake as intake_node
    from pathways.state import (
        IntakeProfile, IntakeStage, PathwaysState, SupervisionStatus,
        TopNeed,
    )

    state = PathwaysState(
        session_id="thread-abc",
        user_message="What about my driver license?",
        intake=IntakeProfile(
            top_need=TopNeed.PAROLE_REPORTING,
            supervision_status=SupervisionStatus.PAROLE,
            parole_reminder_offered=True,
        ),
        intake_complete=True,
        intake_stage=IntakeStage.DONE,
    )
    out = intake_node.run(state)
    assert out["intake"].parole_reminder_opt_in is None


# ---------------------------------------------------------------------------
# Send loop
# ---------------------------------------------------------------------------


def test_run_send_loop_sends_due_tomorrow_marks_them():
    from pathways.parole_reminders import get_store, record_reminder
    from pathways.parole_reminders.service import run_send_loop

    today = date(2026, 5, 16)
    tomorrow = today + timedelta(days=1)
    record_reminder("thread-a", tomorrow)
    record_reminder("thread-b", today + timedelta(days=7))  # not due

    sent: list = []

    def fake_send(to, body):
        sent.append((to, body))
        return True

    def fake_phone(tid):
        return f"+1713555{tid[-4:]}"

    summary = run_send_loop(today=today, send_fn=fake_send,
                            phone_for_thread=fake_phone)
    assert summary["due"] == 1
    assert summary["sent"] == 1
    assert len(sent) == 1
    assert "Reminder" in sent[0][1]

    # Re-running same day does NOT double-send (sent_at is set)
    second = run_send_loop(today=today, send_fn=fake_send,
                           phone_for_thread=fake_phone)
    assert second["due"] == 0
    assert second["sent"] == 0


def test_run_send_loop_skips_when_no_phone():
    from pathways.parole_reminders import record_reminder
    from pathways.parole_reminders.service import run_send_loop

    today = date(2026, 5, 16)
    record_reminder("thread-no-phone", today + timedelta(days=1))

    summary = run_send_loop(today=today,
                            send_fn=lambda t, b: True,
                            phone_for_thread=lambda tid: None)
    assert summary["due"] == 1
    assert summary["sent"] == 0
    assert summary["skipped_no_phone"] == 1


# ---------------------------------------------------------------------------
# Admin endpoint auth
# ---------------------------------------------------------------------------


def test_admin_run_parole_reminders_requires_token():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    client = TestClient(api)
    r = client.post("/admin/run-parole-reminders")
    assert r.status_code == 401


def test_admin_run_parole_reminders_with_valid_token(monkeypatch):
    monkeypatch.setenv("PATHWAYS_ADMIN_TOKEN", "secret-cron-token")
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    client = TestClient(api)
    r = client.post(
        "/admin/run-parole-reminders",
        headers={"authorization": "Bearer secret-cron-token"},
    )
    assert r.status_code == 200
    body = r.json()
    # Phase 6 final ship: admin endpoint drains BOTH parole reminders
    # and the writeback queue, returns a dict keyed by source.
    assert "parole_reminders" in body
    assert "writeback" in body
    assert "target_date" in body["parole_reminders"]
    assert "sent" in body["parole_reminders"]
