---
name: syncyard
description: Dispatch and watch jobs on the operator's own machines through the Syncyard gatekeeper (AXIOVEX/syncyard) — self-hosted GitHub Actions runner lanes with a shared API budget. Use whenever work must run on the operator's desktop or laptop: builds, probes, renders, hardware sessions, file returns. Covers submit/adopt/status, lane routing, marker verdicts, API discipline, and watermark escalation etiquette.
---

# Syncyard — agent skill

Syncyard is the one door between agents and the operator's own machines.
Programs do not dispatch GitHub Actions workflows directly, and they never
poll runs on their own. They submit job requests to the **gatekeeper**
(`gatekeeper/gk.py`), which dispatches within the shared API budget,
assigns lanes, watches every run in one batched sweep, and records
verdicts. If you are an agent with work for the operator's machines, work
through the gatekeeper.

Repository: `AXIOVEX/syncyard`. The live gatekeeper copy runs on the
operator's control machine and tracks this repository's releases.

## Keeping this skill current (standing rule)

**This file is updated in the same change as any change to behavior,
commands, lanes, workflows, or operations.** A change that leaves
this skill stale is incomplete. The project is governed by spec-kit
+ AEE: a constitution (`.specify/memory/constitution.md`) and
numbered specs under `specs/`, each requirement a claim with
evidence and a falsification test. Changes cite the spec they
implement; behavior with no spec gets a spec in the same change.

## Commands

```bash
GK="python3 gatekeeper/gk.py"

# Submit a Windows PowerShell job
$GK submit --program <your-program> --workflow run.yml \
    --lane <quick|normal|long|gpu> --script <script.ps1> \
    --cwd '<windows cwd>' [--expected-min N] --key <unique-key>

# Submit a WSL2 bash job
$GK submit --program <your-program> --workflow wsl.yml \
    --lane <lane> --script <script.sh> --cwd '<wsl cwd>' \
    [--expected-min N] --key <unique-key>

# Return one file from the machine as an artifact (no script; path only)
$GK submit --program <your-program> --workflow grab.yml \
    --lane quick --grab-path '<path on the machine>' --key <unique-key>

# Register a run that was dispatched outside the gatekeeper (watch only)
$GK adopt --run-id <id> --program <your-program> --workflow <wf> \
    --lane <lane> --key <unique-key>

# The board: every tracked job, its state, flags, and verdict markers,
# plus queued/running counts and an ISSUES section (see below)
$GK status

# The board + project-repo health: latest CI, open Dependabot alerts
# and PRs (three API calls; the default status above is local-only)
$GK status --repo

# Hold ALL program dispatch (the watch pass keeps running, so verdicts
# and watermarks stay current; jobs already dispatched are untouched —
# the gatekeeper never cancels). Operator maintenance jobs submitted
# with --maintenance still dispatch during a pause.
$GK pause --reason "WSL cleanup + compact"
$GK resume

# The hard halt: sweeps no-op entirely (no budget spent, no watch)
# until started again. Start clears both a stop and a pause.
$GK stop --reason "fleet maintenance"
$GK start

# Housekeeping: remove terminal (completed/cancelled) job records.
# Dry-run unless --yes; job records carry the harvested evidence, so
# purge with an age filter. --ledger also archives the ledger.
$GK purge --older-than-days 7
$GK purge --older-than-days 7 --yes
```

- Every job carries a **unique `--key`**. Submitting a key that is already
  active is refused and prints the existing job — that refusal is the
  duplicate-dispatch pre-check working. Never work around it by changing
  the key for the same work; check `gk status` instead.
- `--expected-min` matters for `long` and `gpu` jobs: health watermarks
  are judged against the declared expectation before lane defaults.
- `gk cancel <id-or-key>` is local bookkeeping for jobs that were never
  dispatched. It never cancels a GitHub run. There is no command in this
  system that cancels a running job on a timer — see escalation below.
- The status board's **ISSUES** section is the operator's problem
  list: watermark breaches and escalations, log harvests that failed
  or are still pending, a dispatch stuck needing a human, and
  completions with no marker verdict. Read it before concluding the
  fleet is healthy.
- **Logging is two-layered**: `ledger.jsonl` (append-only JSON, one
  record per event — the machine record) and `gatekeeper.log` (one
  human-readable line per sweep, rotating at 1 MB). At completion the
  sweep harvests a run's log once; if the CLI read fails it falls
  back to the REST logs archive and records which source supplied
  the log.
- A **daily health check** reviews the board, the ledger's errors,
  CI on main, and Dependabot. Green Dependabot patch/minor bumps of
  GitHub Actions are merged by the check; major bumps are reported
  to the operator, never merged.
- **Pause** (`gk pause` / `gk resume`) holds dispatch of program
  jobs while the operator works on the machines themselves. Status
  shows the pause banner with its reason; sweeps print PAUSED.
  Maintenance submissions (`submit --maintenance`) bypass the pause,
  the active cap, and lane serialization — never the duplicate
  check. Use maintenance only for operator work on the fleet itself
  (cleanup, repair, inventory), never for program jobs.
- **Stop and start** (`gk stop` / `gk start`) are the hard lifecycle
  controls: while stopped, a sweep returns immediately — no API
  budget spent, no watch pass, no dispatch — and status shows the
  STOPPED banner. `start` clears both a stop and a pause. Neither
  state ever touches jobs already dispatched.
- **Purge** (`gk purge`) removes terminal (completed/cancelled) job
  records — dry-run unless `--yes` is passed. `--older-than-days N`
  restricts it to records created more than N days ago;
  `--ledger` also archives `ledger.jsonl` and starts a fresh one.
  Records hold harvested markers and log tails, so age-filtered
  purges are the norm.

## Lane routing

Every dispatch declares a lane. **No lane declared = not dispatched.**

| Lane | Expected duration | Use for |
|---|---|---|
| `quick` | under ~2 min | probes, status checks, small transfers |
| `normal` | ~2–30 min | builds, installs, packaging |
| `long` | over ~30 min, or unknown | batch stages, scoring runs, renders |
| `gpu` | any duration | any job that needs a GPU |

- **GPU overrides duration.** A 30-second GPU probe goes to `gpu`, never
  to `quick`. A long GPU render goes to `gpu`, never to `long`.
- **Unknown duration goes to `long`.**
- A job that overruns its lane's norm twice gets re-laned in its program's
  briefs (quick → normal, normal → long), and the overrun is reported.
- Detached background processes on a machine are not Actions jobs and do
  not take a lane; the status checks *about* them are `quick` jobs.
- Jobs expected to exceed 60 minutes are announced to the coordination
  point before dispatch, with their expected duration.

## Marker verdicts

**A job's verdict comes from the marker lines it prints in its own log —
never from the GitHub Actions success color alone.** Platform run status
has been observed frozen at "queued" long after a job's log held its
complete result; the log is the record.

- Write every job script to print unambiguous marker lines with its
  results, for example `PROBE_DONE gpus=2 free_gb=212` or
  `BUILD_VERDICT: PASS`. Markers are lines that begin with an
  `ALL_CAPS_` token; the gatekeeper harvests exactly those.
- Read verdicts from `gk status` (completed jobs show their marker
  counts) or from the job file the gatekeeper keeps, not from the
  Actions web UI.
- A run that "failed" according to a client printout but whose markers
  say otherwise gets cross-checked against the actual job log before
  anyone believes either.

## API discipline

The GitHub REST quota (5,000 calls/hour) is one account-wide bucket
shared by every program. The gatekeeper exists so the fleet spends it
once, centrally. Your obligations:

- **Never poll a run yourself.** The gatekeeper's sweep (every
  5 minutes) is the only watcher. If you truly must look, one batched
  `gh run list` covering all your runs, no faster than every 3–5
  minutes — never a per-run loop, never `gh run watch` left running
  (its default interval is ~3 seconds).
- **Before any burst of API calls** (more than ~10), run
  `gh api rate_limit` — the endpoint is free. Core remaining **below
  1,000**: stand down to minimum cadence and say so in your report.
  **Below 500**: completion-critical calls only, at most one per
  5 minutes.
- **A 403 rate-limit response is a hard stop** for that scope. Stop, do
  not retry through it, report the rate-limit snapshot and reset time.
  Resume only after the reset *and* a fresh headroom check.
- Dispatch only needed jobs. No speculative duplicates; cancel your own
  superseded queued work through your coordinator.

## Watermarks and escalation etiquette

Each lane has warning watermarks for queue wait and execution time
(the table is in docs/STANDARD.md). The gatekeeper records breaches; it
**never cancels anything**. Your conduct when a breach involves your job:

- **Queued breach = starvation.** Your job is the victim, not the
  problem. Never cancel it. The lane ahead of it is what gets escalated.
- **Executing breach = stall suspect.** Check step progression in the
  record: a job whose step advanced is slow, not stalled — say so and
  stand down to second-warning watch.
- If machine state is needed to tell slow from wedged, that takes a
  quick-lane probe job (process list, GPU state, disk, venue log tail).
  A probe that never returns reclassifies the event as a machine-level
  problem.
- Escalate to the coordination point at the second warning, with the
  evidence: run id, lane, dispatch time, watermark breached, signals
  observed, probe result.
- **Cancellation authority is narrow:** only your own program's
  coordinator, after a recorded check — or the owner. Never another
  program's watcher, never automatically, never for a queued breach.
  A cancelled job is cancelled *with its check record attached*, so it
  can be re-dispatched from a known state.

## Board (hardware) scenario jobs

Jobs that touch physical hardware (development boards on a bench
station) follow an extra discipline on top of everything above:

- They run **one at a time under a claim**: the job registers its claim
  before its first hardware step and releases it with actual times when
  done. A conflicting active claim holds the job; claims are never
  silently stacked.
- The first step is always a **reachability and identity proof** in the
  execution context that can actually reach the hardware (some networks
  are visible only from a specific user environment on the machine, not
  from the runner's default context). Failure aborts before any claimed
  act.
- Safety gates that protect the hardware are **hard steps inside the
  job**: a failed gate aborts before any step that depends on it.
- Physical acts are **exactly-once**: jobs are idempotent or check a
  consumed-marker before repeating an act.
- Steps only a human can do (power cycles, cable moves) are terminal
  states: the job stops and reports "human step required". No retry
  loops against physical hardware.
- The job **harvests before it exits**: all logs and captures are copied
  off the device before the job ends; results left only on the device
  mean the job failed.

## Break-glass

The operator keeps a separate, frozen emergency admin path outside
Syncyard, for the case where the Actions route itself is broken. It
carries **no job traffic, ever** — not for convenience, not for speed,
not because the queue is long. If you believe the emergency path is
genuinely needed (the gatekeeper cannot dispatch and the runners cannot
be reached), stop, say exactly that, and let the owner decide. Do not
improvise alternate routes to the machines.

## Security rules that bind agents too

- The runner workflows are **dispatch-only** (`workflow_dispatch`).
  Never propose, write, or merge a workflow that binds self-hosted
  runners to `pull_request`, `pull_request_target`, `issues`, or any
  event an untrusted user can trigger.
- CI runs on GitHub-hosted runners only.
- Never commit a token or credential anywhere in this repository.
  Registration tokens are fetched at setup time and used once.
- Runners register to this repository only, never organization-wide.
