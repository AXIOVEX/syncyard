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
- [ ] T001 Host liveness model: per-host last-seen record at
      the gatekeeper; sweep reads the host heartbeat (backchannel
      transport) and `gk status` renders host UP/DOWN against a
      configurable threshold. Golden battery pins the sweep's
      read cost and the status rendering.
- [ ] T002 Going-down record format + verified-write writer
      (host side) and gatekeeper ingest: ledger `host_going_down`
      event, per-record `interrupted_by` annotation, dispatch
      hold for the host. Golden battery pins ledger + annotations
      byte-for-byte on fixtures.
- [ ] T003 Outbox notification on going-down (FR-004): one group
      per affected notify registration + owning chat; duplicate
      suppression on re-sweep pinned by test.

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
- [ ] T011 Boot-shape evaluation on a test host: service-mode
      vs autologon+tray vs boot-scheduled launcher, measured
      against the device-bound job classes (WSL, GPU, audio,
      bench). Evidence pack to the owner.
- [ ] T012 **Owner gate**: boot shape chosen from the T011
      evidence. If service-mode is chosen for any lane, the
      same change amends spec 007 FR-003 and SKILL.md's
      Windowless Supervision section.
- [ ] T013 Implement the chosen shape; per-lane `boot-runnable`
      vs `logon-bound` labels in config; lanes that cannot
      honestly run pre-logon render DOWN, never online.
- [ ] T014 WSL ensure + recovery handshake sequence:
      distro start, backchannel self-test fresh, runners per
      T013, campaign relaunch per T009, handshake to the
      gatekeeper; dispatch stays held until the handshake.
      Test: a withheld handshake leaves the host DOWN.

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
