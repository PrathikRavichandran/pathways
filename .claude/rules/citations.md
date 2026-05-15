# Citation Formatting Rules

## Inline citation format

When citing a statute or regulation inline, use the format the corpus entry provides:

> "Texas Occupations Code § 53.021 allows a licensing authority to deny a license if..."

Hyperlink the citation to its URL when present in the corpus entry:

> "[Texas Occupations Code § 53.021](https://statutes.capitol.texas.gov/Docs/OC/htm/OC.53.htm#53.021) allows a licensing authority to deny a license if..."

Never invent a section number. If the corpus doesn't have a citation for a claim, do not make a claim.

## When multiple citations apply

If two corpus entries are relevant to one claim, cite both. Comma-separated is fine:

> "Federal public housing rules require denial only in two specific cases ([24 CFR § 960.204](https://www.ecfr.gov/...), with HUD guidance in [PIH-2015-19](https://www.hud.gov/...))."

## Citation IDs vs human citations

Internally (in tool calls and structured exchanges between sub-agents), use the corpus `id` (e.g., `tx-occ-53-021`). User-facing prose uses the human-readable `citation` field.

## When the corpus disagrees with itself

Rare but possible — two entries may speak to the same situation from different angles. Present both and let the human navigator or legal aid resolve. Do not silently pick one.

## When the user asks for "the law"

Users sometimes ask "what's the law on X?" Treat this as a request for the citation plus a plain-language summary, not as a request for statutory text reproduction. We do not paste long statutory passages into responses — short paraphrase plus citation plus link to the full text is the pattern.
