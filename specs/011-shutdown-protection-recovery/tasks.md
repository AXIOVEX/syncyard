# Tasks: Spec 011 — Shutdown Protection and Recovery

Sequenced so the production fleet is never at risk: the
record-keeping (Parts A/B gatekeeper side) lands before any
host component can act on it, the guard is proven on a test
host before it touches the production host, and the boot
shape is an owner gate (FR-009) that no phase may pre-decide.
The fleet's existing disciplines apply throughout: pause-first
for any change to live components, queue snapshot +
reconciliation around every fleet deploy (spec 009 FR-006),
and SKILL.md / skills-pack updates in the same change as any
behavior (spec 011 FR-014).

## Phase 1 — Liveness and the going-down record (FR-001, FR-003, FR-006)
- [x] T001 Host liveness model: per-host last-seen record at
      the gatekeeper; sweep reads the host heartbeat (backchannel
      transport) and `gk status` renders host UP/DOWN against a
      configurable threshold. Golden battery pins the sweep's
      read cost and the status rendering.
- [x] T002 Going-down record format + verified-write writer
      (host side) and gatekeeper ingest: ledger `host_going_down`
      event, per-record `interrupted_by` annotation, dispatch
      hold for the host. Golden battery pins ledger + annotations
      byte-for-byte on fixtures.
- [x] T003 Outbox notification on going-down (FR-004): one group
      per affected notify registration + owning chat; duplicate
      suppression on re-sweep pinned by test.

## Phase 1 progress
- [x] T001–T003 (gatekeeper side, 2026-10-31): `liveness.
      down_after_s` config (default 900, positive number,
      fail-closed validation; mirrored in the example config and
      the config battery). Every sweep makes ONE backchannel
      contents read — the read class the sweep already spends —
      refreshing the per-host last-seen record in `hosts.json`
      beside the queue (verified writes); the heartbeat proves
      the WSL2 host and its `via` chain. `gk status` renders
      each host UP/DOWN + heartbeat age from that record and
      spends no API doing it. A merely stale heartbeat records
      DOWN but never blocks dispatch in this phase; only a
      going-down ingest sets a dispatch hold.
      Going-down record format (JSON): `host`, `ts` (the
      drain's start), `trigger` (shutdown | logoff | update |
      unknown), `active_run_ids`, `supervised` (list of
      `{id, checkpoint}`), `uncheckpointed` (list of ids). The
      host delivers it as a `going_down` field on its heartbeat
      payload; the sweep detects it there and calls
      `ingest_going_down`, which ledgers `host_going_down`,
      annotates each affected job `interrupted_by:
      "host-shutdown"` + `interrupted_at` (a ledger
      `interrupted` line per job is what the outbox turns into
      one push per affected notify registration), and sets the
      host's dispatch hold. Ingest is exactly-once per
      (host, ts) — the dedupe lives in the liveness state
      file. The hold clears via `gk host-resume <host>`, the
      Phase-1 stand-in for the FR-010 recovery handshake
      (Phase 5). The gatekeeper never cancels and never
      re-dispatches. Two honest gaps, named: (1) the
      owning-chat copy of the FR-004 notification — the outbox
      has no default/owning target concept today (groups are
      keyed by per-job notify registrations only), so Phase 1
      notifies the registered targets and the owning chat sees
      the event on the status board and in the ledger; an
      owning-chat route needs a config decision. (2) The
      host-side verified-write writer + backchannel push of
      the record (FR-003 host side) ships with the guard
      (Phase 3); the spec 009 runbook's message-set update
      rides that same change — this phase changes no agent
      behavior and invents no second heartbeat format (the
      reader is the one `gk status` already used).
      `gatekeeper/test_golden.py` scenario 6 pins all of it
      (aging -> DOWN, ledger lines, annotations, hold,
      host-resume, single outbox group, duplicate suppression);
      `test_config.py` covers the new key valid/invalid.

## Phase 2 — The drain protocol (FR-005, FR-007)
- [ ] T004 Drain signal + checkpoint window mechanics: guard →
      jobs/campaigns signal path, per-lane window from config,
      checkpointed / uncheckpointed accounting into the
      going-down record. Test-host battery with fixture units
      (cooperative, slow, and ignoring).
- [ ] T005 `gk drain --host <host>`: pause-host, signal, wait,
      plain-language CLEAN / INTERRUPTING verdict. Oracle pass
      by the owner in a quiet and a busy window before it is
      documented as the restart protocol.

## Phase 3 — The shutdown guard (FR-002)
- [ ] T006 Guard component on the test host: shutdown block
      reason registration/release tied to active work,
      `WM_QUERYENDSESSION` veto bounded by the drain window.
      Oracle evidence: held restart with the reason visible in
      the Windows shutdown UI; unheld restart when idle.
- [ ] T007 Guard hardening: the guard's lifecycle is harder to
      exit than the tray's (spec 007 tension, named in the
      spec); a stopped guard is a host-health ISSUES entry at
      the gatekeeper, never a silent loss of protection.
- [ ] T008 Production-host guard deploy, fleet shape: pause,
      snapshot, deploy, reconcile, one clean sweep.

## Phase 4 — Supervised work vehicle (FR-008)
- [ ] T009 Supervisor + ensure + heartbeat, generalized from
      the production anchor pattern: campaign registration at
      the gatekeeper with the checkpoint contract recorded;
      relaunch skips completed units. Battery: kill mid-unit,
      observe remaining-units-only completion.
- [ ] T010 First real campaign adoption (gate): one production
      program's coordinator states its checkpoint contract and
      registers; the anchor's existing campaigns migrate
      without a behavior change to their science.

## Phase 5 — Boot recovery (FR-009, FR-010)
- [ ] T011 Boot-shape proof, narrowed by Amendment 1: on one
      lane of the production host, convert the runner to a
      Windows service running as the owner account and prove,
      with no interactive logon present, that the lane returns
      online and honestly runs its job classes — the WSL
      reachability check is the decisive one. If the owner's
      WSL distro is unreachable from the service session, the
      evidence goes to the fallback shape (boot-scheduled
      launcher in the owner's name) and the same proof runs
      there. Evidence pack either way.
- [x] T012 **Owner gate**: boot shape chosen.
      **Satisfied by owner directive, 2026-10-31 ~23:57 ET
      (Amendment 1)**: boot-start with no interactive logon is
      required; autologon (shape (b)) is excluded by the
      ruling's own words. Selected shape: service-mode
      runners running as the owner account, with the
      boot-scheduled launcher as the named fallback if the
      T011 proof fails on WSL reachability. Choosing
      service-mode amends spec 007 FR-003; that amendment
      rides with the T013 implementation change below, as
      this task requires, together with SKILL.md's
      Windowless Supervision section.
- [ ] T013 Implement the chosen shape; per-lane `boot-runnable`
      vs `logon-bound` labels in config; lanes that cannot
      honestly run pre-logon render DOWN, never online.
      Conversion scope (Amendment 1): all four runner lanes
      to services running as the owner account; the
      backchannel agent joins the boot set (linger for its
      user + the T014 distro-start ensure pulled forward);
      the tray's logon autostart is retired in the same
      change so no runner is ever started twice.
- [ ] T014 WSL ensure + recovery handshake sequence:
      distro start, backchannel self-test fresh, runners per
      T013, campaign relaunch per T009, handshake to the
      gatekeeper; dispatch stays held until the handshake.
      Test: a withheld handshake leaves the host DOWN.
- [ ] T021 `gk reboot` (FR-015, Amendment 1): drain-aware
      refusal naming active jobs, going-down record written
      before any signal (trigger `remote-reboot`),
      `host_reboot_requested` ledger event naming the
      requesting chat, signal via a fresh backchannel first,
      a maintenance dispatch second, an honest unreachable
      report otherwise; dispatch hold after signaling.
      Batteries pin the refusal, the order, and the route
      selection.
- [ ] T022 Venue conversion + no-logon boot proof on
      TRISTEN-DESKTOP: the T013 conversion applied under
      pause-first discipline, then one live fire of
      `gk reboot` (T021) with **no logon afterwards** —
      runners return per their labels, the backchannel
      heartbeat resumes fresh, queued jobs execute in order.
      Counted as a drill under FR-013; the evidence pack
      (runners API state, heartbeat age, job completions)
      lands with the change.

## Phase 6 — Reconciliation and the recovery report (FR-011, FR-012)
- [ ] T015 Sweep reconciliation of interrupted runs: adopt
      GitHub terminal state exactly once (completed / failed /
      cancelled / never-started), interrupted annotation on
      host-killed runs, marker harvest where a log exists, no
      re-dispatch side effects. Golden battery covers all four
      states.
- [ ] T016 Recovery report: shutdown account, interrupted /
      resumed / lost by name, emitted to the owning chat after
      reconciliation; host-never-returns closure path (no
      handshake required) with the same report shape.

## Phase 7 — Drills, docs, release (FR-013, FR-014)
- [ ] T017 Three drills scripted and run on the test host:
      cooperative drain, forced kill mid-run, host-never-
      returns. Results recorded here before any tag.
- [ ] T018 Config keys documented in the example config
      (drain window, liveness threshold, lane session labels);
      validation battery covers the new pairs fail-closed.
- [ ] T019 SECURITY.md shutdown-and-recovery section
      (protection level in the spec's words; the chosen boot
      shape's tradeoff as chosen); SKILL.md + skills pack gain
      drain, supervised work, and host-DOWN states; currency
      battery covers the new text.
- [ ] T020 CHANGELOG + version decision with the owner (this
      spec lands across the 0.3.0 program of spec 010; the
      version it ships in is the owner's call at tag time).

## Notes for the implementing phases
- The 2026-10-31 production anchor campaigns are the FR-008
  reference implementation; their supervisor/ensure/heartbeat
  hashes and the restart-resume evidence live in the Desktop
  Access chat's records and are the starting fixtures for T009.
- The going-down record's backchannel push (T002) extends the
  spec 009 agent's message set; update the spec 009 runbook in
  the same change.
- Nothing in any phase dispatches through a new surface: the
  dispatch-only invariant (spec 010 FR-009) binds every task
  above.
