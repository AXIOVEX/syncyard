# Feature Specification: Failsafe Backchannel

**Feature Branch**: `spec-009-failsafe-backchannel`

**Created**: 2026-10-29

**Status**: **Specified; implementation in this change.**
The VM-side client (`backchannel/bc.py`), the WSL agent
(`backchannel/agent.sh`), and its installer
(`backchannel/install-backchannel.sh`) are written in this change.
Desktop installation of the agent is an owner-session / Desktop
Access act, sequenced so no pending gatekeeper job is lost
(FR-006).

**Direction (owner, 2026-10-29 ~19:03 ET)**: "No we need to
override this. We are supposed to have a failsafe backchannel for
instances like this. in fact, make sure you have a dedicated
channel just for Syncyard development in this side chat" — and,
in the same order: every agent must check Syncyard status
periodically, a new version is to be deployed, other agents are
to be updated to be aware of it, and no pending job may be lost.

## The gap

Syncyard's normal door — gatekeeper dispatch to GitHub Actions
self-hosted runners supervised by the tray — is a single route.
When that route itself is the thing that is broken, there is no
recovery path left:

- On 2026-10-29 the owner could not see the Syncyard tray at
  all. The runners were (as later checks showed) alive, but the
  only tools that could have restarted the tray in his session
  or read its log were jobs through the very system in question.
- The same day, adding a board address on the desktop's wired
  adapter disrupted that adapter's internet reachability. The
  fix needed elevated, owner-session work that a runner job
  provably cannot do (the runner process is not elevated, and
  it cannot even register a highest-privilege one-shot task).
- Under VM write waves, gatekeeper dispatch itself stalls for
  hours (PROGRAM-STATUS backlog item (i)): the pre-dispatch save
  is an exec-channel write from a fresh process, and a process
  born in a wave is write-denied for life. FR-013 keeps every
  record safe, but nothing dispatches.

The old desktop-relay covered this break-glass role before it
was terminated (its repository is gone). This spec replaces
that role in a much narrower form: one private channel, one
named purpose (Syncyard's own development and recovery), one
owning chat, and no program job traffic, ever.

## Requirements

- **FR-001 — Dedicated `syncyard-dev` channel, Desktop Access
  only.** The private repository `tbitcs/syncyard-backchannel`
  carries one channel, `syncyard-dev`, at
  `channels/syncyard-dev/cmd.json`, `channels/syncyard-dev/out.json`,
  and `channels/syncyard-dev/heartbeat.json`. The channel is
  reserved exclusively for Syncyard development and recovery by
  the Desktop Access chat
  (`01e9a059-0626-4470-b012-2784f420fe5a`). No program job
  traffic, ever. No other chat or agent may post to it; other
  agents use it read-only for the status check in FR-005.

  *Acceptance*: the channel files exist at the paths above in
  the private repo; the repository is private; no program job
  has ever been sent over the channel (the agent log and the
  channel history show Syncyard development/recovery commands
  only); a command posted by any other chat is a process defect
  reported to the Desktop Access chat, not a precedent.

- **FR-002 — Backchannel independence.** The desktop agent runs
  as a WSL systemd user service, `syncyard-backchannel.service`,
  under `tpierson` on TRISTEN-DESKTOP (Ubuntu-24.04), independent
  of the Actions runners, the Syncyard tray, and the gatekeeper:
  killing any of those three does not stop it, and it keeps
  working while all three are down. It syncs the channel via the
  git protocol (clone / pull / push — no GitHub REST quota is
  burned by the poll loop), executes bash commands (which may
  invoke `powershell.exe` or `/mnt/c/...` paths for Windows-side
  recovery), writes `out.json` matched by command id, and writes
  a heartbeat on every poll cycle (poll interval ~60 seconds).

  *Acceptance*: with the tray exited and a runner lane stopped,
  the service is still `active`, the heartbeat is no older than
  two poll cycles, and a read-only test command round-trips
  (`cmd.json` in, matching-id `out.json` out, exit code 0).
  `gh api rate_limit` before and after an hour of polling shows
  the loop consumed no REST calls.

- **FR-003 — VM-side client, `backchannel/bc.py`.** A Python
  standard-library-only client with subcommands `heartbeat`,
  `status`, `send`, and `wait`. `send` packs a command file into
  `cmd.json` through the GitHub contents API — the API failsafe
  route, with no local git dependency, so it works during VM
  write waves — refuses to overwrite an unacknowledged pending
  command unless `--force` is given, stamps every command with
  a unique id and the sha256 of its body, and verifies the send
  by reading `cmd.json` back and comparing id and hash. `status`
  prints the heartbeat age, the last command id and its state,
  and the Syncyard health summary it can derive (heartbeat
  freshness, last execution result, STOP state).

  *Acceptance*: the offline unit tests in
  `backchannel/test_bc.py` pass (packing, id uniqueness, sha256,
  refuse-to-overwrite, and the force path, all against a mocked
  API layer with no network); a `send` whose read-back does not
  match fails loudly and reports not-sent; `bc.py heartbeat`
  against a heartbeat older than 5 minutes says so in plain
  terms (see FR-005).

- **FR-004 — Safety rails.** (a) Private repository only — the
  channel never moves to a public repo, and no credential is
  committed in either repo. (b) The agent executes only a
  `cmd.json` whose id differs from the last executed id; a
  replayed or re-pushed old command never re-runs. (c) A
  `channels/syncyard-dev/STOP` file halts execution — the agent
  keeps heartbeating and marks itself stopped, but runs nothing
  until STOP is removed. (d) The agent never writes gatekeeper
  queue records: queue access from the backchannel is read-only
  status unless a command from the Desktop Access chat
  explicitly directs otherwise. (e) The agent keeps a full local
  log on the desktop at `~/syncyard-backchannel/agent.log`.

  *Acceptance*: pushing the same `cmd.json` twice produces one
  execution in the log; with STOP present, a new command is not
  executed but the heartbeat keeps advancing with the stopped
  flag set; the log at `~/syncyard-backchannel/agent.log`
  records every pull, execution (id, exit code), and push.

- **FR-005 — Periodic status-check duty (fleet-wide).** Every
  agent that uses Syncyard checks Syncyard status before
  submitting desktop work, and at least once per hour during an
  active desktop campaign: the gatekeeper board (`gk status`)
  when reachable, otherwise the backchannel `heartbeat` /
  `status`. A stale heartbeat (older than 5 minutes), a down
  tray, or a down runner is reported to the Desktop Access chat
  — never worked around, never routed around silently.

  *Acceptance*: SKILL.md states the duty in the fleet-usage
  part of the skill (this change); the backchannel README
  repeats it for operators; a fleet agent that finds a stale
  heartbeat files the report to the Desktop Access chat and
  does not improvise an alternate route to the machine.

- **FR-006 — No job is lost on any Syncyard change.** Any
  deployment, upgrade, or recovery action on Syncyard (this
  backchannel included) begins with a gatekeeper queue snapshot
  — record count, the aggregate sha256 of the queue files, and
  the open-job list — and ends with reconciliation: the open-job
  set after must equal the set before, or every difference is
  named and explained to the affected program. No job may be
  lost silently.

  *Acceptance*: the change record for the deployment of this
  spec carries the before snapshot and the after reconciliation;
  any difference names the job key, its state before and after,
  and the explanation; an unexplained difference blocks the
  deployment claim.

- **FR-007 — Named recovery use cases.** The backchannel exists
  for, at minimum: (1) restart the packaged Syncyard tray in the
  owner's interactive session (the one-shot scheduled-task route
  a runner job cannot perform for itself when the tray is the
  casualty); (2) read `tray.log` and return it; (3) restart a
  runner lane; (4) run read-only network diagnostics (adapter,
  address, route, and reachability state) — the cases that
  motivated the override: a tray invisible to the owner, wired-
  interface internet loss, and runner-process elevation limits.

  *Acceptance*: each use case has a documented, pre-written
  command shape in `backchannel/README.md`; use case (2) and (4)
  are exercised read-only as part of the install verification;
  use cases (1) and (3) are exercised only on a real need or an
  owner-approved drill, and the outcome is reported to the
  owner either way.

## Claims discipline

Backchannel health is claimed from the heartbeat and the agent
log — a fresh heartbeat with a matching-id `out.json` — never
from the service merely being installed or the repository
merely existing. A recovery is claimed from the recovered
thing's own identity check (the tray process at its packaged
path, the runner listener count, the diagnostic output), never
from the backchannel command's exit code alone.

## Out of scope

- Program job traffic of any kind (FR-001) — programs keep
  using the gatekeeper, in all circumstances, including when
  the queue is long or a lane is slow.
- A general-purpose remote shell for other chats. The channel
  has exactly one poster: the Desktop Access chat.
- Replacing the gatekeeper, the runners, or the tray. The
  backchannel is the failsafe for those systems, not a second
  fleet door.
- Windows-side execution as a service. The agent is a WSL
  systemd user service; Windows-side acts go through
  `powershell.exe` invoked from its bash commands, in the
  owner's context where the command itself arranges it.
