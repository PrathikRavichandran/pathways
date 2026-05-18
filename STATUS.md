# Pathways · Current state snapshot

One-page "what's running, how to verify it, and what's next." For
recruiters, partners, and future-me. The deep build narrative lives in
[`docs/JOURNAL.md`](docs/JOURNAL.md); the architecture deep-dive lives
in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the deferred items
with blockers live in [`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md).
This file is the snapshot.

## Live URLs

| Surface | URL | What you'll see |
|---|---|---|
| PWA (installable) | https://pathways-iota.vercel.app/ | The user-facing chat. Welcome screen with the Sprout logo, four quick-start chips, bilingual UI. |
| Backend | https://prathik10-pathways.hf.space/ | FastAPI app behind the PWA + SMS channels. |
| Health | https://prathik10-pathways.hf.space/health | `{"status":"ok","version":"1.0.0","channels":["sms","web"],"modules":["dashboard","parole_reminders","writeback","audit"]}` |
| OpenAPI / Swagger | https://prathik10-pathways.hf.space/docs | Interactive API explorer. Try `/_debug/invoke`. |
| Caseworker dashboard | https://prathik10-pathways.hf.space/dashboard/ | Token-gated. Demo mode accepts `Authorization: Bearer <anything>`. |
| Markdown report export | https://prathik10-pathways.hf.space/dashboard/api/report.md | Anonymized monthly trend report. Same auth. |

## What's running right now

| Subsystem | State | Backed by |
|---|---|---|
| SMS channel | Live | Twilio webhook + `pathways/api/main.py` |
| Web channel (PWA) | Live | `pathways/api/web.py` + Vercel-hosted React 19 PWA |
| Multi-turn intake | Live | Salted SHA-256 thread_id + LangGraph PostgresSaver |
| Multilingual (EN/ES) | Live | `pathways/i18n/` + bilingual draft templates + Spanish crisis hook patterns |
| Multi-need routing | Live | Heuristic + LLM intake; iterates over all detected needs in match |
| Geo-aware ranking | Live | All 254 TX counties → 28 TWC workforce regions, ZCTA centroids, haversine |
| Crisis hook | Live | `.claude/hooks/crisis_keyword_check.py`, regex-deterministic, EN + ES patterns |
| Compliance auditor | Live | `compliance-auditor` sub-agent, runs every turn, blocks before send |
| Provider-pluggable LLM | Live | `pathways/llm/`, Anthropic default + Gemini fallback |
| Hybrid retrieval | Available (opt-in) | `PATHWAYS_RETRIEVAL_BACKEND=hybrid` + run `python scripts/embed_corpus.py` |
| Caseworker dashboard | Live | Token-gated, anonymized aggregates, per-partner scope |
| Anonymized Markdown trend reports | Live | `GET /dashboard/api/report.md` |
| Eval harness | Live | CI gate on every PR. 73 scenarios, 11 categories, crisis must be 100% |
| Opt-in parole reminder | **Live with forward phone map** | Queue lives in `parole_reminders` table; daily cron drains it; phone map encrypted via Fernet |
| NGO write-back queue | **Live with forward phone map** | Queue lives in `relay_messages`; same daily cron drains; same forward map |
| PWA resource map view (Phase 7) | Live | `web/src/components/ResourceMap.tsx` — Leaflet + OpenStreetMap tiles + custom marigold pins + Google Maps deep-link. Self-gates when no resource has lat/lon. |
| Map-engagement analytics (Phase 7) | Live | `resources_with_coords_count` column on `conversation_events` + `map_pins_total` / `turns_with_map_view` in dashboard summary + structured `web_turn_map_metrics` log line per turn |
| CI auto-deploy to HF Space (Phase 7) | Live | `.github/workflows/deploy-hf.yml` — push to `main` force-pushes the repo to the HF Space, polls `/health` for 10 min; needs `HF_TOKEN` repo secret with write scope |

## Quality signal

```
305 unit tests + 73 eval scenarios = 378 things that must stay green
                                       for a PR to merge
```

CI runs both on every push and PR.

## Operator setup (what the deploy needs)

Required for production-quality send (parole reminders + NGO write-back):

```bash
# 1. Encryption key for the forward phone map. Generate once, paste
# into the HF Space's PATHWAYS_PHONE_ENCRYPTION_KEY secret.
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Admin endpoint secret for the daily cron.
openssl rand -hex 32   # paste into HF Space secret PATHWAYS_ADMIN_TOKEN
                       # AND into GitHub repo secret PATHWAYS_ADMIN_TOKEN
                       # (used by .github/workflows/daily-cron.yml)

# 3. Hugging Face write-scope token for the CI auto-deploy.
#    Create at https://huggingface.co/settings/tokens with WRITE scope.
gh secret set HF_TOKEN   # paste the token when prompted
gh workflow run deploy-hf.yml --ref main   # first sync (catches any backlog)
```

That's it. The daily-cron workflow at `.github/workflows/daily-cron.yml`
hits the admin endpoint every day at 14:00 UTC and drains both queues.
Without the encryption key, the system falls back to memory-only phone
map and the cron honestly reports `skipped_no_phone`.

The deploy-hf workflow at `.github/workflows/deploy-hf.yml` force-pushes
`main` to https://huggingface.co/spaces/prathik10/pathways on every
merge and polls `/health` for 10 minutes. Without `HF_TOKEN` set, the
workflow fails fast with a clear error in the Actions tab.

## What's deferred (and why)

| Item | Blocker | Unblock criterion |
|---|---|---|
| MMS photo extraction of TDCJ release packet | Paid Twilio MMS + Claude vision spend | Partner sponsorship, or pilot data showing it's the adoption bottleneck |
| Warm-transfer voice connect | Paid Twilio Voice + carrier fees | Same |

Both have full design + estimated effort in
[`docs/PHASE6_DEFERRED.md`](docs/PHASE6_DEFERRED.md).

## What's NOT next (intentionally)

The technical surface is comprehensive. The next bottleneck is real
users, not more features. Priorities going forward are:

1. Partner NGO outreach. The dashboard URL is the artifact that
   unlocks those conversations.
2. Recruiter / job-application use. The architecture showcase is the
   point of this project for that audience; the live URLs and the
   journal make the case better than any pitch deck.
3. Real user testing with one returning citizen, when relationships
   make that possible.

Anything in code beyond bug fixes from real-user signal is premature
optimization.
