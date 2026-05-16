"""Load scenarios from evals/scenarios/*.json.

Each file holds a list of scenario objects. The scenario `id` is unique
across files and used as the LangGraph thread_id so each scenario gets
isolated checkpointer state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


@dataclass
class Scenario:
    id: str
    category: str
    input: dict[str, Any]
    expects: dict[str, Any] = field(default_factory=dict)
    expects_full_mode: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Scenario":
        return cls(
            id=d["id"],
            category=d["category"],
            input=d["input"],
            expects=d.get("expects", {}) or {},
            expects_full_mode=d.get("expects_full_mode", {}) or {},
            notes=d.get("notes", "") or "",
        )


def load_all(
    scenarios_dir: Path | None = None,
    category: str | None = None,
) -> list[Scenario]:
    """Load every scenario in scenarios_dir, optionally filtered by category."""
    sdir = scenarios_dir or SCENARIOS_DIR
    if not sdir.exists():
        return []
    out: list[Scenario] = []
    for f in sorted(sdir.glob("*.json")):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValueError(
                f"{f}: scenario files must contain a JSON list of scenarios"
            )
        for entry in data:
            scenario = Scenario.from_dict(entry)
            if category and scenario.category != category:
                continue
            out.append(scenario)
    # Sanity check: ids must be unique across files
    seen = set()
    for s in out:
        if s.id in seen:
            raise ValueError(f"duplicate scenario id: {s.id}")
        seen.add(s.id)
    return out
