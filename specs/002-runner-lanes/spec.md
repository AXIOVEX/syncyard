# Feature Specification: Runner Lanes and the Runner Watchdog

**Feature Branch**: `002-runner-lanes`

**Created**: 2026-10-27

**Status**: **Specified; stand-up pending an owner session on the
desktop.** The watchdog script is written
(`runner/runner-watchdog.ps1`); the lane registrations, labels, and
identity proofs all happen in one owner-run session because runner
registration tokens are short-lived and runners are user-window
processes that a job cannot bootstrap for itself.

**Direction (operator, 2026-10-27)**: four lanes on the desktop —
quick, normal, long, gpu — serial within each lane, so a two-minute
probe never again waits behind a two-hour render.

## The gap

Census, 2026-10-27: one shared runner queue. A quick status job
waited ~75 minutes behind a ~90-minute host job. Lanes give queue
isolation — shorter work is no longer held hostage by the longest
job in the fleet — without pretending to add compute.

## Functional requirements

- **FR-001 — Four registrations, one profile.** Four runner
  registrations for this repository on the desktop, all under the
  operator's own profile: the incumbent runner becomes lane-long;
  new runners serve lane-quick, lane-normal, and lane-gpu. Each
  runner lives in its own directory following the incumbent pattern
  and runs as a user-window process, not a service.
- **FR-002 — Required lane.** Every dispatch declares a lane; the
  workflows take a required lane input and target
  `[self-hosted, <lane label>]`. No declared lane = not dispatched.
- **FR-003 — Routing.** A job that needs a GPU goes to lane-gpu
  regardless of duration. Unknown duration routes to lane-long. A
  job that overruns its lane's norm twice is re-laned and the
  change is reported.
- **FR-004 — Serial within lane.** Each lane executes one job at a
  time. Lanes do not parallelize a machine; they order its queues.
- **FR-005 — Watchdog.** A scheduled task under the operator's
  profile checks each runner's listener process every 5 minutes and
  restarts a dead listener, capped at 3 restarts per runner per
  rolling hour, after which it logs OWNER NEEDED and stops trying.
  It writes a local status file an operator can read at a glance.
- **FR-006 — Identity proof before real work.** Each lane proves
  itself with an identity job before carrying real dispatch:
  hostname, Windows user, and WSL user printed as markers; the gpu
  lane additionally prints both graphics cards from the Windows
  side. A lane without a passing identity proof is not routed to.

## Claims discipline

Lane stand-up is claimed per lane, from that lane's identity-job
markers — never from the registration appearing in the repository
settings (a listing is not a proof the lane executes).

## Out of scope

- Laptop runners (they join under the same pattern in a separate
  session, gated by spec 005's laptop gate).
- Detached campaigns: long-running work that lives outside Actions
  stays outside; its status checks are ordinary quick-lane jobs.
