# Syncyard Constitution

Ratified: 2026-10-27 (codifies the standing rules the system was
built under on its first day).

## I. One door

- All work on the operator's machines goes through the gatekeeper.
  Programs never dispatch GitHub Actions workflows directly, never
  register their own runners on the shared machines, and never poll
  runs with watchers of their own. The gatekeeper is the only
  dispatcher and the only watcher.
- The one exception class is projects that do not use the operator's
  machines at all. They are out of scope, not exceptions to route
  around the door.

## II. Security invariant

- Self-hosted runners are reachable ONLY through `workflow_dispatch`
  (write access required). No workflow may bind self-hosted labels to
  `pull_request`, `pull_request_target`, issue, or any other
  externally-triggerable event — ever.
- Repository CI runs on GitHub-hosted runners exclusively.
- Runners are registered to this repository only, never org-wide.
- No tokens, credentials, or secrets live in this repository.

## III. Marker verdicts

- A job's verdict comes from the marker lines in its own log and the
  harvested record — never from the Actions run color alone, and
  never from a liveness probe. What is reported is what the markers
  establish, together with what they do not establish.

## IV. Shared API budget

- The GitHub REST quota is one account-wide bucket shared by every
  program. The gatekeeper checks headroom before dispatching,
  stands down below 1,000 remaining calls, and stops watch calls
  below 500. A rate-limit 403 is a hard stop for that scope, never
  something to retry through.

## V. The machines

- Execution runs on the operator's own profile only (the primary
  Windows/WSL user on each machine). Another user's profile is never
  a run environment, and its storage is never deleted or reset.
- Project trees live under the operator's Development folder, never
  in a drive root. Anything installed for any project uses a real
  installer package; a tool whose vendor ships no installer is a
  flagged exception for the owner's ruling, never silently
  grandfathered.

## VI. Health and escalation

- Job-health watermarks trigger a check, never an automatic cancel.
  Cancellation authority stays with the dispatching program's
  coordinator or the owner. Breaches and their outcomes are recorded.

## VII. Documentation currency

- **SKILL.md is updated in the same change as any change to
  behavior, commands, lanes, workflows, or operations.** A change
  that leaves SKILL.md stale is incomplete.
- Development is spec-driven (spec-kit) with claim-level review
  (AEE): every requirement in `specs/` is a claim carrying its
  evidence and a falsification test in the spec's `aee-claims.json`.
  Changes cite the spec they implement; behavior with no spec gets
  a spec in the same change.
- The changelog records every notable change under [Unreleased]
  until the owner releases a version.

## VIII. Versioning

- No version bump and no new release until the owner judges the
  project complete: full CI green and the system proven as the
  daily driver for several days. The version lives in `VERSION`;
  releases are tagged from it.

## Tooling

- Specs are managed with spec-kit (sequential numbering under
  `specs/`). The `.specify/` scripts and templates are installed by
  the specify CLI and are not hand-edited; this constitution is the
  governing document and is edited deliberately, with the change
  recorded in the changelog.
