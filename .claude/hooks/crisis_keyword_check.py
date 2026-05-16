#!/usr/bin/env python3
"""
UserPromptSubmit hook: crisis keyword detection.

Runs before any model invocation on each user prompt. If a crisis keyword is
matched, it injects a system instruction that forces the next turn to route to
the `crisis-response` Skill, bypassing all other Skill routing logic.

Design notes
------------
- This is deliberately keyword-based, not model-based. Crisis detection cannot
  depend on whether the model decides to be careful this turn. The cost of a
  false positive (asking "are you okay?") is small; the cost of a false negative
  in a hook-triggered safety layer is large.
- Keywords are intentionally broad and conservative. The `crisis-response`
  Skill handles graceful exit on false positives.
- The keyword list is split by category so the auditor can later report which
  category fired. Categories are exposed to the model via the injected
  instruction so the right resource is offered.

Input contract (per Claude Code hook spec)
------------------------------------------
JSON via stdin:
    {
      "hook_event_name": "UserPromptSubmit",
      "session_id": "...",
      "prompt": "the user's message",
      ...
    }

Output:
    - stdout: nothing on no-match
    - stdout: JSON `{"continue": true, "systemMessage": "..."}` on match,
              which Claude Code merges into the next turn's context
    - exit code 0 on success, 1 on internal error (does NOT block the turn)

References:
- Claude Code hooks: https://docs.claude.com/en/docs/claude-code/hooks
- Trauma-informed crisis response: SAMHSA TIP 57
"""

from __future__ import annotations

import json
import re
import sys
from typing import Optional

# Curated keyword list. Each tuple: (compiled regex, category).
# Categories map to specific resources in the crisis-response Skill.
#
# Pattern design rules:
# 1. Bias toward false positives over false negatives. The crisis-response
#    Skill includes a graceful-exit script for false positives; a false
#    negative on a real crisis has no recovery path.
# 2. Cover progressive forms of verbs (kill / killing / killed) explicitly.
#    Regex word-boundaries do NOT collapse these for us.
# 3. Cover both contracted and non-contracted negation (don't / do not).
#    Many users typing on basic phones write the non-contracted form.
# 4. Reflexive constructions ("kill myself") gate the suicide category;
#    third-person constructions ("kill him", "kill me" as victim) belong
#    in violence_to_others or domestic_violence.
KEYWORDS = [
    # Suicidality
    (re.compile(
        r"\b("
        r"kill(ing|s|ed)?\s+(myself|my\s*self)|"
        r"end(ing)?\s+(it|my\s+life|things|it\s+all)|"
        r"suicid(e|al)|"
        r"(don'?t|do\s+not|does\s+not|doesn'?t)\s+want\s+to\s+(live|be\s+here|wake\s+up)|"
        r"want(ing)?\s+to\s+die|"
        r"wish\s+(I\s+was|I\s+were|I'?m)\s+dead|"
        r"better\s+off\s+dead|"
        r"no\s+reason\s+to\s+(live|be\s+here)|"
        r"life\s+(is\s+not|isn'?t)\s+worth(\s+living)?"
        r")\b",
        re.I), "suicide"),

    # Self-harm
    (re.compile(r"\b(cut(ting)?\s+myself|self[-\s]?harm|hurt(ing)?\s+myself|"
                r"burn(ing)?\s+myself)\b", re.I),
     "self_harm"),

    # Overdose / acute substance crisis
    (re.compile(r"\b(overdos(e|ing|ed)|OD'?d|OD'?ing|took\s+too\s+much|"
                r"going\s+to\s+overdose|"
                r"can'?t\s+stop\s+using|been\s+using\s+all\s+(day|night)|"
                r"shooting\s+up\s+again)\b", re.I),
     "substance"),

    # Domestic violence in progress
    (re.compile(r"\b(he'?s\s+(hitting|beating|going\s+to\s+kill)|"
                r"she'?s\s+(hitting|beating|going\s+to\s+kill)|"
                r"they'?re\s+(hitting|beating|coming\s+for\s+me)|"
                r"abus(ing|er)\s+me|hide\s+from\s+(him|her|them))\b", re.I),
     "domestic_violence"),

    # Imminent violence toward others (and toward "me" by a named third party)
    (re.compile(r"\b(going\s+to\s+(kill|hurt|shoot|stab)|"
                r"want\s+to\s+(kill|hurt)\s+(him|her|them)|"
                r"have\s+a\s+(gun|knife)\s+and|"
                r"(he|she|they)\s+(is|are|'?s|'?re)\s+going\s+to\s+kill\s+me)\b",
                re.I),
     "violence_to_others"),

    # Sexual violence (recent or in progress)
    (re.compile(r"\b(rap(e|ed|ing)|sexually\s+assault(ed|ing))\b", re.I),
     "sexual_violence"),

    # Acute housing emergency with danger
    # The "tonight" anchor distinguishes acute emergency from generic
    # housing instability (which routes through housing-pathway, not crisis).
    (re.compile(
        r"\b("
        r"sleeping\s+(on\s+the\s+street|outside|in\s+(my\s+|the\s+)?car)\s+tonight|"
        r"nowhere\s+(safe\s+)?(to\s+(sleep|stay|go)\s+)?tonight|"
        r"no(\s+|\s*-?\s*)(where|place)\s+(safe\s+)?(to\s+(sleep|stay|go))?\s*tonight|"
        r"homeless\s+(tonight|right\s+now)|"
        r"on\s+the\s+street\s+tonight|"
        r"freezing\s+(outside|tonight)"
        r")\b",
        re.I), "housing_emergency"),
]


def detect_crisis(prompt: str) -> Optional[str]:
    """Return the first matching crisis category, or None."""
    for pattern, category in KEYWORDS:
        if pattern.search(prompt):
            return category
    return None


def build_system_message(category: str) -> str:
    """Build the system instruction injected on match."""
    return (
        f"CRISIS_HOOK_FIRED: category={category}. "
        f"The user's last message contained language matching a crisis pattern. "
        f"Load the `crisis-response` Skill immediately and follow its protocol. "
        f"Do not route to any other Skill. Do not call any MCP retrieval tools. "
        f"Do not draft a navigation response. Acknowledge the user, offer the "
        f"resource matched to category={category}, and stay present. "
        f"If on second look you assess the keyword match was a false positive, "
        f"the `crisis-response` Skill includes the graceful-exit script."
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0  # No input, no-op
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"crisis_keyword_check: invalid JSON input: {e}", file=sys.stderr)
        return 0  # Do not block the turn on hook errors

    prompt = payload.get("prompt", "")
    if not prompt:
        return 0

    category = detect_crisis(prompt)
    if category is None:
        return 0  # No match, silent pass

    response = {
        "continue": True,
        "systemMessage": build_system_message(category),
        "hookMetadata": {
            "hook": "crisis_keyword_check",
            "category": category,
        },
    }
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
