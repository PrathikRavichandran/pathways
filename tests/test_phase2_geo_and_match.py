"""Phase 2 tests: geo helpers, nearby ranking, match-node wire-up."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------


class TestZipToCoords:
    def test_known_tx_metros_resolve(self):
        from pathways.geo import zip_to_coords

        for z in ("77002", "75201", "78701", "78201", "79901", "78520", "79401", "75701"):
            coords = zip_to_coords(z)
            assert coords is not None, f"ZIP {z} did not resolve"
            lat, lon = coords
            # Texas bbox roughly: 25.8-36.5 lat, -106.6 to -93.5 lon
            assert 25 < lat < 37, f"{z} lat out of TX range: {lat}"
            assert -107 < lon < -93, f"{z} lon out of TX range: {lon}"

    def test_zip_plus_4_form(self):
        from pathways.geo import zip_to_coords

        a = zip_to_coords("77002")
        b = zip_to_coords("77002-1234")
        assert a == b

    def test_unknown_zip(self):
        from pathways.geo import zip_to_coords

        assert zip_to_coords("90210") is None  # CA, not in TX table
        assert zip_to_coords("00000") is None
        assert zip_to_coords("") is None
        assert zip_to_coords("not-a-zip") is None


class TestCountyAndWorkforceRegion:
    @pytest.mark.parametrize("zip5,expected_county,expected_region", [
        ("77002", "Harris", "Gulf Coast"),
        ("75201", "Dallas", "Dallas"),
        ("78701", "Travis", "Capital Area"),
        ("78201", "Bexar", "Alamo"),
        ("79901", "El Paso", "Borderplex"),
        ("78520", "Cameron", "Cameron County"),
        ("79401", "Lubbock", "South Plains"),
        ("75701", "Smith", "East Texas"),
        ("76101", "Tarrant", "Tarrant County"),
        ("75901", "Angelina", "Deep East Texas"),
    ])
    def test_zip_to_county_and_region(self, zip5, expected_county, expected_region):
        from pathways.geo import county_for_zip, workforce_region_for_zip

        assert county_for_zip(zip5) == expected_county
        assert workforce_region_for_zip(zip5) == expected_region


class TestHaversine:
    def test_zero_distance(self):
        from pathways.geo import haversine_miles

        assert haversine_miles(29.76, -95.37, 29.76, -95.37) == 0.0

    def test_houston_to_dallas(self):
        from pathways.geo import haversine_miles

        # Houston to Dallas is ~225 mi great-circle.
        d = haversine_miles(29.7604, -95.3698, 32.7767, -96.7970)
        assert 220 < d < 245, f"Houston-Dallas distance off: {d}"

    def test_symmetry(self):
        from pathways.geo import haversine_miles

        a_to_b = haversine_miles(29.76, -95.37, 32.78, -96.80)
        b_to_a = haversine_miles(32.78, -96.80, 29.76, -95.37)
        assert abs(a_to_b - b_to_a) < 0.001


# ---------------------------------------------------------------------------
# find_resources_nearby (file backend, seed data)
# ---------------------------------------------------------------------------


class TestFindResourcesNearby:
    def _import_server(self):
        # Force the file backend and reload so a previous test's env doesn't leak.
        import importlib.util, os
        os.environ["TX_RESOURCES_BACKEND"] = "file"
        here = REPO_ROOT / "mcp_servers" / "tx_resources" / "server.py"
        spec = importlib.util.spec_from_file_location("tx_resources_server_test", here)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_unknown_zip_returns_error_with_fallback(self):
        server = self._import_server()
        out = server.find_resources_nearby(near_zip="90210", top_k=3)
        assert "error" in out
        assert out["ranked"] == []
        # Fallback should always include statewide hotlines
        assert len(out["fallback"]) >= 1

    def test_houston_zip_returns_houston_orgs_or_fallback(self):
        server = self._import_server()
        out = server.find_resources_nearby(near_zip="77002", top_k=5)
        assert "user_coords" in out
        # In the seed JSON, only lsla-houston and trla-statewide carry lat/lon
        # (until ingesters run against the Postgres backend). Confirm the
        # nearby ranker returns something OR provides a fallback.
        total = len(out["ranked"]) + len(out["fallback"])
        assert total >= 1

    def test_houston_zip_orders_by_distance(self):
        server = self._import_server()
        out = server.find_resources_nearby(near_zip="77002", top_k=10)
        ranked = out["ranked"]
        if len(ranked) >= 2:
            for i in range(len(ranked) - 1):
                assert ranked[i]["distance_miles"] <= ranked[i + 1]["distance_miles"]


# ---------------------------------------------------------------------------
# match node + slot-fill + nearby integration (stateless graph)
# ---------------------------------------------------------------------------


class TestMatchNodeNearbyWireUp:
    @pytest.fixture(autouse=True)
    def _demo_env(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("TX_RESOURCES_BACKEND", "file")

    def test_zip_aware_match_runs_without_error(self, monkeypatch):
        """The match node uses find_resources_nearby when intake.zipcode is set."""
        from pathways.graph import build_graph
        from pathways.state import (
            CrisisSignal, IntakeProfile, IntakeStage, PathwaysState, TopNeed,
        )

        app = build_graph(use_checkpointer=False)
        state = PathwaysState(
            session_id="match-zip-test",
            user_message="I need a place to stay tonight in Houston",
            crisis=CrisisSignal(fired=False),
            intake=IntakeProfile(
                name="Test",
                zipcode="77002",
                city="Houston",
                region="Greater Houston",
                top_need=TopNeed.HOUSING,
            ),
            intake_complete=True,
            intake_stage=IntakeStage.DONE,
        )
        result = app.invoke(state)
        # Should produce at least one matched resource (211 fallback at minimum)
        out = result if isinstance(result, dict) else result.model_dump()
        assert out.get("matched_resources"), \
            "match node should produce at least the 211 fallback"
