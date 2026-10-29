# Tasks — 009 Failsafe Backchannel

- [x] T001 — Spec 009 written (FR-001..FR-007 with acceptance
      criteria) plus AEE claims, citing the owner's 2026-10-29
      override order.
- [x] T002 — WSL agent (`backchannel/agent.sh`): clone/pull the
      private `tbitcs/syncyard-backchannel` repo over git,
      STOP check, execute only a new command id (sha256 of the
      body verified first), write `out.json` matched by id,
      heartbeat every poll cycle (~60 s), full local log at
      `~/syncyard-backchannel/agent.log`. `bash -n` passes.
- [x] T003 — Installer (`backchannel/install-backchannel.sh`):
      copies the agent into `~/syncyard-backchannel/`, writes
      the `syncyard-backchannel.service` systemd user unit,
      enables + starts it, prints SYNCBC_INSTALL markers.
      Idempotent.
- [x] T004 — VM-side client (`backchannel/bc.py`, stdlib only):
      `heartbeat` / `status` / `send` / `wait`; `send` goes
      through the GitHub contents API (no local git), refuses
      to overwrite an unacknowledged pending command unless
      `--force`, stamps id + sha256, verifies by read-back.
- [x] T005 — Offline unit tests (`backchannel/test_bc.py`):
      packing, id, sha256, refuse-to-overwrite and force paths
      against a mocked API layer; no network. Tests pass.
- [x] T006 — Operator doc (`backchannel/README.md`): channel,
      ownership, send/check procedure, recovery use cases,
      STOP kill switch, no-program-jobs rule.
- [x] T007 — SKILL.md: Failsafe Backchannel section + the
      FR-005 periodic status-check duty in the fleet-usage
      part; CHANGELOG `[Unreleased]` entry; VERSION 0.2.0
      (owner override of the version hold, 2026-10-29).
- [ ] T008 — Desktop Access deployment, under FR-006: queue
      snapshot (count + aggregate sha256 + open-job list)
      first; install the agent in WSL on TRISTEN-DESKTOP via
      the installer; prove independence (tray exited, one lane
      stopped, heartbeat fresh, read-only round-trip — FR-002
      acceptance); exercise the read-only recovery use cases
      (tray.log read, network diagnostics); reconcile the queue
      snapshot — open-job set identical, or every difference
      named and explained. (Parent / Desktop Access chat owns
      this step; it is not done from the spec branch.)
- [ ] T009 — Fleet awareness: notify every Syncyard-using chat
      of the new version, the backchannel's existence (read-only
      for them), and the FR-005 duty; confirm each chat's
      pending jobs survived the deployment by key.
