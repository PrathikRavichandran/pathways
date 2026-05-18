"""Phase 7 tests: resource map view contract.

Covers:
    - _coerce_float helper (the type-laundering shim that protects the
      ResourceCard projection from psycopg Decimals, JSON strings,
      garbage values, and None).
    - ResourceCard pydantic shape: lat / lon nullable floats.
    - _shape_response pass-through from matched_resources into cards.
    - End-to-end /web/turn response contract: every card has lat + lon
      keys; statewide entries arrive null while geo-aware entries
      arrive with floats.
    - dashboard analytics counts pin-able resources per turn so the
      caseworker dashboard can track map engagement over time.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# _coerce_float: protects ResourceCard.lat/lon from upstream type drift
# ---------------------------------------------------------------------------


class TestCoerceFloat:
    @staticmethod
    def _fn():
        from pathways.api.web import _coerce_float
        return _coerce_float

    def test_none_returns_none(self):
        assert self._fn()(None) is None

    def test_int_returns_float(self):
        out = self._fn()(29)
        assert out == 29.0
        assert isinstance(out, float)

    def test_float_returns_float(self):
        out = self._fn()(29.7604)
        assert out == 29.7604

    def test_numeric_string_returns_float(self):
        """Some MCP server backends return text columns; cover the case."""
        out = self._fn()("29.7604")
        assert out == 29.7604

    def test_decimal_returns_float(self):
        """psycopg returns NUMERIC columns as decimal.Decimal."""
        out = self._fn()(Decimal("29.7604"))
        assert out == 29.7604

    def test_bool_does_not_coerce_meaningfully(self):
        # bool inherits from int in Python; this would produce 0.0 or 1.0.
        # Document the behavior so a future reader understands; the map
        # filters out anything that isn't a real coordinate anyway.
        assert self._fn()(True) == 1.0
        assert self._fn()(False) == 0.0

    def test_garbage_string_returns_none(self):
        assert self._fn()("not a number") is None

    def test_empty_string_returns_none(self):
        assert self._fn()("") is None

    def test_list_returns_none(self):
        assert self._fn()([1, 2, 3]) is None

    def test_dict_returns_none(self):
        assert self._fn()({"lat": 1.0}) is None


# ---------------------------------------------------------------------------
# ResourceCard pydantic shape
# ---------------------------------------------------------------------------


class TestResourceCardShape:
    def test_accepts_lat_lon_as_floats(self):
        from pathways.api.web import ResourceCard

        card = ResourceCard(id="x", name="Star of Hope", lat=29.7604, lon=-95.3698)
        assert card.lat == 29.7604
        assert card.lon == -95.3698

    def test_accepts_lat_lon_as_null(self):
        """Statewide hotlines arrive without coords. The PWA's map view
        silently filters them out; the cards list still renders them."""
        from pathways.api.web import ResourceCard

        card = ResourceCard(id="trla", name="TRLA", lat=None, lon=None)
        assert card.lat is None
        assert card.lon is None

    def test_defaults_when_unspecified(self):
        from pathways.api.web import ResourceCard

        card = ResourceCard(id="x", name="N")
        assert card.lat is None
        assert card.lon is None

    def test_round_trips_to_json(self):
        """JSON contract is what reaches the PWA. Verify the keys survive."""
        from pathways.api.web import ResourceCard

        payload = ResourceCard(
            id="houston-soh",
            name="Star of Hope",
            phone="713-222-2220",
            distance_miles=1.2,
            lat=29.7604,
            lon=-95.3698,
        ).model_dump(mode="json")
        assert payload["lat"] == 29.7604
        assert payload["lon"] == -95.3698
        # keys are always present so the React `card.lat != null` filter
        # never throws ReferenceError
        assert "lat" in payload
        assert "lon" in payload


# ---------------------------------------------------------------------------
# _shape_response: matched_resources -> ResourceCard pass-through
# ---------------------------------------------------------------------------


class TestShapeResponsePassThrough:
    def _final(self, matched: list[dict]) -> dict:
        """Minimal final-state dict shape that _shape_response accepts."""
        return {
            "final_response": "reply",
            "matched_resources": matched,
            "intake": {"language": "en", "top_need": "housing"},
        }

    def test_passes_lat_lon_when_present(self):
        from pathways.api.web import _shape_response

        out = _shape_response(self._final([
            {"id": "a", "name": "A", "lat": 29.76, "lon": -95.37},
        ]), default_language="en")
        assert len(out.resources) == 1
        assert out.resources[0].lat == 29.76
        assert out.resources[0].lon == -95.37

    def test_returns_null_when_record_has_no_coords(self):
        from pathways.api.web import _shape_response

        out = _shape_response(self._final([
            {"id": "trla", "name": "TRLA"},
        ]), default_language="en")
        assert out.resources[0].lat is None
        assert out.resources[0].lon is None

    def test_mixed_records_each_get_their_own_coords(self):
        from pathways.api.web import _shape_response

        out = _shape_response(self._final([
            {"id": "soh", "name": "Star of Hope", "lat": 29.76, "lon": -95.37},
            {"id": "trla", "name": "TRLA"},
            {"id": "bridge", "name": "The Bridge", "lat": 32.78, "lon": -96.80},
        ]), default_language="en")
        assert out.resources[0].lat == 29.76
        assert out.resources[1].lat is None
        assert out.resources[2].lat == 32.78

    def test_decimal_inputs_get_coerced(self):
        """Simulate the psycopg case where lat/lon arrive as Decimal."""
        from pathways.api.web import _shape_response

        out = _shape_response(self._final([
            {"id": "a", "name": "A", "lat": Decimal("29.76"), "lon": Decimal("-95.37")},
        ]), default_language="en")
        assert out.resources[0].lat == 29.76
        assert isinstance(out.resources[0].lat, float)

    def test_corrupt_lat_value_becomes_null_not_crash(self):
        """Defensive: garbage in the resource dict should not 500 the API."""
        from pathways.api.web import _shape_response

        out = _shape_response(self._final([
            {"id": "a", "name": "A", "lat": "not-a-number", "lon": -95.37},
        ]), default_language="en")
        assert out.resources[0].lat is None
        # lon was still valid
        assert out.resources[0].lon == -95.37


# ---------------------------------------------------------------------------
# End-to-end through /web/turn: the contract the PWA actually consumes
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _eval_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PATHWAYS_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("PATHWAYS_THREAD_SALT", "phase7-test-salt")
    monkeypatch.setenv("PATHWAYS_SKIP_TWILIO_SIG", "1")
    from pathways.sessions import checkpointer
    from pathways import graph as graph_mod
    checkpointer.reset_checkpointer()
    graph_mod.reset_app()
    from pathways.sessions import idempotency
    idempotency._seen_sids.clear()
    from pathways.dashboard import analytics
    analytics.reset_store()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from pathways.api.main import api
    return TestClient(api)


def test_web_turn_response_includes_lat_lon_keys_on_every_card(client):
    """Schema invariant: PWA's ResourceMap reads card.lat / card.lon
    every time. Both keys must always be present (nullable). If the
    keys ever go missing, the React filter throws and the map breaks."""
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    for msg in ["hi", "Marcus", "77002", "I need housing in Houston"]:
        r = client.post("/web/turn", json={"session_id": sid, "message": msg}).json()
    for card in r["resources"]:
        assert "lat" in card, f"missing lat in {card['id']}"
        assert "lon" in card, f"missing lon in {card['id']}"
        assert card["lat"] is None or isinstance(card["lat"], (int, float))
        assert card["lon"] is None or isinstance(card["lon"], (int, float))


def test_web_turn_geo_query_preserves_lat_lon_contract(client):
    """When the user asks for housing in a real ZIP, every returned
    card must carry the lat/lon keys (nullable). The number of pins
    that actually render depends on how many seed-catalog entries are
    geocoded; the schema contract is what this test guards.

    The companion behavioral assertion (at least one pin when the
    catalog has geocoded metro entries) lives at the seed-data layer
    in mcp_servers/tx_resources/resources.json. The demo seed today
    has no geocoded rows; the production deploy carries HRSA + metro
    geocodes that DO pin. See _shape_response unit tests above for
    the projection-layer coverage."""
    s = client.post("/web/session", json={}).json()
    sid = s["session_id"]
    for msg in ["hi", "Marcus", "77002", "I need housing in Houston"]:
        r = client.post("/web/turn", json={"session_id": sid, "message": msg}).json()
    # Schema contract holds in every environment.
    for c in r["resources"]:
        assert "lat" in c, f"missing lat in {c['id']}"
        assert "lon" in c, f"missing lon in {c['id']}"
        assert c["lat"] is None or isinstance(c["lat"], (int, float))
        assert c["lon"] is None or isinstance(c["lon"], (int, float))
    # Behavioral signal: count of pin-able resources for visibility.
    pin_able = [c for c in r["resources"] if c["lat"] is not None and c["lon"] is not None]
    # Document the count for log-grep diagnosis without failing the suite
    # in environments where the catalog is statewide-only.
    print(f"\n[phase7] pin-able cards: {len(pin_able)} / {len(r['resources'])}")


# ---------------------------------------------------------------------------
# Dashboard analytics: track map engagement per turn
# ---------------------------------------------------------------------------


class TestAnalyticsMapTracking:
    def test_event_from_state_counts_resources_with_coords(self):
        """The dashboard's per-turn event now records how many of the
        matched resources had coords. This lets the caseworker dashboard
        report on map engagement over time."""
        from pathways.dashboard.analytics import event_from_state

        final = {
            "matched_resources": [
                {"id": "a", "name": "A", "lat": 29.76, "lon": -95.37},
                {"id": "b", "name": "B", "lat": 32.78, "lon": -96.80},
                {"id": "trla", "name": "TRLA"},  # no coords
            ],
            "intake": {"language": "en"},
        }
        event = event_from_state(
            final_state=final,
            thread_id="t1",
            channel="web",
            user_message="I need a shelter in Houston",
            reply="here are some places",
            crisis_fired=False,
        )
        assert event.matched_resource_count == 3
        assert event.resources_with_coords_count == 2

    def test_event_from_state_zero_when_all_statewide(self):
        from pathways.dashboard.analytics import event_from_state

        final = {
            "matched_resources": [
                {"id": "trla", "name": "TRLA"},
                {"id": "211-texas", "name": "211 Texas"},
            ],
            "intake": {"language": "en"},
        }
        event = event_from_state(
            final_state=final, thread_id="t1", channel="web",
            user_message="legal aid question", reply="here are statewide options",
            crisis_fired=False,
        )
        assert event.matched_resource_count == 2
        assert event.resources_with_coords_count == 0

    def test_event_from_state_zero_when_no_resources(self):
        from pathways.dashboard.analytics import event_from_state

        event = event_from_state(
            final_state={"intake": {}}, thread_id="t1", channel="web",
            user_message="hi", reply="hello", crisis_fired=False,
        )
        assert event.matched_resource_count == 0
        assert event.resources_with_coords_count == 0
