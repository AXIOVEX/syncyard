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
- [x] T003 Lane generalization: lane set, concurrency, and
      watermark tables read from config; validation battery
      (duplicate names, bad host refs, inverted watermarks).
- [x] T004 Golden tests: fixture queue driven under the fleet
      config produces byte-identical dispatch decisions to the
      pre-config code path.
- [x] T005 Fleet cutover to config: queue snapshot, switch,
      reconciliation (open-set equality), report.

## Phase 2 — Host matrix (FR-003, FR-004)
- [x] T006 Host type model in config + gatekeeper routing by
      host; identity-marker contract per type.
- [x] T007 Windows + WSL2 transports generalized from
      run.yml / wsl.yml / grab.yml (no behavior change for the
      production fleet; proven by the Phase 1 golden tests).
- [x] T008 Linux + macOS transports (execute + grab) with
      hosted-runner CI smoke batteries.
- [x] T009 Docker venue transport (image from config/job,
      declared mounts, result return via grab) + battery.

## Phase 3 — Backchannel hardening (FR-005)
- [x] T010 Agent start-up self-test; result in heartbeat.
- [x] T011 `gk status` heartbeat age + stale alarm (>5 min).
- [x] T012 Chaos battery: kill/restart, corrupt cmd.json,
      duplicate ids, STOP halts execution, heartbeat survives.
- [x] T013 Recovery runbook shipped (spec 009 FR-007 cases).

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
- [x] T022 Create `AXIOVEX/gh-syncyard` (public, Apache-2.0,
      topic `gh-extension`); scaffold with
      `gh extension create --precompiled=go`.
- [x] T023 Thin dispatcher: locate the installed gatekeeper
      (or walk the user through installing it) and forward
      submit/status/cancel/pause/resume/outbox with output
      and exit codes streamed.
- [x] T024 Release wiring: `gh-extension-precompile` action;
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

## Phase 7 progress
- [x] T022–T024 (complete, 2026-10-31; pulled forward ahead of
      Phases 2–5 on the owner's order): `AXIOVEX/gh-syncyard`
      is live (public, Apache-2.0, topics `gh-extension`,
      `syncyard`, `github-cli`). The dispatcher (Go, stdlib
      only) resolves the gatekeeper via $SYNCYARD_GK,
      $SYNCYARD_HOME, ~/syncyard, ~/.syncyard, beside the
      binary, or ./gatekeeper, resolves Python via
      $SYNCYARD_PYTHON or PATH, and forwards every other
      command with streams and exit code unchanged;
      `version`/`doctor`/`help` are extension-native.
      Release v0.1.0 built by `cli/gh-extension-precompile`
      (run 41193373037, success; assets for darwin/linux/
      windows/freebsd incl. the required six targets).
      Install proof on this machine: `gh extension install
      AXIOVEX/gh-syncyard` → `gh syncyard version` →
      `gh syncyard doctor` (fleet gatekeeper resolved via
      $SYNCYARD_HOME) → `gh syncyard status` printed the live
      fleet status (491 completed jobs) through the real
      gh CLI.

## Phase 1 progress (slice 2)
- [x] T003 + T004 (2026-10-31): gk.py now binds every config
      constant from the effective config at import (repos,
      budgets, dispatch knobs, workflows, lane set + runner
      labels + per-lane concurrency, queued/executing
      watermark tables, merged host cwd map, marker pattern,
      log cap); a config that fails validation exits loudly
      (fail closed). `gatekeeper/test_golden.py`: 17 constant
      anchors against the pre-config literals + fixture-queue
      dispatch equivalence (defaults vs fleet example yaml,
      byte-identical decisions in lanes-live and pre-lane-cap
      scenarios, also pinned against hand-computed semantics).
      All batteries pass; test_golden wired into CI.
- [x] T005 (fleet cutover, 2026-10-31): pre-switch queue
      snapshot 534 records (aggregate sha256
      780935b8257d29ad08c2c257ec079e79456b4dd719271362d2335c5
      7296c4411, open set 5). Wired gk.py + config.py deployed
      by atomic rename (fleet hashes match the repo copies);
      `gk status` identical on the defaults path and again
      with the fleet `syncyard.yaml` in place; reconciliation
      exact (534 = 534, open-set equality); first sweep on
      the wired code ran clean and dispatched (budget 4,880).
      Spec 010 Phase 1 (FR-001/FR-002/FR-007) is COMPLETE.

## Phase 2 progress
- [x] T006 (2026-10-31): hosts in config now declare the
      transport workflows they serve (execute/grab kinds) and
      their identity markers; an IDENTITY_BY_TYPE contract
      gives every host type its default marker set. Validation
      fails closed on: undeclared workflow served, bad kind,
      a wsl2 workflow its via host does not serve with the
      same kind, a declared workflow served by no host, an
      empty identity list. The gatekeeper routes by host:
      submit/adopt refuse a (lane, workflow) pair the lane's
      host does not serve in the needed kind — no silent
      venue fallback (FR-004). Golden battery: routing anchors
      + an 8-pair routing matrix spanning the fleet hosts and
      a macos host added by config alone, all pinned. Fleet
      behavior unchanged (every fleet lane sits on the
      windows host, which serves all three transports).
      Fleet cutover DONE the same day, Phase 1 shape:
      snapshot 534 records (open set 2 at deploy time), wired
      gk.py + config.py + refreshed fleet syncyard.yaml
      deployed by atomic rename (hashes match main), open
      jobs verified routing to (desktop, execute), misroute
      refusal proven in-process, reconciliation exact
      (534 = 534), first sweep on the routing build clean
      (dispatched 1, budget 4,985).
- [x] T007 (2026-10-31): the repo's transport workflows
      (runner/workflows run/wsl/grab, v0.2.0) are generalized
      to the shape the production door already runs: a `lane`
      input addresses the runner (`runs-on: [self-hosted,
      "${{ inputs.lane }}"]`), no hardcoded label lists, and
      host-agnostic prose stating the FR-003 host contract.
      Execution bodies are byte-for-byte the proven ones. A
      new contract battery (runner/test_workflow_contract.py,
      18 checks, wired into CI) pins dispatch-only triggers,
      lane binding, and transport inputs for every workflow.
      The live door workflows are untouched — the spec 005
      move repoints the fleet to these copies when it lands.
- [x] T008 + T009 (2026-10-31): POSIX and Docker transports
      shipped. `runner/workflows/linux.yml` + `macos.yml`:
      native bash execute transports with ONE shared script
      body (base64 via openssl for GNU/BSD portability; cwd
      honored; exit code propagates) — the contract battery
      fails CI if the bodies drift; grab.yml already serves
      every host type. `runner/workflows/docker.yml`: caller
      image + comma-separated mounts + container cwd; the
      script runs inside the image, and files written into a
      declared mount land on the host for grab return.
      Gatekeeper: `submit --image/--mounts` (image falls
      back to the lane host's configured `image`), dispatch
      passes both through — pinned by exact-argv golden
      checks for plain, docker, and grab jobs. Batteries:
      `runner/test_transport_smoke.py` executes the shipped
      bodies (markers, cwd, exit 7; docker: image pull, in-
      container run, mounted result file) and
      `.github/workflows/transport-smoke.yml` runs it on
      ubuntu + macos hosted runners and in a docker-required
      job — GitHub-hosted only; the dispatch-only invariant
      is untouched. The fleet gains no new hosts (defaults
      unchanged); the example config carries commented Linux
      and Docker adopter examples. Spec 010 Phase 2
      (FR-003/FR-004) is COMPLETE.

## Phase 3 progress
- [x] T010–T013 (2026-10-31): the backchannel agent runs a
      start-up self-test (git, python3, base/log writable,
      repo reachable, channel writable) whose result rides
      every heartbeat as `self_test`; bc.py prints it
      (BC_SELFTEST). `gk status` gained a backchannel line —
      heartbeat age, host, stopped, self-test — with a
      `!! BACKCHANNEL STALE` alarm past 300 s (one contents
      call per status run; sweeps unaffected). New chaos
      battery (backchannel/test_chaos.py, 16 checks, in CI):
      the real agent against a local file:// channel —
      execute, duplicate-id refusal, corrupt cmd survival,
      STOP halt + resume, kill -9 restart with no replay.
      RUNBOOK.md ships the FR-007 recovery cases (tray
      restart via one-shot task, tray.log read, runner-lane
      restart, network diagnostics) plus failure triage.
      Field note: the T011 line's first live run caught the
      production agent genuinely stalled (heartbeat frozen
      2026-10-31T11:05:57Z; no command executing, STOP
      absent) — diagnosis + agent update ride the fleet
      deploy of this phase. Spec 010 Phase 3 (FR-005) is
      COMPLETE in the repo.
- [x] Field follow-up (2026-10-31): the stalled agent
      recovered on its own after ~13 minutes — consistent
      with an unbounded `git pull` hanging on a network
      stall (the loop's only unbounded wait). agent.sh now
      bounds every network git operation with
      SYNCBC_GIT_TIMEOUT_S (default 120 s; clone 2x), so a
      stalled sync fails one cycle instead of freezing the
      heartbeat. The chaos battery's fixed-sleep phases were
      hardened to polled waits after one flaky run; two
      consecutive full passes followed.
