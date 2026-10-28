# Gatekeeper — Desktop Access dispatch/watch door

The gatekeeper is the single VM-side gatekeeper for the `tbitcs/desktop-runner`
self-hosted runner fleet. Programs submit job requests to it; it alone
dispatches and watches, under the fleet standard
(`github-polling-census-and-standard-2026-10-27.md`, Parts 2 and 4). It is
files plus a CLI — no daemon. A cron-driven `gk sweep` every 5 minutes does
all API work in one batched pass.

Owner: Desktop Access & GitHub Actions program. Built 2026-10-27.

## Layout

```
gatekeeper/
  gk.py               the CLI (Python 3, stdlib only)
  queue/<job-id>.json one JSON per job (state of record per job)
  ledger.jsonl        append-only event log (submitted / adopted /
                      dispatched / state_change / watermark_breach /
                      watermark_escalation / log_harvested / ...)
  runner-watchdog.ps1 desktop-side runner watchdog (Part B; NOT installed
                      by anything in this folder - see install note)
  sweep.log           cron target for sweep stdout (created by cron line)
```

## Commands

```
python3 gk.py submit --program NAME --workflow run.yml|wsl.yml|grab.yml \
    --lane quick|normal|long|gpu --script PATH --cwd DIR \
    [--expected-min N] --key UNIQUE-KEY
python3 gk.py adopt  --run-id ID --program NAME --workflow WF \
    --lane LANE [--expected-min N] --key UNIQUE-KEY
python3 gk.py sweep
python3 gk.py status
python3 gk.py cancel <job-id-or-key>     # local only, pre-dispatch jobs
python3 gk.py pause [--reason TEXT]    # hold program dispatch; watch continues
python3 gk.py resume                   # clear a pause
python3 gk.py stop [--reason TEXT]     # hard halt: sweeps no-op until start
python3 gk.py start                    # clear stop + pause: fully running
python3 gk.py purge [--older-than-days N] [--ledger] [--yes]  # dry-run default
python3 gk.py outbox [--ack]           # pushes owed to registered chats
```

- **submit** writes a job file in state `submitted` and records the script's
  SHA-256. If an *active* job (submitted / dispatching / dispatched /
  watching) already carries the same `--key`, submit refuses and prints the
  existing job id (exit 3). This is the local half of the
  duplicate-dispatch pre-check.
- **adopt** registers an already-dispatched run for watching (no dispatch).
  Refuses if the key or the run id is already tracked by an active job.
- **sweep** (one pass, cron every 5 min):
  1. `gh api rate_limit` first (free). Core remaining **< 1,000**: dispatch
     nothing, ledger `budget_standdown`, still do the watch pass with the
     one list call. **< 500**: ledger `budget_critical` and exit — no list
     call at all.
  2. Dispatch pass over `submitted` jobs in submission order. Gates:
     same-lane serialization (one live gatekeeper job per lane), an
     identical in-flight dispatch check (same workflow + same script
     SHA-256 already holding → `dispatch_skipped_duplicate`), and a total
     cap of **2 gatekeeper-active runs** (`MAX_ACTIVE_DISPATCHED` in
     `gk.py`) until real lanes exist. Each job's state is written as
     `dispatching` *before* the `gh` call; a `dispatching` state older
     than 10 minutes with no run id is flagged `stale_dispatching` for a
     human and is never auto-redispatched. The created run id is captured
     from the URL `gh workflow run` prints, falling back to a list call
     filtered by workflow + createdAt >= dispatch time, skipping ids
     already recorded — an id that does not resolve is never latched.
  3. Watch pass: ONE `gh run list -L 50 --json` covers every tracked run.
     State changes are ledgered; a newly completed run's log is fetched
     exactly once (`gh run view --log`), its marker lines (job-printed
     lines starting with an `ALL_CAPS_` marker token) and the last 200
     log lines are stored in the job file, with
     `verdict_source="markers"`. Verdicts come from markers, never from
     the Actions conclusion alone.
  4. Watermarks (standard Part 4, pre-lane transition rule). Queued
     W1/W2 per lane: quick 10/30, normal 20/45, long 45/120, gpu 30/90
     minutes. Queued W1 is *recorded* only; queued W2 also sets a job
     flag and a `watermark_escalation` ledger event. Executing W1/W2:
     quick 5/15, normal 45/90; long/gpu use the declared expectation
     (W1 = 1.5x, W2 = 2x) floored at long 90/180, gpu 120/240 minutes.
     On an executing W1/W2 breach the sweep spends ONE extra jobs call
     to record the current step, so W2 can report step progression
     (advanced vs frozen). **A breach never cancels anything.** The
     sweep only records and escalates on paper; cancellation authority
     stays with the dispatching program's coordinator or the owner,
     per Part 4.
  5. Prints exactly one summary line, e.g.
     `SWEEP 2026-10-27T15:21:57Z budget_remaining=4297 dispatched=0 changes=6 breaches=12 active=6 waiting=1`
- **status** prints the board: counts by state, queued/running counts,
  all live jobs with lane / run status / flags, completed jobs with marker
  counts, an ISSUES section (watermark breaches, failed or pending log
  harvests, completions without a marker verdict), and the last 10 ledger
  events. `status --repo` adds project-repo health: latest CI runs, open
  Dependabot alerts, and open Dependabot pull requests (three API calls;
  the default status is local-only).
- **Logging** is two-layered: the append-only JSON ledger
  (`ledger.jsonl`, one record per event — the machine record) and a
  human-readable rotating log (`gatekeeper.log`, one line per sweep,
  1 MB with one backup). Log harvest tries `gh run view --log` first
  and falls back to the REST logs archive, recording which source
  supplied the log.
- **cancel** retires a job that has not been dispatched yet (local state
  only). It refuses for dispatched jobs and never cancels a GitHub run.
- **Lifecycle control** — `pause` holds dispatch of program jobs (the
  watch pass keeps running; jobs submitted with `--maintenance` still
  dispatch, bypassing the pause, the active cap, and lane serialization
  but never the duplicate check); `resume` clears a pause. `stop` is
  the hard halt: a sweep returns immediately — no budget spent, no
  watch, no dispatch — until `start` clears both stop and pause.
  `status` shows the control state in a banner. `purge` removes
  terminal (completed/cancelled) job records, dry-run unless `--yes`;
  `--older-than-days N` restricts it to records created more than N
  days ago, and `--ledger` also archives `ledger.jsonl` to a
  timestamped file and starts a fresh one. Job records carry the
  harvested markers and log tails — they are the evidence trail — so
  purge with an age filter is the norm, not the exception.
- **Push notifications** — `submit` and `adopt` accept
  `--notify-chat <chat-id>`. A job carrying one produces pushes —
  started (with its expected length), completed (conclusion plus
  verdict highlights from the harvested markers), W2-escalated —
  which `outbox` prints grouped by chat from the ledger (history
  from before the mechanism existed is never replayed). Delivery
  is the coordinator forwarding each group into the named chat;
  `outbox --ack` then advances the cursor. Programs register once
  and stop polling.

Known platform caveat (recorded in PROGRAM-STATUS): GitHub's run-level
status for `wsl.yml` runs has been observed frozen at `queued` while the
job's log held the complete result. The gatekeeper therefore stores the
log and markers at completion and treats markers as the verdict source;
if a wsl run's API state lags, its job file is the record to check, not
the Actions UI.

## Workflow inputs (verified against tbitcs/desktop-runner, 2026-10-27)

Checked via the repo contents API (one directory call + the grab.yml
file) and the fleet's existing clients (`~/workspace/opengen-local/
desktop-run.sh`, `desktop-wsl.sh`):

| Workflow | Inputs | Notes |
|---|---|---|
| `run.yml` | `cmd_b64` (required), `cwd` | PowerShell, base64 of script; default cwd `C:\Users\trist` |
| `wsl.yml` | `cmd_b64` (required), `cwd` | bash in WSL2, base64 of script; default cwd `/home/tpierson` |
| `grab.yml` | **`path` only** | Uploads one desktop file as artifact `grabbed-file`. **No `cmd_b64`, no `cwd`, no script.** |

The grab.yml difference matters: a grab job is submitted with
`--grab-path "<desktop file path>"` instead of `--script`. File returns
(e.g. the Glossa capture grabs) remain a manual step by the parent
program — the gatekeeper watches and harvests markers for grab runs but
does not chain grabs automatically.

## Adopted runs (registered 2026-10-27, watch + harvest only)

| Run id | Program | Workflow | Lane | Key | Origin |
|---|---|---|---|---|---|
| 40507526136 | desktop-access | run.yml | quick | win-measure-2026-10-27 | Windows measuring job (cre-work, duplicate trees, mpcodec dirs, Docker WSL data) |
| 40506702515 | desktop-access | wsl.yml | quick | wsl-inventory-2026-10-27 | WSL read-only disk inventory |
| 40512763692 | desktop-access | run.yml | quick | tool-inventory-win-2026-10-27 | Windows tool inventory (registry/winget/Scoop/paths) |
| 40512845587 | desktop-access | wsl.yml | quick | tool-inventory-wsl-2026-10-27 | WSL tool inventory |
| 40512854341 | glossa-proof | run.yml | normal | glossa-capture-indus | Glossa Chrome capture of the Indus tracker page; completion triggers manual grab.yml returns by the parent |
| 40516944590 | crscale-bench | run.yml | quick | crscale-leg0-preflight | CRScale bench LEG 0 read-only preflight (ElectroHire chat) |

## Smoke test (2026-10-27, no real work dispatched)

Rate limit snapshot before the smoke test: **core remaining 4313 / 5000**
(`gh api rate_limit`); the sweep observed **4297**.

1. Submit (throwaway script `/tmp/gk-smoke.ps1`, prints `SMOKE_TICK`):
   `SUBMITTED 20261027T152136Z-smoke-throwaway-2026-10-27-9a9dd8 key=smoke-throwaway-2026-10-27 program=smoke-test workflow=run.yml lane=quick` (rc 0)
2. Duplicate submit, same key: `REFUSED duplicate key 'smoke-throwaway-2026-10-27': active job 20261027T152136Z-smoke-throwaway-2026-10-27-9a9dd8 (state=submitted, run_id=None)` (rc 3) — as specified.
3. Adopted the six runs in the table above; all six `ADOPTED` lines
   printed, six job files written.
4. One sweep (verbatim):
   `SWEEP 2026-10-27T15:21:57Z budget_remaining=4297 dispatched=0 changes=6 breaches=12 active=6 waiting=1`
   - `dispatched=0`: the throwaway was deferred by the active-run cap
     (6 adopted runs already holding; ledger `dispatch_deferred_cap`) —
     nothing real or throwaway was dispatched by the smoke test.
   - `changes=6`: all six adopted runs took their first observed status —
     every one still `queued` (the fleet backlog is real).
   - `breaches=12`: each of the six queued runs recorded queued W1
     (record-only) + W2 (escalation flag), classification `starvation`,
     consistent with multi-hour queue waits already on the program
     record. No job was cancelled or touched — recording only.
5. Throwaway then retired locally:
   `CANCELLED (local only, nothing was dispatched) 20261027T152136Z-smoke-throwaway-2026-10-27-9a9dd8`
   so no future sweep can ever dispatch it.
6. Idempotency sweep (verbatim):
   `SWEEP 2026-10-27T15:22:16Z budget_remaining=4296 dispatched=0 changes=0 breaches=0 active=6 waiting=0`
   — zero new ledger lines (27 total), proving a repeat sweep neither
   double-dispatches nor double-records watermark breaches.
7. `gk status` shows `jobs by state: cancelled=1, watching=6`, each
   watching job flagged `watermark_queued_w2`.

## Cron (recommended — the parent registers it)

```
*/5 * * * * /usr/bin/env python3 /home/hatch/workspace/desktop-access-migration/gatekeeper/gk.py sweep >> /home/hatch/workspace/desktop-access-migration/gatekeeper/sweep.log 2>&1
```

Every 5 minutes matches the fleet poll floor; the sweep self-locks, so
an overlapping invocation is a no-op.

## Desktop runner watchdog — install note (owner session, do NOT run from an Actions job)

`runner-watchdog.ps1` ships in this folder as a file only. It is
installed during the lanes owner session on TRISTEN-DESKTOP:

1. Copy `runner-watchdog.ps1` to `C:\actions-runner-watchdog\runner-watchdog.ps1`
   on the desktop.
2. At lane stand-up, extend the `$RunnerDirs` config array at the top of
   the script with the lane directories (`C:\actions-runner-quick`,
   `C:\actions-runner-normal`, `C:\actions-runner-gpu` as registered).
   It ships configured for the incumbent `C:\actions-runner-desktop`
   only.
3. Create the every-5-minutes user scheduled task (run in Tristen's own
   session, PowerShell):

```
schtasks /Create /TN "RunnerWatchdog" /SC MINUTE /MO 5 /RU trist /RL LIMITED /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\actions-runner-watchdog\runner-watchdog.ps1"
```

Behavior: for each configured runner dir, if no `Runner.Listener.exe`
process lives under that dir and `run.cmd` exists, it starts `run.cmd`
via `Start-Process` (the task context is not an Actions job, so the
listener survives). Restart cap **3 per runner per rolling hour**;
past the cap it writes `OWNER NEEDED` to the log and status and stops
restarting that runner. Every run writes
`C:\actions-runner-watchdog\status.json` (per-runner: dir,
listener_alive, last_action, owner_needed, checked_at) and appends to
`C:\actions-runner-watchdog\watchdog.log`. The script is ASCII-only
(Windows PowerShell 5.1 mis-parses non-ASCII UTF-8-no-BOM scripts — a
recorded fleet lesson).

## What the gatekeeper does NOT do yet

- **No real lanes.** The runner workflows take no lane input until
  LANES-STANDUP step 4 lands; all dispatches still land on the single
  incumbent runner. `lane` here is gatekeeper-side classification and
  serialization only.
- **No webhook push.** Watching is the 5-minute batched sweep. Phase 2
  is push via `gh webhook forward` to cut polling further.
- **No cancellation, ever.** Watermark breaches are recorded and
  flagged; the check-before-cancel ladder's human steps and any
  cancellation stay with the dispatching program / the owner.
- **No automatic grab chaining.** grab.yml returns (e.g. Glossa's
  capture files) are dispatched manually; the gatekeeper watches those
  runs like any other.
- **No probe jobs.** Part 4 step-3 machine-state probes are a
  coordination decision, not something the sweep fires on its own.
