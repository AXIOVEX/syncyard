# Tasks: Spec 010 — Public Release

Sequenced so the production fleet is never at risk: config is
additive first (defaults = today's constants), proven against
the live fleet by golden test, and only then becomes the
source the fleet runs on (spec 009 FR-006 snapshot +
reconciliation around the cutover).

## Phase 1 — Configuration (FR-001, FR-002, FR-007)
- [ ] T001 `syncyard.yaml` schema + checked-in example config
      expressing the current production fleet exactly.
- [ ] T002 Gatekeeper config loader (stdlib only): file →
      effective config; absent keys fall back to today's
      constants; invalid config fails closed with a named
      error, never a silent default.
- [ ] T003 Lane generalization: lane set, concurrency, and
      watermark tables read from config; validation battery
      (duplicate names, bad host refs, inverted watermarks).
- [ ] T004 Golden tests: fixture queue driven under the fleet
      config produces byte-identical dispatch decisions to the
      pre-config code path.
- [ ] T005 Fleet cutover to config: queue snapshot, switch,
      reconciliation (open-set equality), report.

## Phase 2 — Host matrix (FR-003, FR-004)
- [ ] T006 Host type model in config + gatekeeper routing by
      host; identity-marker contract per type.
- [ ] T007 Windows + WSL2 transports generalized from
      run.yml / wsl.yml / grab.yml (no behavior change for the
      production fleet; proven by the Phase 1 golden tests).
- [ ] T008 Linux + macOS transports (execute + grab) with
      hosted-runner CI smoke batteries.
- [ ] T009 Docker venue transport (image from config/job,
      declared mounts, result return via grab) + battery.

## Phase 3 — Backchannel hardening (FR-005)
- [ ] T010 Agent start-up self-test; result in heartbeat.
- [ ] T011 `gk status` heartbeat age + stale alarm (>5 min).
- [ ] T012 Chaos battery: kill/restart, corrupt cmd.json,
      duplicate ids, STOP halts execution, heartbeat survives.
- [ ] T013 Recovery runbook shipped (spec 009 FR-007 cases).

## Phase 4 — Agent skills (FR-006)
- [ ] T014 `skills/meta-muse/SKILL.md` — primary package.
- [ ] T015 `skills/generic-agent/SKILL.md` +
      `skills/cli-only/SKILL.md` from the same contract.
- [ ] T016 Skill currency check in CI: skill version matches
      VERSION; invariant text present verbatim.

## Phase 5 — Docs, tests, release (FR-008, FR-009, FR-010)
- [ ] T017 SECURITY.md posture + adopter checklist; README
      links it above the quickstart.
- [ ] T018 README story + per-host quickstarts.
- [ ] T019 Full battery wiring in CI; all green.
- [ ] T020 CHANGELOG + VERSION 0.3.0 + release.

## Phase 6 — Named later (FR-011)
- [ ] T021 `docs/github-pitch.md` prepared (gh-extension
      adoption shape). NOT sent; owner's word required.

## Phase 7 — gh CLI extension (FR-012, Amendment 1)
- [ ] T022 Create `AXIOVEX/gh-syncyard` (public, Apache-2.0,
      topic `gh-extension`); scaffold with
      `gh extension create --precompiled=go`.
- [ ] T023 Thin dispatcher: locate the installed gatekeeper
      (or walk the user through installing it) and forward
      submit/status/cancel/pause/resume/outbox with output
      and exit codes streamed.
- [ ] T024 Release wiring: `gh-extension-precompile` action;
      binaries for windows/linux/darwin × amd64/arm64 named
      per GitHub's convention; install proof
      (`gh extension install AXIOVEX/gh-syncyard`, then
      `gh syncyard status` against the live fleet).

## Phase 1 progress
- [x] T001 (slice 1, additive): `config/syncyard.example.yaml`
      expressing the fleet exactly + stdlib YAML-subset loader
      with validation (`gatekeeper/config.py`) +
      `gatekeeper/test_config.py` (25 checks: golden constants,
      defaults equivalence, merge, six fail-closed rejections).
      All passing 2026-10-30. gk.py does not read config yet;
      wiring is the next slice.
