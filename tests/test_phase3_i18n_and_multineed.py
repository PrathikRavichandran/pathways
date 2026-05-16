"""Phase 3 tests: Spanish support + multi-need routing.

Covers:
- pathways/i18n/detect.py language detection
- pathways/i18n/responses.py bilingual string table parity
- Spanish patterns in .claude/hooks/crisis_keyword_check.py
- Multi-need heuristic extraction in pathways/nodes/intake.py
- Multi-need iteration in pathways/nodes/match.py (no duplicate orgs)
- Bilingual template draft in pathways/nodes/draft.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


HOOK_CRISIS = REPO_ROOT / ".claude" / "hooks" / "crisis_keyword_check.py"


def _run_hook(payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(HOOK_CRISIS)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if not proc.stdout.strip():
        return {}
    return json.loads(proc.stdout.strip().split("\n")[-1])


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


class TestLanguageDetection:
    @pytest.mark.parametrize("text", [
        "Hi, I need help finding housing in Houston",
        "Just got out yesterday and need a place to sleep",
        "Can I vote in Texas if I'm on parole?",
        "I need a job that will hire me with my record",
        "thanks",
        "",
    ])
    def test_english_messages_stay_en(self, text):
        from pathways.i18n.detect import detect_language
        assert detect_language(text) == "en", f"flagged ES on: {text!r}"

    @pytest.mark.parametrize("text", [
        "Hola, necesito ayuda con vivienda",
        "Salí ayer y no tengo donde dormir",
        "Necesito trabajo, tengo antecedentes",
        "Soy de Houston y necesito comida",
        "Quiero ayuda con identificación",
        "español",
    ])
    def test_spanish_messages_detected_as_es(self, text):
        from pathways.i18n.detect import detect_language
        assert detect_language(text) == "es", f"missed ES on: {text!r}"

    def test_single_spanish_word_in_english_message_stays_en(self):
        """Trauma-informed rule: do not infer language from a single word."""
        from pathways.i18n.detect import detect_language
        # "hola" alone in an English context should NOT flip to Spanish.
        assert detect_language("ok hola, I need help with housing") == "en"


# ---------------------------------------------------------------------------
# Bilingual response table parity
# ---------------------------------------------------------------------------


class TestResponseTableParity:
    def test_every_key_has_both_languages(self):
        from pathways.i18n.responses import _TABLE
        for key, entry in _TABLE.items():
            assert "en" in entry, f"missing EN for key {key!r}"
            assert "es" in entry, f"missing ES for key {key!r}"
            assert entry["en"].strip(), f"empty EN string for key {key!r}"
            assert entry["es"].strip(), f"empty ES string for key {key!r}"

    def test_bilingual_helper_returns_correct_language(self):
        from pathways.i18n.responses import bilingual
        en = bilingual("tcpa_stop_ack", "en")
        es = bilingual("tcpa_stop_ack", "es")
        assert "further messages" in en.lower()
        assert "no recibirá" in es.lower()
        assert en != es

    def test_unknown_key_returns_empty_not_raise(self):
        from pathways.i18n.responses import bilingual
        assert bilingual("does-not-exist", "en") == ""

    def test_unknown_language_falls_back_to_english(self):
        from pathways.i18n.responses import bilingual
        # Pass an invalid lang; should not crash, should fall back.
        assert bilingual("tcpa_help", "fr") == bilingual("tcpa_help", "en")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spanish crisis hook patterns (subprocess test, real hook execution)
# ---------------------------------------------------------------------------


class TestSpanishCrisisPatterns:
    @pytest.mark.parametrize("prompt,expected_category", [
        ("me quiero matar", "suicide"),
        ("quiero morir", "suicide"),
        ("estoy pensando en suicidarme", "suicide"),
        ("voy a acabar con todo", "suicide"),
        ("ya no aguanto vivir", "suicide"),
        ("me corte anoche", "self_harm"),
        ("quiero hacerme daño", "self_harm"),
        ("no tengo donde dormir esta noche", "housing_emergency"),
        ("durmiendo en mi carro esta noche", "housing_emergency"),
        ("me esta pegando ahora", "domestic_violence"),
        ("llevo toda la noche drogandome", "substance"),
    ])
    def test_spanish_patterns_fire(self, prompt, expected_category):
        out = _run_hook({"prompt": prompt})
        assert out.get("continue") is True, f"hook missed Spanish prompt: {prompt!r}"
        assert out["hookMetadata"]["category"] == expected_category

    @pytest.mark.parametrize("prompt", [
        "Salí de la carcel ayer",        # release statement, not crisis
        "Quiero un trabajo",              # job request, not "want to die"
        "Necesito ayuda con vivienda",    # housing request, not emergency
        "Hola, como estas",               # greeting
    ])
    def test_spanish_false_positive_guards(self, prompt):
        out = _run_hook({"prompt": prompt})
        # Either no match (empty out) or some other non-crisis category.
        assert out == {} or out.get("continue") is not True


# ---------------------------------------------------------------------------
# Multi-need heuristic extraction
# ---------------------------------------------------------------------------


class TestMultiNeedExtraction:
    def test_single_need_returns_one(self):
        from pathways.nodes.intake import _heuristic_extract
        out = _heuristic_extract("I need a place to stay")
        assert out["top_need"] == "housing"
        assert out["secondary_needs"] == []

    def test_two_needs_returns_both(self):
        from pathways.nodes.intake import _heuristic_extract
        out = _heuristic_extract("I need food and a job")
        # 'food' -> benefits; 'job' -> employment
        assert "benefits" in [out["top_need"]] + out["secondary_needs"]
        assert "employment" in [out["top_need"]] + out["secondary_needs"]

    def test_three_needs_returns_all(self):
        from pathways.nodes.intake import _heuristic_extract
        out = _heuristic_extract(
            "I need housing, food, and to get my driver license back"
        )
        all_needs = [out["top_need"]] + out["secondary_needs"]
        assert "housing" in all_needs
        assert "benefits" in all_needs
        assert "id_documents" in all_needs

    def test_spanish_multi_need(self):
        from pathways.nodes.intake import _heuristic_extract
        out = _heuristic_extract("Necesito comida y trabajo")
        all_needs = [out["top_need"]] + out["secondary_needs"]
        assert "benefits" in all_needs
        assert "employment" in all_needs


# ---------------------------------------------------------------------------
# Multi-need match iteration (no duplicate orgs across needs)
# ---------------------------------------------------------------------------


class TestMultiNeedMatchIteration:
    @pytest.fixture(autouse=True)
    def _demo_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("TX_RESOURCES_BACKEND", "file")

    def test_multi_need_state_runs_through_graph(self):
        from pathways.graph import build_graph
        from pathways.state import (
            CrisisSignal, IntakeProfile, IntakeStage, PathwaysState, TopNeed,
        )

        app = build_graph(use_checkpointer=False)
        state = PathwaysState(
            session_id="multi-need-test",
            user_message="I need food and a place to stay in Houston",
            crisis=CrisisSignal(fired=False),
            intake=IntakeProfile(
                name="Test",
                zipcode="77002",
                city="Houston",
                region="Greater Houston",
                top_need=TopNeed.HOUSING,
                secondary_needs=[TopNeed.BENEFITS],
            ),
            intake_complete=True,
            intake_stage=IntakeStage.DONE,
        )
        result = app.invoke(state)
        out = result if isinstance(result, dict) else result.model_dump()
        matched = out.get("matched_resources", [])
        # Must have at least one resource per need OR the 211 safety net
        assert matched, "Expected at least one matched resource for multi-need state"

        # No duplicate IDs in the matched list
        ids = [m.get("id") for m in matched if m.get("id")]
        assert len(ids) == len(set(ids)), f"Duplicate org ids surfaced: {ids}"


# ---------------------------------------------------------------------------
# Bilingual template draft
# ---------------------------------------------------------------------------


class TestBilingualDraft:
    @pytest.fixture(autouse=True)
    def _demo_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def test_english_draft_for_en_profile(self):
        from pathways.nodes.draft import _template_draft
        from pathways.state import (
            CrisisSignal, IntakeProfile, PathwaysState, TopNeed,
        )

        state = PathwaysState(
            session_id="draft-en-test",
            user_message="I need a place to stay",
            crisis=CrisisSignal(fired=False),
            intake=IntakeProfile(
                name="Marcus", language="en", top_need=TopNeed.HOUSING,
            ),
        )
        draft = _template_draft(state)
        assert draft
        # Spanish-only phrasing must not leak into an English reply
        assert "te escucho" not in draft.lower()
        assert "necesito" not in draft.lower()

    def test_spanish_draft_for_es_profile(self):
        from pathways.nodes.draft import _template_draft
        from pathways.state import (
            CrisisSignal, IntakeProfile, PathwaysState, TopNeed,
        )

        state = PathwaysState(
            session_id="draft-es-test",
            user_message="Necesito un lugar para dormir",
            crisis=CrisisSignal(fired=False),
            intake=IntakeProfile(
                name="Marcos", language="es", top_need=TopNeed.HOUSING,
            ),
        )
        draft = _template_draft(state)
        assert draft
        # Spanish reply should not be the English template
        assert "i hear you" not in draft.lower()
        # Must include the user's name when present
        assert "Marcos" in draft

    def test_multi_need_draft_mentions_multiple_needs(self):
        from pathways.nodes.draft import _template_draft
        from pathways.state import (
            CrisisSignal, IntakeProfile, PathwaysState, TopNeed,
        )

        state = PathwaysState(
            session_id="draft-multi-test",
            user_message="I need food and a job",
            crisis=CrisisSignal(fired=False),
            intake=IntakeProfile(
                language="en",
                top_need=TopNeed.BENEFITS,
                secondary_needs=[TopNeed.EMPLOYMENT],
            ),
        )
        draft = _template_draft(state)
        # Should mention both needs in some form
        assert (
            "snap" in draft.lower() or "benefits" in draft.lower()
        )
        assert "work" in draft.lower() or "job" in draft.lower() or "employment" in draft.lower()


# ---------------------------------------------------------------------------
# Multi-turn intake with Spanish first-touch
# ---------------------------------------------------------------------------


class TestSpanishMultiTurnIntake:
    @pytest.fixture(autouse=True)
    def _demo_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
        monkeypatch.setenv("PATHWAYS_THREAD_SALT", "phase3-test-salt")
        monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
        from pathways.sessions import checkpointer
        from pathways import graph as graph_mod
        checkpointer.reset_checkpointer()
        graph_mod.reset_app()
        from pathways.sessions import idempotency
        idempotency._seen_sids.clear()

    def test_spanish_first_message_gets_spanish_prompt(self):
        """A Spanish first message should produce a Spanish slot prompt."""
        from pathways.graph import build_graph

        app = build_graph(use_checkpointer=True)
        config = {"configurable": {"thread_id": "ph_es_test_1"}}
        result = app.invoke(
            {
                "session_id": "ph_es_test_1",
                "user_message": "Hola, necesito ayuda con vivienda",
                "channel": "sms",
            },
            config=config,
        )
        result_dict = result if isinstance(result, dict) else result.model_dump()
        intake = result_dict.get("intake")
        lang = (
            intake.language if hasattr(intake, "language")
            else (intake or {}).get("language")
        )
        assert lang == "es", f"language not detected as es; got {lang}"

        prompt = result_dict.get("final_response", "")
        # Spanish slot prompt should contain "nombre" or similar
        assert "nombre" in prompt.lower() or "llamar" in prompt.lower(), (
            f"Expected Spanish name prompt; got: {prompt!r}"
        )
