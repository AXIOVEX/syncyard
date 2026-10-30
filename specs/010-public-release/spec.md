# Feature Specification: Public Release — Configurability, Host Matrix, Agent Skills

**Feature Branch**: `spec-010-public-release`

**Created**: 2026-10-30

**Status**: **Specified; implementation begins with this change.**
This spec turns Syncyard from a single-fleet tool, hardwired to
one owner's desktop, chats, and repositories, into a general
open-source project other people — and other people's agents —
can adopt: a real configuration system, a tested host matrix
(Windows, WSL2, macOS, Linux, Docker), a hardened failsafe
backchannel, and an agent-skills pack with Meta Muse as the
primary vehicle.

**Direction (owner, 2026-10-30 ~08:30 ET)**: "go, and we
should add much more configurability like how many lanes and
other things like that and keeping the backup backchannel
always robust and solid. we should also create skills.md for
various chat agents and champion Meta Muse as the primary
vehicle since that is my daily work. Also add more knobs that
will be helpful for others. make sure this tool is great at
connecting to Windows, MacOS, Linux, and any of those hosts'
VMs like WSL2 on Windows and Docker and stuff. We will need
tests for all these things as well." And, as a named later
possibility: "eventually pitching this to GitHub (the company)
to see if they could see adopting this into gh cli."

## The gap

Syncyard works — 440+ production jobs in its first three days,
zero jobs lost through host write-corruption waves, an API
budget discipline that ended a real quota outage — but it only
works *here*:

- Lane count and names, the door and project repositories, the
  runner directories, the watermark tables, the budget
  thresholds, and the notification targets are constants in
  gatekeeper code or conventions in one fleet's memory. An
  adopter must edit source to change any of them.
- The host story is one Windows desktop with WSL2. macOS,
  native Linux, and Docker venues exist only as folklore.
- The backchannel is proven live but young: no self-test, no
  stale-heartbeat alarm surface, no chaos battery.
- There is no skills pack. Every agent that drives Syncyard
  today learned it from one fleet's internal documents; an
  outside agent has no contract to program against.
- Testing is deep where the scars are (FR-013 battery,
  backchannel unit tests) and absent where they aren't (config,
  hosts, tray on a clean machine).

## Requirements

### FR-001 — One configuration file is the source of truth
A single documented config file (`syncyard.yaml`, with a
checked-in example) carries: door repo, project repo, host
definitions, lanes, watermarks, budget thresholds and
stand-down floors, poll cadences, notification endpoints,
default working directories per host, log retention, and the
script-transport size ceiling. The gatekeeper, the sweep, and
the tray read configuration from it; code constants remain
only as defaults when a key is absent. The fleet's current
production configuration, expressed in the file, reproduces
today's behavior exactly (golden-tested, FR-008).

### FR-002 — Lanes are configuration, not code
Lane count, names, per-lane concurrency (default: serial),
runner-label mapping, and per-lane watermark tables are all
config. Validation rejects duplicate names, unknown host
references, and watermark tables whose warn level meets or
exceeds their escalate level. Adding a lane is a config change
plus a runner registration, never a code change.

### FR-003 — Host matrix: Windows, WSL2, macOS, Linux, Docker
A host is a typed venue: `windows`, `wsl2` (a named distro
inside a Windows host), `macos`, `linux`, or `docker` (a named
image run on any host). Each host type defines: how its runner
registers, its job transport workflows (execute + file-return),
its identity markers (host, user, OS, session), and its
process-teardown semantics. Jobs name a host the way they name
a lane today; the gatekeeper routes by config.

### FR-004 — VM and container venues are first-class
WSL2 jobs ride the Windows host's runner (today's wsl.yml,
generalized and named). Docker jobs execute inside a
caller-specified image with declared mounts and result return
through the same grab mechanism. A VM guest reachable only
through its host is modeled as a host of its own type with a
documented reachability path. No venue may silently fall back
to another: a job runs where it was addressed or fails loudly.

### FR-005 — The backchannel stays always robust and solid
The failsafe backchannel (spec 009) is a permanent, supported
component, not a one-off: the agent gains a start-up self-test
(service state, channel reachability, log writable) whose
result rides in the heartbeat; `gk status` surfaces heartbeat
age with a stale alarm (>5 min) by default; the documented
recovery runbook (spec 009 FR-007 cases) ships in the repo;
and the chaos battery (FR-008) covers agent kill/restart,
corrupt cmd.json, duplicate command ids, and STOP behavior.
The channel's exclusivity rule is unchanged: Syncyard
development and recovery only, never program job traffic.

### FR-006 — Agent skills pack, Meta Muse first
A `skills/` tree ships versioned SKILL.md packages that teach
an agent to drive Syncyard: submit, watch by markers (never by
run color), read status, respect the API discipline, and use
the backchannel only for Syncyard recovery. The primary,
first-class package targets **Meta Muse** (the owner's daily
vehicle); sibling packages adapt the same contract to other
agent hosts (a generic-agent edition and a CLI-only edition
that assumes nothing but `gh` and the gatekeeper CLI). Every
skill states the security invariant (FR-009) verbatim.
Skills are release artifacts: a behavior change to Syncyard
updates the affected skill in the same change (the standing
SKILL.md currency rule, generalized).

### FR-007 — Knobs an adopter actually needs
Beyond lanes and hosts: expected-duration defaults per lane,
the job soft cap, duplicate-submission policy (refuse /
allow-with-key), outbox delivery endpoints abstracted from
chat ids (named endpoints of type chat, webhook, file, or
command), marker regex, queue/ledger retention and rotation,
budget reserve for completion-critical calls, and the chunked
transport helper shipped as a tool (the fleet's proven answer
to the workflow-input size ceiling). Every knob is documented
in the example config with its default and its failure mode.

### FR-008 — Tests for all of it
Each requirement carries a named test: config golden tests
(today's fleet config → today's behavior, byte-compared queue
effects on fixtures); lane validation tests; per-host smoke
batteries (execute + grab + identity markers) runnable in CI
on hosted runners for linux, macos, and windows, with WSL2 and
Docker legs runnable on a self-hosted venue and marked as
such; the backchannel chaos battery; the existing FR-013 and
bc.py batteries keep passing. A release with a red battery
does not ship.

### FR-009 — Security posture is a shipped document
`SECURITY.md` (or its docs equivalent) states the invariant
plainly: runners are reachable only via `workflow_dispatch`
from the gatekeeper; no workflow may bind self-hosted labels
to pull_request, pull_request_target, or issue events; the
door repository is private; the backchannel repository is
private; adopter checklists for token scoping and runner
isolation. The README links it above the quickstart.

### FR-010 — Public polish and the 0.3.0 release
README tells the story in two minutes (the problem, the scars
that shaped the design, what it deliberately doesn't do),
quickstarts exist per host type, CHANGELOG covers the
generalization, and VERSION moves to 0.3.0 when FR-001..009
are implemented and green. No marketing claims the tests
don't back.

### FR-011 — GitHub pitch readiness (later phase, named)
A pitch brief lives in `docs/github-pitch.md`: the problem as
GitHub would see it (agent fleets driving self-hosted runners
safely), the realistic adoption shape (a `gh` extension first —
`gh syncyard` — not a core merge), the design constraints
Syncyard already satisfies, and what would need to change.
Prepared under this spec; **sent only on the owner's explicit
word**, which has not been given.

## Non-goals

- No rewrite of the gatekeeper core. Its semantics (queue
  records, exactly-once dispatch, marker verdicts, safe writes)
  are the battle-tested asset; this spec generalizes its
  inputs, not its engine.
- No multi-machine pooling or runner autoscaling. Syncyard is
  for one owner's machines, deliberately.
- No new trigger surfaces for self-hosted runners. The
  dispatch-only invariant (FR-009) outranks convenience.
- No pitch, outreach, or submission to GitHub under this spec
  (FR-011 is preparation only).

## Success criteria

- A fresh adopter, on any host type in FR-003, goes from clone
  to a first job with markers back in under an hour, using
  only the shipped docs.
- The production fleet runs on the config file with zero
  behavior change (golden tests + a live reconciliation in the
  FR-006-of-spec-009 shape: queue snapshot before, set equality
  after).
- Every battery in FR-008 is green in CI for the 0.3.0 tag.
