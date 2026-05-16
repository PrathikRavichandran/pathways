"""Phase 1 tests: stateful slot-filling intake + sessions + idempotency.

These tests cover the new behavior added in Phase 1:

- thread_id derivation hashes + does not leak phone numbers
- slot-filling intake asks for name -> location -> top_need one at a time
- multi-turn invocations against the checkpointer share state
- idempotency dedup prevents double-processing of the same MessageSid
- Twilio signature verifier (skipped path in demo mode + happy path)
- API /sms end-to-end via FastAPI TestClient

The graph in these tests is the checkpointer-enabled compiled app.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Test setup: force demo mode + in-memory checkpointer for hermetic tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _demo_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "test-salt-do-not-use-in-prod")
    monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
    # Reset checkpointer + graph singletons between tests
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    # Wipe in-memory dedup state
    from pathways.sessions import idempotency
    idempotency._seen_sids.clear()


@pytest.fixture
def app():
    """Phase 1 checkpointer-enabled graph."""
    from pathways.graph import build_graph
    return build_graph(use_checkpointer=True)


# ---------------------------------------------------------------------------
# thread_id derivation
# ---------------------------------------------------------------------------


class TestThreadID:
    def test_same_phone_same_thread(self):
        from pathways.sessions.thread import thread_id_for_phone

        t1 = thread_id_for_phone("+17135550100")
        t2 = thread_id_for_phone("+17135550100")
        assert t1 == t2
        assert t1.startswith("ph_")

    def test_normalized_phone_collapses_punctuation(self):
        from pathways.sessions.thread import thread_id_for_phone

        a = thread_id_for_phone("+1 713-555-0100")
        b = thread_id_for_phone("+17135550100")
        c = thread_id_for_phone(" +1-713-555-0100 ")
        assert a == b == c

    def test_different_phones_different_threads(self):
        from pathways.sessions.thread import thread_id_for_phone

        t1 = thread_id_for_phone("+17135550100")
        t2 = thread_id_for_phone("+17135550101")
        assert t1 != t2

    def test_thread_id_is_not_raw_phone(self):
        """The phone number must not appear in the derived thread_id."""
        from pathways.sessions.thread import thread_id_for_phone

        phone = "+17135550100"
        tid = thread_id_for_phone(phone)
        assert phone not in tid
        assert "7135550100" not in tid
        assert "555" not in tid

    def test_different_salt_produces_different_thread(self):
        from pathways.sessions.thread import thread_id_for_phone

        t1 = thread_id_for_phone("+17135550100", salt="salt-a")
        t2 = thread_id_for_phone("+17135550100", salt="salt-b")
        assert t1 != t2

    def test_web_thread_id_distinct_prefix(self):
        from pathways.sessions.thread import thread_id_for_phone, thread_id_for_web

        ph = thread_id_for_phone("+17135550100")
        web = thread_id_for_web("uuid-1234")
        assert ph.startswith("ph_")
        assert web.startswith("web_")
        assert ph != web

    def test_empty_phone_raises(self):
        from pathways.sessions.thread import thread_id_for_phone

        with pytest.raises(ValueError):
            thread_id_for_phone("")
        with pytest.raises(ValueError):
            thread_id_for_phone("   ")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_first_sid_is_new(self):
        from pathways.sessions.idempotency import seen_message_sid

        assert seen_message_sid("SM_test_001") is False

    def test_duplicate_sid_is_seen(self):
        from pathways.sessions.idempotency import seen_message_sid

        assert seen_message_sid("SM_test_002") is False
        # Second call with same sid should report seen
        assert seen_message_sid("SM_test_002") is True

    def test_empty_sid_never_dedupes(self):
        from pathways.sessions.idempotency import seen_message_sid

        # No SID means we can't dedup; return False so the turn proceeds.
        assert seen_message_sid("") is False
        assert seen_message_sid("") is False  # still False; not stored

    def test_distinct_sids_independent(self):
        from pathways.sessions.idempotency import seen_message_sid

        assert seen_message_sid("SM_test_A") is False
        assert seen_message_sid("SM_test_B") is False
        # Each was independent and is now seen
        assert seen_message_sid("SM_test_A") is True
        assert seen_message_sid("SM_test_B") is True


# ---------------------------------------------------------------------------
# Slot-filling pure functions
# ---------------------------------------------------------------------------


class TestSlotFilling:
    def test_empty_profile_needs_name_first(self):
        from pathways.nodes.intake_slots import Slot, next_missing_slot
        from pathways.state import IntakeProfile

        slot = next_missing_slot(IntakeProfile())
        assert slot == Slot.NAME

    def test_name_filled_needs_location(self):
        from pathways.nodes.intake_slots import Slot, next_missing_slot
        from pathways.state import IntakeProfile

        slot = next_missing_slot(IntakeProfile(name="Marcus"))
        assert slot == Slot.LOCATION

    def test_name_and_location_needs_top_need(self):
        from pathways.nodes.intake_slots import Slot, next_missing_slot
        from pathways.state import IntakeProfile

        slot = next_missing_slot(IntakeProfile(name="Marcus", zipcode="77002"))
        assert slot == Slot.TOP_NEED

    def test_all_filled_returns_none(self):
        from pathways.nodes.intake_slots import next_missing_slot
        from pathways.state import IntakeProfile, TopNeed

        slot = next_missing_slot(
            IntakeProfile(name="Marcus", zipcode="77002", top_need=TopNeed.HOUSING)
        )
        assert slot is None

    def test_city_counts_as_location(self):
        from pathways.nodes.intake_slots import Slot, next_missing_slot
        from pathways.state import IntakeProfile

        slot = next_missing_slot(IntakeProfile(name="Marcus", city="Houston"))
        # Either city or zip is enough
        assert slot != Slot.LOCATION

    def test_extract_name_from_bare_reply(self):
        from pathways.nodes.intake_slots import extract_name_from_reply

        assert extract_name_from_reply("Marcus") == "Marcus"
        assert extract_name_from_reply("marcus") == "Marcus"

    def test_extract_name_from_conversational_reply(self):
        from pathways.nodes.intake_slots import extract_name_from_reply

        assert extract_name_from_reply("my name is Marcus") == "Marcus"
        assert extract_name_from_reply("I'm Marcus") == "Marcus"
        assert extract_name_from_reply("I am Marcus") == "Marcus"
        assert extract_name_from_reply("call me Marcus") == "Marcus"
        assert extract_name_from_reply("Marcus Jones") == "Marcus"  # first name only

    def test_extract_name_declines_to_decline(self):
        from pathways.nodes.intake_slots import extract_name_from_reply

        assert extract_name_from_reply("no") is None
        assert extract_name_from_reply("skip") is None
        assert extract_name_from_reply("prefer not to say") is None
        assert extract_name_from_reply("idk") is None

    def test_extract_zip_or_city(self):
        from pathways.nodes.intake_slots import extract_zip_or_city_from_reply

        zip5, city = extract_zip_or_city_from_reply("77002")
        assert zip5 == "77002"

        zip5, city = extract_zip_or_city_from_reply("I'm in Houston")
        assert city == "Houston"
        assert zip5 is None

        zip5, city = extract_zip_or_city_from_reply("Houston 77002")
        assert zip5 == "77002"
        assert city == "Houston"

    def test_prompt_for_slot_is_short_and_includes_question(self):
        from pathways.nodes.intake_slots import Slot, prompt_for_slot
        from pathways.state import IntakeProfile

        profile = IntakeProfile()
        for slot in [Slot.NAME, Slot.LOCATION, Slot.TOP_NEED]:
            prompt = prompt_for_slot(slot, profile)
            assert prompt
            assert "?" in prompt


# ---------------------------------------------------------------------------
# Multi-turn intake against the checkpointer-enabled graph
# ---------------------------------------------------------------------------


def _normalize(state):
    """Coerce graph output into a fully-serialized dict for assertions.

    LangGraph returns a dict with mixed Pydantic models and primitives;
    .get(...) is unsafe on Pydantic instances, so we model_dump everything.
    """
    if hasattr(state, "model_dump"):
        return state.model_dump(mode="json")
    if isinstance(state, dict):
        out = {}
        for k, v in state.items():
            if hasattr(v, "model_dump"):
                out[k] = v.model_dump(mode="json")
            elif isinstance(v, list):
                out[k] = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in v
                ]
            elif hasattr(v, "value"):  # Enum
                out[k] = v.value
            else:
                out[k] = v
        return out
    return state


class TestMultiTurnIntake:
    def test_turn1_asks_for_name(self, app):
        config = {"configurable": {"thread_id": "ph_t1_test"}}
        result = app.invoke(
            {
                "session_id": "ph_t1_test",
                "user_message": "hey",
                "channel": "sms",
            },
            config=config,
        )
        result_dict = _normalize(result)
        assert result_dict.get("final_response")
        # The first turn should ship a slot prompt, not a retrieval reply
        assert "name" in result_dict["final_response"].lower()
        assert result_dict.get("intake_stage") == "collect_name"

    def test_turn1_through_turn4_full_intake(self, app):
        config = {"configurable": {"thread_id": "ph_t2_test"}}

        # Turn 1: greeting -> bot asks for name
        r1 = _normalize(app.invoke(
            {"session_id": "ph_t2_test", "user_message": "hey", "channel": "sms"},
            config=config,
        ))
        assert r1.get("intake_stage") == "collect_name"

        # Turn 2: user gives name -> bot asks for location
        r2 = _normalize(app.invoke(
            {"session_id": "ph_t2_test", "user_message": "Marcus", "channel": "sms"},
            config=config,
        ))
        assert r2["intake"]["name"] == "Marcus"
        assert r2.get("intake_stage") == "collect_location"
        assert "zip" in r2["final_response"].lower() or "city" in r2["final_response"].lower()

        # Turn 3: user gives ZIP -> bot asks for top need
        r3 = _normalize(app.invoke(
            {"session_id": "ph_t2_test", "user_message": "77002", "channel": "sms"},
            config=config,
        ))
        assert r3["intake"]["zipcode"] == "77002"
        assert r3.get("intake_stage") == "collect_need"

        # Turn 4: user gives need -> intake done, retrieval happens, real reply
        r4 = _normalize(app.invoke(
            {
                "session_id": "ph_t2_test",
                "user_message": "I need a place to stay tonight",
                "channel": "sms",
            },
            config=config,
        ))
        assert r4.get("intake_stage") == "done"
        assert r4.get("intake_complete") is True
        # Should have a real final response (not a slot prompt) and at least one retrieval
        assert r4.get("final_response")
        assert len(r4.get("retrievals", [])) >= 1

    def test_separate_threads_do_not_share_state(self, app):
        # Thread A goes through turn 1 (name asked).
        app.invoke(
            {"session_id": "ph_A", "user_message": "hey", "channel": "sms"},
            config={"configurable": {"thread_id": "ph_A"}},
        )
        # Thread B starts fresh -> should also be at "collect_name"
        rd = _normalize(app.invoke(
            {"session_id": "ph_B", "user_message": "hello", "channel": "sms"},
            config={"configurable": {"thread_id": "ph_B"}},
        ))
        # Thread B should NOT have inherited any intake from thread A
        assert rd["intake"]["name"] is None
        assert rd.get("intake_stage") == "collect_name"

    def test_single_turn_with_all_info_does_not_stall(self, app):
        """If the user packs name + location + need into the first message,
        intake should still iterate through the slots gracefully. (The
        heuristic extractor in demo mode does not pull names; this test
        verifies the graph does not crash and asks for the missing slot.)"""
        config = {"configurable": {"thread_id": "ph_packed"}}
        rd = _normalize(app.invoke(
            {
                "session_id": "ph_packed",
                "user_message": "I'm Marcus from 77002 and I need a place to stay tonight",
                "channel": "sms",
            },
            config=config,
        ))
        # Demo extractor catches the zip + need but not the name. So we
        # land at collect_name with a prompt.
        assert rd.get("intake_stage") == "collect_name"
        assert "name" in rd["final_response"].lower()


# ---------------------------------------------------------------------------
# Twilio signature verifier
# ---------------------------------------------------------------------------


class TestTwilioSignature:
    def test_skip_env_returns_true(self):
        os.environ["PATHWAYS_SKIP_TWILIO_SIG"] = "1"
        try:
            from pathways.api.twilio_signature import verify_twilio_signature

            assert verify_twilio_signature(
                "https://example.com/sms", {"Body": "hi", "From": "+1"}, "anything"
            ) is True
        finally:
            del os.environ["PATHWAYS_SKIP_TWILIO_SIG"]

    def test_missing_token_returns_false(self, monkeypatch):
        monkeypatch.delenv("PATHWAYS_SKIP_TWILIO_SIG", raising=False)
        monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
        from pathways.api.twilio_signature import verify_twilio_signature

        assert verify_twilio_signature(
            "https://example.com/sms", {"Body": "hi"}, "sig"
        ) is False

    def test_missing_signature_header_returns_false(self, monkeypatch):
        monkeypatch.delenv("PATHWAYS_SKIP_TWILIO_SIG", raising=False)
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token-do-not-use")
        from pathways.api.twilio_signature import verify_twilio_signature

        assert verify_twilio_signature(
            "https://example.com/sms", {"Body": "hi"}, None
        ) is False

    def test_valid_signature_returns_true(self, monkeypatch):
        """Use Twilio's own RequestValidator to compute a valid signature,
        then verify the wrapper accepts it."""
        monkeypatch.delenv("PATHWAYS_SKIP_TWILIO_SIG", raising=False)
        token = "test-auth-token-1234567890"
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", token)
        from twilio.request_validator import RequestValidator
        from pathways.api.twilio_signature import verify_twilio_signature

        url = "https://example.com/sms"
        params = {"Body": "hello", "From": "+17135550100", "MessageSid": "SM1"}
        sig = RequestValidator(token).compute_signature(url, params)
        assert verify_twilio_signature(url, params, sig) is True


# ---------------------------------------------------------------------------
# /sms endpoint via FastAPI TestClient (in-memory checkpointer)
# ---------------------------------------------------------------------------


class TestSmsEndpoint:
    def test_sms_first_turn_asks_for_name(self, monkeypatch):
        monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
        from fastapi.testclient import TestClient

        from pathways.api.main import api

        client = TestClient(api)
        response = client.post(
            "/sms",
            data={"Body": "hey", "From": "+17135550100", "MessageSid": "SMtest1"},
        )
        assert response.status_code == 200
        assert "name" in response.text.lower()

    def test_sms_duplicate_messagesid_is_idempotent(self, monkeypatch):
        monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
        from fastapi.testclient import TestClient

        from pathways.api.main import api

        client = TestClient(api)
        r1 = client.post(
            "/sms",
            data={"Body": "hey", "From": "+17135550101", "MessageSid": "SMdup1"},
        )
        r2 = client.post(
            "/sms",
            data={"Body": "hey", "From": "+17135550101", "MessageSid": "SMdup1"},
        )
        # Both succeed (200), but the second is a no-op (empty TwiML message)
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert "name" in r1.text.lower()
        # Second response is empty TwiML (no actual message)
        assert "<Message></Message>" in r2.text or "<Message/>" in r2.text

    def test_sms_stop_keyword_opts_out(self, monkeypatch):
        monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
        from fastapi.testclient import TestClient

        from pathways.api.main import api

        client = TestClient(api)
        response = client.post(
            "/sms",
            data={"Body": "STOP", "From": "+17135550102", "MessageSid": "SMstop1"},
        )
        assert response.status_code == 200
        assert "not receive" in response.text.lower() or "opt" in response.text.lower()

    def test_sms_help_keyword_returns_help_text(self, monkeypatch):
        monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
        from fastapi.testclient import TestClient

        from pathways.api.main import api

        client = TestClient(api)
        response = client.post(
            "/sms",
            data={"Body": "HELP", "From": "+17135550103", "MessageSid": "SMhelp1"},
        )
        assert response.status_code == 200
        assert "pathways" in response.text.lower() or "navigator" in response.text.lower()

    def test_sms_without_signature_returns_403_when_not_skipped(self, monkeypatch):
        monkeypatch.delenv("PATHWAYS_SKIP_TWILIO_SIG", raising=False)
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
        from fastapi.testclient import TestClient

        from pathways.api.main import api

        client = TestClient(api)
        response = client.post(
            "/sms",
            data={"Body": "hey", "From": "+17135550104", "MessageSid": "SMns1"},
        )
        assert response.status_code == 403
