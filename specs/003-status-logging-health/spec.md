# Feature Specification: Status, Logging, and the Daily Health Check

**Feature Branch**: `003-status-logging-health`

**Created**: 2026-10-27

**Status**: **Implemented 2026-10-27** — status and logging changes
live in the gatekeeper the same day (and mirrored into this
repository's canonical copy); the daily health check is scheduled
and first runs 2026-10-28.

**Direction (operator, 2026-10-27)**: "make sure syncyard has a
status function as well which shows all things queued, running, and
issues. and make sure we have a solid logging system and make sure
you check syncyard daily to make sure no issues and check
dependencybot and CI and keep the tool always improving. And when we
have it solid, we can begin determining new features, but for now we
need to make it robust and solid."

## The gap

The original status printed a table but no issue rollup: a failed
log harvest, a watermark escalation, and a completion with no marker
verdict each had to be spotted by reading raw flags. Two logging
gaps were proven in the field the same day: some runs' logs cannot
be read by `gh run view --log` at all (the harvest failed on every
attempt while the REST archive read fine), and the ledger — a JSON
event stream — is a machine record, not something an operator scans.

## Functional requirements

- **FR-001 — The board.** `gk.py status` prints counts by state,
  explicit queued and running counts, every live job with lane, run
  status, and flags, and completed jobs with their conclusion,
  verdict source, and marker count. The default status is local-only
  and spends no API calls.
- **FR-002 — ISSUES section.** Status ends the board with an ISSUES
  section derived from saved job state: watermark breach/escalation
  flags, failed or pending log harvests, a dispatching state needing
  a human, and completions that lack a marker verdict (failed with
  no markers, or successful with no harvest). Zero issues prints as
  zero.
- **FR-003 — Repo health on request.** `status --repo` adds project
  health for this repository: the latest CI runs, open Dependabot
  alerts, and open Dependabot pull requests. It costs three API
  calls, is made only when the flag is passed, and degrades each
  line to "unavailable" rather than failing the status.
- **FR-004 — Two-layer logging.** The append-only JSON ledger
  (`ledger.jsonl`) remains the machine record of every event. A
  human-readable log (`gatekeeper.log`) carries one line per sweep,
  rotating at 1 MB with one backup. Logging is best-effort: a logging
  failure never breaks a sweep.
- **FR-005 — Harvest fallback.** When `gh run view --log` cannot
  read a completed run, the harvest falls back to the REST logs
  archive before declaring failure, and the job record and ledger
  note which source supplied the log.
- **FR-006 — Daily health check.** A daily check reviews the status
  board (including ISSUES), sweep health, the ledger's error events,
  CI on main, and Dependabot. It merges green Dependabot pull
  requests that bump a GitHub Action by a patch or minor version;
  major bumps are reported, never merged. It reports only material
  findings and stays silent when the system is clean.
- **FR-007 — Robustness first.** Until the operator judges the
  system solid, work on Syncyard is robustness and correctness only
  — no new features are scoped. Defects the daily check surfaces are
  recorded in a robustness backlog and fixed in that order.

## Claims discipline

The status board reports saved state; it does not re-derive truth
from GitHub in the default view. Where saved state and GitHub could
disagree (a run's live status), the board says what the record
holds, and the sweep is what reconciles it.

## Out of scope

- Dashboards, web UIs, or notifications beyond the operating chat.
- Automatic remediation of issues (the check reports and, for
  Dependabot only, merges; everything else is a human's call).
