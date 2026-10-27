# Tasks: 002-runner-lanes

- [ ] T001 — In one owner session on the desktop: fetch a
  registration token and run the prepared setup to register the
  quick, normal, and gpu runners under the operator's profile,
  each in its own directory.
- [ ] T002 — Relabel the incumbent runner as lane-long, keeping its
  old labels during the transition.
- [ ] T003 — Install the runner watchdog as a scheduled task under
  the operator's profile (script: `runner/runner-watchdog.ps1`).
- [ ] T004 — Add the required `lane` input to the workflows;
  runs-on becomes `[self-hosted, <lane label>]`.
- [ ] T005 — Run one identity job per lane; record the markers
  (hostname, Windows user, WSL user; both GPUs for lane-gpu).
- [ ] T006 — Update the clients to take a required lane argument;
  roll programs over one by one.
- [ ] T007 — Update SKILL.md and the changelog with the lane
  behavior in the same change (constitution §VII).
