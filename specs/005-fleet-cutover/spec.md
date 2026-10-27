# Feature Specification: Fleet Cutover — Retiring the Old Doors

**Feature Branch**: `005-fleet-cutover`

**Created**: 2026-10-27

**Status**: **In progress.** The mandate is confirmed by every
desktop-using program (2026-10-27); the gatekeeper is the live
door. The old router repositories retire one by one, each behind
its gate below — nothing is removable yet, because the Syncyard
lane proof (spec 002) has not run.

**Direction (operator, 2026-10-27)**: "make sure all projects in
muse use Syncyard unless they are one of the few exceptions that
do not use the tristen-desktop at all." Asked when the old routers
can be removed, the gates in this spec are the answer given the
same day.

## The gap

Three older doors exist alongside Syncyard: a private desktop
runner repository (today's live door until the lanes land), a
laptop runner repository, and the desktop relay (a hand-built
git-polling protocol). Each was justified when built; each is now
a second way to reach the machines, with its own failure modes —
the relay's worst being a duplicate agent instance executing the
same launch twice. A fleet with several doors drifts; the cutover
leaves exactly one.

## Functional requirements

- **FR-001 — The mandate.** Every project that uses the operator's
  desktop dispatches only through the gatekeeper (spec 001): no
  direct workflow dispatch, no per-project runners, no parallel
  watchers. Projects with no desktop use at all are exceptions by
  definition and are left exactly as they are.
- **FR-002 — Desktop-runner repository gate.** The old desktop
  runner repository is deleted only after: the four Syncyard lane
  registrations exist, each lane has a passing identity proof
  (spec 002 FR-006), and programs are dispatching through the
  Syncyard runners. Until then it is the live door and is not
  removable.
- **FR-003 — Laptop-runner repository gate.** The laptop runner
  repository is deleted after the laptop's runner is installed,
  tested, and re-registered under Syncyard. Expected last: laptop
  access is currently blocked on every route.
- **FR-004 — Relay: archive, never silently delete.** The relay
  repository is archived (read-only) when its fail-safe commission
  closes by report or the operator waives it. Outright deletion
  needs the operator's separate say-so. The relay itself stays
  frozen as break-glass: no job traffic, kept for admin work and
  for emergencies when the Actions route itself is broken.
- **FR-005 — Laptop bridge gate.** No laptop bridge component is
  removed or altered until the laptop runner's acceptance tests
  pass and the owning program confirms it.
- **FR-006 — Cutover constraints.** Every step honors the standing
  rules: execution on the operator's own profile only; project
  trees under the Development folder; real installer packages for
  anything installed (constitution §V).

## Claims discipline

A door is claimed retired from its repository state (deleted or
archived, read back) — never from the intention. A gate is claimed
met from its evidence: identity-job markers for lanes, an
acceptance record for the laptop, a closure report or waiver for
the relay commission.

## Out of scope

- Projects hosted elsewhere (hosted CI, cloud sites, SaaS): not
  cut over, not exceptions to argue about — simply not this spec's
  subject.
