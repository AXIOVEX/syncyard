# The Syncyard fleet standard

How a fleet of programs shares one GitHub account and a small set of
personal machines without starving either. Three parts: the API budget,
the runner lanes, and job health.

This standard was not designed in the abstract. It was written after a
measured incident on the founding deployment: several programs
dispatching and polling at once exhausted the account's GitHub API
quota in a single morning, and a status probe waited about 75 minutes
in a runner queue behind one long job. The numbers below come from that
measurement pass; the rules are what the fleet adopted in response.

## Part 1 — The API budget

The GitHub REST quota is **5,000 calls per hour, account-wide**. Every
program, agent, and script on the account draws from the same bucket.
GraphQL is a separate, much less loaded bucket; the pressure is all
REST.

1. **One watcher per run.** Only the dispatching program polls its run.
   Nobody else polls it "to check." Under Syncyard, the gatekeeper is
   that watcher for everything it tracks.
2. **Poll floors.** No faster than every **180 seconds** while a run is
   queued, and every **300 seconds** while it executes — a 3–5 minute
   minimum for all runner and API watching. Never leave `gh run watch`
   running unattended at its default ~3-second interval. Prefer **one
   batched call** (`gh run list` covering all your runs) over per-run
   calls. At these floors, one watching program costs roughly 12–20
   calls per hour.
3. **Check headroom before bursts.** Before any planned burst (more
   than ~10 calls), run `gh api rate_limit` — the endpoint itself is
   free. Core remaining **below 1,000**: stand down to minimum cadence
   and say so in your report. **Below 500**: completion-critical calls
   only, at most one per 5 minutes.
4. **Fleet budget.** Treat 4,000 calls/hour as the fleet's soft cap and
   hold ~1,000/hour in reserve for interactive and owner use. If
   several programs poll concurrently, each stays within its poll-floor
   budget; a program running more than 3 simultaneously polling legs is
   the anomaly — flag it to coordination instead of letting it
   compound.
5. **Runner etiquette.** Dispatch only needed jobs. First spend one
   `gh run list` call to check for an identical in-flight dispatch of
   yours — speculative duplicates are measured waste. Cancel your own
   superseded queued jobs promptly. Soft cap: 30 minutes of execution
   per job; chunk longer work with checkpoint/resume. Any job expected
   to exceed 60 minutes is announced to coordination before dispatch,
   with its expected duration.
6. **Batch reads.** Prefer bulk endpoints over per-item loops. The
   pattern that works: one call that lists everything, then fetches
   only what changed.
7. **On exhaustion, stop.** A 403 rate-limit response is a **hard stop**
   for that scope. Do not retry through it. Report the rate-limit
   snapshot and the reset time. Resume only after the reset *and* a
   headroom check; a scheduled post-reset resumption is the preferred
   shape. A program that hits a 403 twice in one day drops to a
   300-second cadence for the rest of the day and tells coordination.

**Headline numbers:** quota 5,000/hour · stand down below 1,000
remaining · poll floors 180 s queued / 300 s executing · fleet soft cap
4,000/hour with 1,000/hour reserve · job soft cap 30 min · announce
anything expected over 60 min.

## Part 2 — Runner lanes

A single self-hosted runner executes **one job at a time**. Put every
job shape in one line and the line's order becomes the fleet's
schedule: in the founding measurement, completed runs' start-to-finish
spans reached about two hours — almost all of it queue wait, on a
machine that was not slow. A two-minute probe waited ~75 minutes
behind a ~90-minute job. Lanes fix the *ordering*, not the machine.

Four runner registrations per machine, each its own directory, each
running as a user-window process under the owner's own account (never
another profile), each serial within itself:

| Lane | Label | Expected duration | Carries |
|---|---|---|---|
| quick | `lane-quick` | under ~2 min | probes, status checks, small transfers |
| normal | `lane-normal` | ~2–30 min | builds, installs, packaging, mid-length tasks |
| long | `lane-long` | over ~30 min, or unknown | batch stages, scoring runs, renders |
| gpu | `lane-gpu` | any duration | any job needing a GPU |

Routing rules:

1. Every dispatch declares its lane by label. **No lane declared = not
   dispatched.**
2. **GPU need overrides duration.** A long GPU job goes to `gpu`, never
   to `long`; a quick GPU probe goes to `gpu`, never to `quick`.
3. **Unknown duration routes to `long`.**
4. A job that overruns its lane's norm **twice** is re-laned in its
   program's briefs (quick → normal, normal → long), and the overrun is
   reported, not silently absorbed.
5. Lanes govern **dispatched jobs only**. Detached processes — launched
   once and left running on a machine under their own supervision —
   stay outside Actions entirely. The status checks *about* them are
   quick-lane jobs.
6. Part 1's etiquette carries into every lane.

The GPU lane is a **single serial lane on purpose**, even on a machine
with two graphics cards: GPU jobs never run concurrently, so they never
contend for video memory, never split it unpredictably, and never push
each other out of memory. The price is throughput — a short GPU probe
waits behind a long render. Splitting into per-card GPU lanes is a
later option only if run lists show real queue pain from small GPU
jobs.

**Honest limit.** Lanes give queue isolation, not more compute. Four
lanes running heavy jobs at once still contend for the machine's CPU,
memory, and disk. A lane guarantees a quick job is never stuck *behind*
a long job in line; it does not guarantee the quick job a fast machine
while the long jobs run. The announce-over-60-minutes rule and
coordination remain the backstop for genuinely large simultaneous
work.

**Fallback.** If four registrations prove heavier to run than the
isolation is worth, the evidence strictly requires three: `gpu`,
`quick`, and `long`, with the normal class folded into `long`. The
`normal` lane rests on the 30-minute job cap rather than on a measured
starvation of its own; it can also be split out of `long` later if run
lists show mid-length waits.

Each lane is **proven with an identity job** (a dispatch whose log
prints the machine name and the user it ran as) before the first real
dispatch routes to it.

## Part 3 — Job health: watermarks and check-before-cancel

Tasks that should be fast must be **checked before pulling the plug**.
The governing principle: **a watermark breach is a check trigger, never
an automatic cancel.** Nothing in this standard authorizes any watcher
to cancel any job on a timer. Watermarks exist to start a recorded
check while intervention is still cheap.

Watermarks are evaluated at the watcher's normal polls (Part 1 floors),
so worst-case detection lag after a breach is one poll interval. No
extra polling is created by this part — health rides the polls that
already exist.

### 3.1 Watermarks per lane

Two levels per lane: **W1** (first warning — the watcher runs the check
ladder) and **W2** (second warning — escalate to coordination with the
evidence).

| Lane | Queued W1 | Queued W2 | Executing W1 | Executing W2 |
|---|---|---|---|---|
| quick (under ~2 min) | 10 min | 30 min | 5 min | 15 min |
| normal (~2–30 min) | 20 min | 45 min | 45 min | 90 min |
| long (over ~30 min) | 45 min | 2 h | declared expectation + 50% (floor 90 min) | 2× declared expectation (floor 3 h) |
| gpu (any duration) | 30 min | 90 min | declared expectation + 50% (floor 2 h) | 2× declared expectation (floor 4 h) |

- **Declared expectation wins.** A job dispatched with an expected
  duration is judged against it, not the lane default — a render
  announced at 95 minutes does not false-alarm at a generic threshold.
- **Transition rule.** On a single un-laned runner, long queued waits
  are normal operation — that is the problem lanes exist to remove.
  Until lanes stand up, treat **queued W2** (not W1) as the escalation
  line, and record W1 breaches without acting on them, so the
  transition produces data rather than alarm fatigue.
- Dispatchers of long/gpu jobs should treat declaring an expectation
  as part of the dispatch.

### 3.2 What is actually visible

**Through the API, within the existing poll discipline:**

- **Run and job state and timestamps.** A queued job whose state never
  advances is starvation-visible; an executing job whose record stops
  changing across consecutive polls is a first stall hint.
- **Step progression.** The jobs endpoint exposes each step's status;
  the current in-progress step changes as a job advances. **A step
  frozen across two consecutive polls is the primary stall signal** —
  it costs no extra calls; the watcher records the current step at each
  poll and compares.
- **Runner state.** The runners endpoint reports each runner `online`
  and `busy`: a queued breach with the lane's runner *offline* explains
  the starvation in one read; *online + busy* means the lane is working
  on something ahead; *online + not busy* while a job sits queued is
  itself an anomaly (a dispatch or label mismatch) worth escalating
  as-is.

**Not exposed by GitHub — requires eyes on the machine:**

- **Live log tails of in-progress jobs.** The API serves logs for
  completed jobs only. A watcher cannot tail a running job's log
  through the API. Exception: jobs that write their own log and marker
  files on the machine — those tails are readable by a probe job or a
  status job.
- **Machine state.** Process list, CPU, GPU use and memory, disk
  headroom, whether a worker process is alive, spinning, or dead —
  none of it is in any GitHub response. Getting it requires a
  **quick-lane probe job** on the machine itself (a tiny dispatched job
  that prints process/GPU/disk state and any machine-side log tails).
  The probe is itself a queued job, and that is useful: if it answers,
  the problem is at job level; if it never runs, the problem is the
  runner or the machine — escalate to coordination and the owner, not
  to the job.

### 3.3 The check-before-cancel ladder

Run by the run's own watcher when a watermark breaches. Each step is
recorded (see 3.4) before the next is taken.

1. **Re-read.** At the breach, re-read the run/job state in the next
   batched poll — no special burst. Many apparent stalls are a poll
   that raced a step boundary; the re-read separates a real breach from
   a sampling artifact.
2. **Classify.** Two different diseases, two different responses:
   - *Queued breach = starvation.* The waiting job is not the problem;
     the lane or queue ahead of it is. Check the lane runner's state in
     the same read. **Never cancel the victim.** Escalate the *lane* to
     coordination — the blocker may be another program's job, and
     moving it is coordination's call, not the victim's watcher's.
   - *Executing breach = stall suspect.* Compare step progression
     across the recorded polls. If the step advanced inside the window,
     the job is slow, not stalled: record "slow-not-stalled", stand
     down to W2 watch. If the step is frozen, continue to step 3.
3. **Probe** (only when the distinction needs machine state). Dispatch
   a quick-lane probe. Its result distinguishes alive-but-slow (process
   running, GPU busy, log advancing) from dead/wedged (no process, GPU
   idle, log frozen at an old line). Probe non-return reclassifies the
   event as runner/machine-level.
4. **Notify the dispatching program.** At W1 the watcher records the
   breach and its check outcome in the program's own reporting, the
   moment the check completes. A breach must never exist only in a
   transient message.
5. **Escalate at W2.** If the breach reaches W2 unresolved — or at W1
   when the classification is machine-level, or another program's job
   is the blocker — the watcher notifies coordination with the evidence
   pack: run id, lane, dispatch time, watermark breached, signals
   observed, probe result. Past W2, silence is the failure mode this
   part exists to prevent.
6. **Cancellation — authority, narrowly held.** A job is cancelled
   only by (a) the dispatching program's own coordinator, after the
   check above is recorded, or (b) the owner. Never by another
   program's watcher; never automatically; never for a queued breach.
   A cancelled-because-stalled job is cancelled *with its check record
   attached*, so the kill is auditable and the job's owner can
   re-dispatch from the recorded state (checkpoint/resume per Part 1
   rule 5) instead of from a mystery.

### 3.4 What gets recorded

Every watermark breach and its outcome lands in the watching program's
run report (and, for cancellations, in the dispatching program's own
records with the outcome appended):

- the breach: run id, lane, watermark level (queued/executing × W1/W2),
  breach time, how long the job had been in that state;
- the signals: step progression across the window, runner state, probe
  result if one was dispatched;
- the classification: starvation / slow-not-stalled / stalled /
  machine-level;
- the action: none (stood down) / escalated to coordination /
  cancelled — and if cancelled, by whom, and from what recorded state
  it can be re-dispatched.

A killed or rescued job is never a silent event, and a job that was
checked and left running carries the check with it — the next watcher
inherits the record, not a rumor.
