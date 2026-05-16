# Phase 6: deferred items + unblock criteria

This file tracks the Phase 6 items the team explicitly deferred. Each
section has the design we'd ship, the blocker that's currently in the
way, and the concrete signal that would unblock it.

The four items that *did* ship in Phase 6 are:
- #1 Opt-in parole-reporting reminder (`pathways/parole_reminders/`)
- #3 Anonymous monthly trend reports (`GET /dashboard/api/report.md`)
- #5 NGO write-back queue (`POST /dashboard/api/writeback`)
- Plus chunk B: eval harness expansion (+25 scenarios, +5 scorers)

The two below remain deferred.

---

## #2 MMS photo extraction of the TDCJ release packet

### What it would do

When a recently released user texts a photo of their TDCJ release
packet, Pathways extracts the structured fields and pre-fills the
intake profile in one shot instead of asking name -> ZIP -> need
across four turns.

### Why it matters

The release packet has the parole officer name, the assigned county,
the supervision conditions, the next reporting date, and (often) a
gate-money receipt. A user who can photograph it once and have it
parsed reduces intake from ~4 turns to 1. For a population that often
has 30 free SMS-credit minutes before their TracFone runs out, that's
a real difference.

### Design

1. **Inbound channel:** Twilio inbound MMS (paid) hits a new
   `/sms/mms` webhook that pulls the attached `MediaUrl0` (the JPEG/
   PNG/PDF the user texted).
2. **Vision extraction:** Claude vision (`claude-opus-4-7` or `claude-
   sonnet-4-6` with image input) parses the page into structured JSON
   matching `IntakeProfile`. System prompt enforces a strict schema
   and a "if unsure, return null" rule.
3. **Consent + redaction:** The image bytes are processed in memory,
   never written to disk. The extracted JSON is logged (PII fields
   redacted by the existing `pii_redact` PreToolUse hook). The image
   itself is discarded after extraction.
4. **Pre-fill:** The intake node sees a `mms_extracted_profile` field
   on state, merges it into the running profile, and skips the slot-
   filling prompts for any field the vision call filled with high
   confidence.

### Blocker

- Twilio inbound MMS costs $0.01 per message in the US. The current
  zero-spend constraint says no Twilio paid features until a partner
  org sponsors the bill.
- Vision API calls aren't free. Each MMS would be ~1 cent in Claude
  Sonnet 4.6 image-input tokens. At meaningful volume this adds real
  cost.

### Unblock criteria

Either:
1. A partner org commits to underwriting Twilio + Claude vision spend
   (or any other paid mainstream LLM with vision), OR
2. The Pathways pilot proves enough usage that the cost becomes
   justifiable on its own terms (e.g., it's clearly the bottleneck to
   adoption).

### Estimated effort once unblocked

- ~2 days for the webhook + vision pipeline
- ~1 day for the consent / redaction / hook wiring
- ~1 day for tests (mocked vision client; synthetic packet image)
- Total: ~4 days

---

## #4 Warm-transfer voice connect

### What it would do

When Pathways escalates to a human navigator (any
`escalation_reason`), the user gets the option to reply `CALL` and
have Pathways dial both legs (the user + the partner NGO's intake
line), then bridge them into a live call. The user never leaves SMS;
the partner picks up a regular phone call.

### Why it matters

A cold phone number in an SMS reply ("call 211 for housing help")
has a substantially lower follow-through rate than a warm transfer
that places the call for the user. The literature on returning-citizen
services consistently shows warm-transfer conversion is roughly 2-3x
cold referral conversion.

### Design

1. **Trigger:** When the graph routes to `escalate` AND the matched
   resource has a `warm_transfer_phone` configured, the reply ends
   with: "Reply CALL to be connected to [Name] in about 30 seconds."
2. **CALL handler:** A new SMS body keyword `CALL` (in addition to
   STOP/HELP/START) initiates the bridge.
3. **Twilio Voice:** Pathways calls the user's number, then calls the
   partner number, then bridges via a `<Dial>` TwiML response. The
   call is recorded only if both parties opt in (TX is a one-party
   consent state for recording, but the safety-first default for
   reentry use is two-party).
4. **Logging:** A new `warm_transfer_events` table captures
   thread_id, partner_resource_id, initiated_at, connected_at,
   duration_seconds, outcome. No call recordings, no transcripts.

### Blocker

Same as MMS: Twilio Voice is paid. ~$0.013/min outbound + carrier
fees. A typical warm transfer is 5-10 minutes. At 100 transfers/month
that's ~$50-$130/month. Violates zero-spend.

### Unblock criteria

Same as MMS: partner sponsorship of the phone bill, or pilot evidence
that warm-transfer conversion materially exceeds cold referral
conversion in the Pathways data (the existing `referral_outcomes`
table from Phase 3 scaffolding would be the source of truth for that).

### Estimated effort once unblocked

- ~1 day for the CALL keyword + escalate-node integration
- ~2 days for the Twilio Voice handler + the warm_transfer_events
  table + the consent prompt
- ~1 day for tests (Twilio's TestClient covers webhook responses;
  manual test of the bridge against the trial account)
- Total: ~4 days

---

## Forward phone map (dependency for both write-back send + parole reminders)

Both shipped Phase 6 features (parole reminders #1 and NGO write-back
#5) queue messages by `thread_id` (the salted SHA-256 hash of the
phone number), but neither can actually send until the operator wires
a forward map from `thread_id -> phone` at send time.

The SMS path knows the phone (it arrives on the Twilio webhook), so
the right place to populate the map is in `pathways/api/main.py::sms`
right after `thread_id_for_phone` resolution. The schema would be a
small `session_phones(thread_id PK, encrypted_phone, last_seen)` table
with the phone encrypted via a Fernet key in `PATHWAYS_PHONE_ENCRYPTION_KEY`.

When the operator is ready to enable real outbound from these
features, three lines change:
1. Add `session_phones` insert in the SMS handler.
2. Add `pathways/sessions/phone_map.py::resolve(thread_id) -> phone`.
3. Point the parole reminder service's `_resolve_phone` and the
   writeback service's default `phone_for_thread` at the new resolver.

Until then, both features queue messages and report
`skipped_no_phone` in the daily cron summary. The queues persist; no
data is lost; the system catches up when the map is wired.
