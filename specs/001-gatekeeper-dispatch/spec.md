# Feature Specification: The Gatekeeper — Single Dispatch and Watch Door

**Feature Branch**: `001-gatekeeper-dispatch`

**Created**: 2026-10-27

**Status**: **Implemented 2026-10-27** — live the same day it was
approved (operator decision 2026-10-27 11:15 ET), smoke-tested
(duplicate submit refused; second sweep fully idempotent), and in
continuous operation on a 5-minute sweep since.

**Direction (operator, 2026-10-27)**: every program's work for the
operator's machines goes through one gatekeeper that dispatches
inside a shared API budget and watches everything itself — no
direct dispatches and no per-program watchers.

## The gap

Before the gatekeeper, each program dispatched GitHub Actions runs
itself and polled them on its own cadence. On 2026-10-27 the combined
polling exhausted the account-wide REST quota (5,000 calls/hour) and
stopped a harvest mid-flight. Programs also duplicated each other's
visibility: nobody held the whole queue, so long jobs starved short
ones invisibly.

## Functional requirements

- **FR-001 — Single door.** The gatekeeper (`gatekeeper/gk.py`,
  Python 3 standard library only) is the only dispatcher and the
  only watcher for the shared runner fleet. Programs interact
  through `submit`, `adopt`, `status`, and `cancel`; the `sweep`
  does dispatch and watch passes.
- **FR-002 — Budget gate, checked first.** Every sweep reads the
  rate-limit headroom before anything else. Below 1,000 core calls
  remaining it dispatches nothing (the watch pass still runs);
  below 500 it makes no list call either. A rate-limit response is
  a hard stop for the sweep, never retried through.
- **FR-003 — Duplicate refusal.** A submission whose key is already
  active is refused and reports the existing job. The same workflow
  with the same script hash is likewise skipped at dispatch. This
  refusal is the duplicate-dispatch pre-check; there is no override
  flag.
- **FR-004 — Lane serialization + active cap.** At most one
  gatekeeper-dispatched run per lane is active at a time, and at
  most 2 gatekeeper-dispatched runs are active in total until the
  lanes of spec 002 exist.
- **FR-005 — Batched watch.** One `gh run list` call per sweep
  covers every tracked run. A completed run's log is fetched exactly
  once; the harvest stores the marker lines and a 200-line tail in
  the job record, and the verdict source is recorded as the markers.
- **FR-006 — State safety.** A job's state is saved before its
  dispatch is attempted; a `dispatching` state older than 10 minutes
  with no run id is flagged for a human and is never automatically
  re-dispatched. The sweep is self-locking against overlap.
- **FR-007 — The gatekeeper never cancels.** No sweep action cancels
  a run. Cancellation is a local bookkeeping act for jobs that were
  never dispatched (`cancel`), or the dispatching program's own
  decision outside the sweep (constitution §VI).
- **FR-008 — Pause and resume.** `gk pause --reason <text>` records
  a pause the operator sets and `gk resume` clears. While paused,
  the sweep dispatches no program jobs but keeps watching (verdicts
  and watermarks stay current); status shows the pause and its
  reason, and sweep summaries print PAUSED. Jobs submitted with
  `--maintenance` — operator work on the fleet itself — dispatch
  during a pause, bypassing the active cap and lane serialization
  but never the duplicate check. Added 2026-10-27 on the operator's
  directive, first used the same day to hold the fleet during a
  WSL cleanup and compact.
- **FR-009 — Stop and start (full lifecycle control).** `gk stop
  --reason <text>` is the hard halt, stronger than pause: a sweep
  returns before spending any API budget — no rate-limit call, no
  watch pass, no dispatch — and status shows the STOPPED banner.
  `gk start` clears both a stop and a pause, returning the
  gatekeeper to fully running. Neither state affects jobs already
  dispatched (FR-007 still holds). Added 2026-10-27 on the
  operator's directive that the CLI be fully developed, with
  start/pause/stop as first-class controls.
- **FR-010 — Purge.** `gk purge` removes terminal job records
  (states completed and cancelled) — dry-run by default; deletion
  requires `--yes`. `--older-than-days N` restricts removal to
  records created more than N days ago; `--ledger` additionally
  archives `ledger.jsonl` to a timestamped file and starts a fresh
  ledger. Active, submitted, and watching records are never purge
  targets. Because records carry harvested markers and log tails,
  the age filter is the normal mode; every executed purge is
  itself ledgered.
- **FR-011 — Push notifications.** A job MAY carry a notify target
  (a chat id, set by `--notify-chat` at submit or adopt). The
  gatekeeper MUST surface the pushes owed — started (with the
  job's expected length), completed (conclusion plus verdict
  highlights from the harvested markers), and W2-escalated —
  grouped by notify target, derived from the append-only ledger,
  never replaying history from before the mechanism existed. The
  outbox cursor advances only on an explicit ack after delivery.
  Pushes ride the existing sweep cadence — no new infrastructure.
  (Owner decision 2026-10-27: push over SSE and over an MCP front
  door; MCP remains a possible later ergonomics addition, not the
  push mechanism.)

## Claims discipline

Every completion report cites the marker lines harvested from the
run's own log. A GitHub conclusion of `success` without markers is
reported as exactly that — a conclusion without a marker verdict —
never upgraded to a pass (constitution §III).

## Out of scope

- Webhook-driven watching (polling by sweep is the design; a push
  channel is a possible future spec, not a gap in this one).
- Automatic return of grabbed files to the requesting program (the
  grab workflow produces the artifact; chaining is a future spec).
