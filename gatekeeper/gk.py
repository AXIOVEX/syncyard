#!/usr/bin/env python3
"""gk.py - Sallyport gatekeeper: the single dispatch/watch door for the
AXIOVEX/sallyport self-hosted runner fleet.

Implements the Sallyport fleet standard (docs/STANDARD.md, Parts 2 and 4):
  - one watcher (this tool, via a 5-minute cron sweep), batched reads
  - gh api rate_limit headroom check before any dispatch; hard stand-down
    below 1,000 core remaining, completion-critical only below 500
  - duplicate-dispatch pre-check (local --key + same script hash in flight)
  - lane serialization on this side until real lanes stand up
  - Part 4 watermarks are RECORDED, never acted on: this tool never cancels
    any run, ever.

State lives in files next to this script:
  queue/<job-id>.json   one JSON per job
  ledger.jsonl          append-only event log

Python 3 stdlib only.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
QUEUE_DIR = os.path.join(BASE, "queue")
LEDGER = os.path.join(BASE, "ledger.jsonl")
LOCK_DIR = os.path.join(BASE, ".sweep.lock")

REPO = "AXIOVEX/sallyport"

# --- Config constants (edit here, nowhere else) ---------------------------
MAX_ACTIVE_DISPATCHED = 2        # total gatekeeper-active runs cap, pre-lanes
STANDDOWN_REMAINING = 1000       # below this: no dispatch (standard Part 2.3)
CRITICAL_REMAINING = 500         # below this: no list call either
STALE_DISPATCHING_MIN = 10       # dispatching state older than this = human flag
LOCK_STALE_MIN = 10
WORKFLOWS = ("run.yml", "wsl.yml", "grab.yml")
LANES = ("quick", "normal", "long", "gpu")
DEFAULT_CWD = {"run.yml": r"C:\Users\trist", "wsl.yml": "/home/tpierson",
               "grab.yml": None}

# Part 4 watermark tables, minutes: lane -> (W1, W2)
QUEUED_WM = {"quick": (10, 30), "normal": (20, 45), "long": (45, 120),
             "gpu": (30, 90)}
EXEC_WM_FIXED = {"quick": (5, 15), "normal": (45, 90)}
# long/gpu executing: declared expectation wins, floored.
EXEC_WM_FLOOR = {"long": (90, 180), "gpu": (120, 240)}

# States in which a job blocks a duplicate --key and holds its lane.
ACTIVE_STATES = ("submitted", "dispatching", "dispatched", "watching")
# States holding a live run on the runner (lane gate / active cap).
RUN_HOLDING_STATES = ("dispatching", "dispatched", "watching")

MARKER_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}([ :]|$)")


# --- Small helpers ---------------------------------------------------------

def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return now_dt().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None


def minutes_between(a, b):
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 60.0


def ledger(event, **kw):
    rec = {"ts": now_iso(), "event": event}
    rec.update(kw)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def job_path(job_id):
    return os.path.join(QUEUE_DIR, job_id + ".json")


def save_job(job):
    fd, tmp = tempfile.mkstemp(dir=QUEUE_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(job, f, indent=2, sort_keys=True)
        os.replace(tmp, job_path(job["id"]))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_jobs():
    jobs = []
    if not os.path.isdir(QUEUE_DIR):
        return jobs
    for name in sorted(os.listdir(QUEUE_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(QUEUE_DIR, name), encoding="utf-8") as f:
                jobs.append(json.load(f))
    return jobs


def new_job_id(key):
    slug = re.sub(r"[^a-z0-9-]+", "-", key.lower()).strip("-")[:48] or "job"
    return "%s-%s-%s" % (now_dt().strftime("%Y%m%dT%H%M%SZ"), slug,
                         uuid.uuid4().hex[:6])


def run_cmd(args, timeout=120):
    try:
        p = subprocess.run(args, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 127, "", str(e)


def gh_json(args, timeout=120):
    rc, out, err = run_cmd(["gh"] + args, timeout=timeout)
    if rc != 0:
        return None, "gh %s failed rc=%d: %s" % (" ".join(args), rc,
                                                 err.strip()[:300])
    try:
        return json.loads(out), None
    except ValueError:
        return None, "gh %s returned non-JSON" % " ".join(args)


def rate_limit_remaining():
    """Free endpoint. Returns (remaining, error)."""
    data, err = gh_json(["api", "rate_limit"])
    if err:
        return None, err
    try:
        return int(data["resources"]["core"]["remaining"]), None
    except (KeyError, TypeError, ValueError):
        return None, "rate_limit response missing resources.core.remaining"


def list_runs(limit=50):
    """ONE batched list call covering all workflows."""
    return gh_json(["run", "list", "-R", REPO, "-L", str(limit), "--json",
                    "databaseId,status,conclusion,createdAt,updatedAt,"
                    "workflowName,url"])


def workflow_name(workflow_file):
    return workflow_file[:-4] if workflow_file.endswith(".yml") else workflow_file


# --- submit / adopt / cancel ----------------------------------------------

def find_active(jobs, key=None, run_id=None):
    for j in jobs:
        if j["state"] not in ACTIVE_STATES:
            continue
        if key is not None and j.get("key") == key:
            return j
        if run_id is not None and str(j.get("run_id")) == str(run_id):
            return j
    return None


def cmd_submit(args):
    jobs = load_jobs()
    dup = find_active(jobs, key=args.key)
    if dup:
        print("REFUSED duplicate key '%s': active job %s (state=%s, run_id=%s)"
              % (args.key, dup["id"], dup["state"], dup.get("run_id")))
        return 3
    job = {
        "id": new_job_id(args.key),
        "key": args.key,
        "program": args.program,
        "workflow": args.workflow,
        "lane": args.lane,
        "cwd": args.cwd if args.cwd is not None else DEFAULT_CWD[args.workflow],
        "expected_min": args.expected_min,
        "state": "submitted",
        "created_at": now_iso(),
        "run_id": None,
        "run_status": None,
        "run_conclusion": None,
        "adopted": False,
        "verdict_source": None,
        "watermarks": {},
        "flags": [],
    }
    if args.workflow == "grab.yml":
        if not args.grab_path:
            print("ERROR: grab.yml jobs require --grab-path "
                  "(the desktop file path to return)")
            return 2
        job["grab_path"] = args.grab_path
        job["script_path"] = None
        job["script_sha256"] = None
    else:
        if not args.script or not os.path.isfile(args.script):
            print("ERROR: --script PATH must name an existing file for %s"
                  % args.workflow)
            return 2
        with open(args.script, "rb") as f:
            data = f.read()
        job["script_path"] = os.path.abspath(args.script)
        job["script_sha256"] = hashlib.sha256(data).hexdigest()
    save_job(job)
    ledger("submitted", job_id=job["id"], key=job["key"],
           program=job["program"], workflow=job["workflow"],
           lane=job["lane"], script_sha256=job["script_sha256"])
    print("SUBMITTED %s key=%s program=%s workflow=%s lane=%s"
          % (job["id"], job["key"], job["program"], job["workflow"],
             job["lane"]))
    return 0


def cmd_adopt(args):
    jobs = load_jobs()
    dup = find_active(jobs, key=args.key)
    if dup:
        print("REFUSED duplicate key '%s': active job %s" % (args.key,
                                                             dup["id"]))
        return 3
    dup = find_active(jobs, run_id=args.run_id)
    if dup:
        print("REFUSED: run %s already tracked by job %s" % (args.run_id,
                                                             dup["id"]))
        return 3
    job = {
        "id": new_job_id(args.key),
        "key": args.key,
        "program": args.program,
        "workflow": args.workflow,
        "lane": args.lane,
        "cwd": None,
        "expected_min": args.expected_min,
        "state": "watching",
        "created_at": now_iso(),
        "adopted_at": now_iso(),
        "run_id": int(args.run_id),
        "run_status": None,
        "run_conclusion": None,
        "run_created_at": None,
        "adopted": True,
        "verdict_source": None,
        "watermarks": {},
        "flags": [],
    }
    save_job(job)
    ledger("adopted", job_id=job["id"], key=job["key"],
           program=job["program"], workflow=job["workflow"],
           lane=job["lane"], run_id=job["run_id"])
    print("ADOPTED %s run_id=%s key=%s program=%s lane=%s"
          % (job["id"], job["run_id"], job["key"], job["program"],
             job["lane"]))
    return 0


def cmd_cancel(args):
    """Local only: retire a job that has NOT been dispatched. Never touches
    any GitHub run (Part 4: watchers do not cancel runs)."""
    jobs = load_jobs()
    target = None
    for j in jobs:
        if j["id"] == args.job or j.get("key") == args.job:
            target = j
            break
    if target is None:
        print("ERROR: no job with id/key '%s'" % args.job)
        return 2
    if target["state"] != "submitted":
        print("REFUSED: job %s is state=%s (already dispatched or terminal). "
              "gk cancel is local-only and never cancels a GitHub run."
              % (target["id"], target["state"]))
        return 3
    target["state"] = "cancelled"
    target["cancelled_at"] = now_iso()
    save_job(target)
    ledger("cancelled_local", job_id=target["id"], key=target["key"])
    print("CANCELLED (local only, nothing was dispatched) %s" % target["id"])
    return 0


# --- sweep: dispatch --------------------------------------------------------

def recorded_run_ids(jobs):
    return {str(j["run_id"]) for j in jobs if j.get("run_id")}


def capture_run_id(workflow, before_iso, taken):
    """Find the run this dispatch created: same workflow, createdAt >= the
    moment just before dispatch, earliest first, skipping ids already
    recorded against other jobs. Never latches an id that does not resolve
    (the list call IS the resolution). Returns run id or None."""
    data, err = gh_json(["run", "list", "-R", REPO, "--workflow", workflow,
                         "-L", "10", "--json", "databaseId,createdAt,status"])
    if err or not data:
        return None
    cands = [r for r in data
             if r.get("createdAt", "") >= before_iso
             and str(r["databaseId"]) not in taken]
    if not cands:
        return None
    cands.sort(key=lambda r: r["createdAt"])
    return int(cands[0]["databaseId"])


def dispatch_one(job, jobs):
    """Returns True if the job now holds a run. Caller has already applied
    the lane/cap gates. Sets state=dispatching BEFORE the gh call so a
    killed sweep cannot double-dispatch."""
    job["state"] = "dispatching"
    job["dispatching_at"] = now_iso()
    save_job(job)
    ledger("dispatching", job_id=job["id"], key=job["key"],
           workflow=job["workflow"], lane=job["lane"])
    before = now_iso()
    if job["workflow"] == "grab.yml":
        gh_args = ["workflow", "run", "grab.yml", "-R", REPO,
                   "-f", "path=" + job["grab_path"]]
    else:
        with open(job["script_path"], "rb") as f:
            payload = base64.b64encode(f.read()).decode("ascii")
        gh_args = ["workflow", "run", job["workflow"], "-R", REPO,
                   "-f", "cmd_b64=" + payload]
        if job.get("cwd"):
            gh_args += ["-f", "cwd=" + job["cwd"]]
    rc, out, err = run_cmd(["gh"] + gh_args, timeout=60)
    run_id = None
    # Newer gh prints the created run URL on stdout - most robust capture.
    m = re.search(r"/actions/runs/(\d+)", out or "")
    if m:
        rid = m.group(1)
        if rid not in recorded_run_ids(jobs):
            run_id = int(rid)
    if run_id is None:
        run_id = capture_run_id(job["workflow"], before,
                                recorded_run_ids(jobs))
    if run_id is not None:
        job["state"] = "dispatched"
        job["run_id"] = run_id
        job["dispatched_at"] = now_iso()
        job.pop("dispatching_at", None)
        save_job(job)
        ledger("dispatched", job_id=job["id"], key=job["key"],
               run_id=run_id, gh_rc=rc)
        return True
    if rc != 0:
        # gh itself failed and no run materialized: safe to retry next sweep.
        job["state"] = "submitted"
        job["last_dispatch_error"] = (err or "").strip()[:300]
        job.pop("dispatching_at", None)
        save_job(job)
        ledger("dispatch_failed_retryable", job_id=job["id"],
               key=job["key"], gh_rc=rc,
               error=job["last_dispatch_error"])
    else:
        # gh claims success but we cannot identify the run: do NOT guess
        # and do NOT auto-redispatch (that is the double-dispatch trap).
        job["state"] = "dispatching"
        if "dispatch_unconfirmed" not in job["flags"]:
            job["flags"].append("dispatch_unconfirmed")
        save_job(job)
        ledger("dispatch_unconfirmed", job_id=job["id"], key=job["key"])
    return False


def dispatch_pass(jobs, runs_by_id):
    """Returns number of jobs dispatched this sweep."""
    dispatched = 0
    # Stale dispatching states: flag for a human, never auto-redispatch.
    for j in jobs:
        if j["state"] == "dispatching" and not j.get("run_id"):
            age = minutes_between(parse_iso(j.get("dispatching_at")), now_dt())
            if age is not None and age > STALE_DISPATCHING_MIN:
                if "stale_dispatching" not in j["flags"]:
                    j["flags"].append("stale_dispatching")
                    save_job(j)
                    ledger("stale_dispatching", job_id=j["id"], key=j["key"],
                           age_min=round(age, 1))
    holding = [j for j in jobs
               if j["state"] in RUN_HOLDING_STATES
               and j.get("run_status") != "completed"]
    active_count = len(holding)
    held_lanes = {j["lane"] for j in holding}
    held_hashes = {(j["workflow"], j.get("script_sha256")) for j in holding
                   if j.get("script_sha256")}
    waiting = sorted([j for j in jobs if j["state"] == "submitted"],
                     key=lambda j: j["created_at"])
    for job in waiting:
        if active_count >= MAX_ACTIVE_DISPATCHED:
            ledger("dispatch_deferred_cap", job_id=job["id"], key=job["key"],
                   active=active_count, cap=MAX_ACTIVE_DISPATCHED)
            continue
        if job["lane"] in held_lanes:
            continue  # lane serialization: another job of this class is live
        if (job["workflow"], job.get("script_sha256")) in held_hashes:
            ledger("dispatch_skipped_duplicate", job_id=job["id"],
                   key=job["key"], workflow=job["workflow"],
                   script_sha256=job.get("script_sha256"))
            continue
        if dispatch_one(job, jobs):
            dispatched += 1
            active_count += 1
            held_lanes.add(job["lane"])
            if job.get("script_sha256"):
                held_hashes.add((job["workflow"], job["script_sha256"]))
    return dispatched


# --- sweep: watch + watermarks ----------------------------------------------

def current_step(run_id):
    """One jobs call - used ONLY for a run that has breached executing W1,
    to compare step progression across breaches. Returns 'N:name' or None."""
    data, err = gh_json(["api", "repos/%s/actions/runs/%s/jobs"
                         % (REPO, run_id)])
    if err or not data or not data.get("jobs"):
        return None
    steps = data["jobs"][0].get("steps") or []
    for s in steps:
        if s.get("status") == "in_progress":
            return "%s:%s" % (s.get("number"), s.get("name"))
    return None


def extract_log_lines(raw):
    """gh run view --log lines are 'job<TAB>step<TAB>timestamp content'.
    Return content lines (prefix stripped when the shape matches)."""
    lines = []
    for line in raw.splitlines():
        parts = line.split("\t")
        content = parts[-1] if len(parts) >= 3 else line
        content = re.sub(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z ", "", content)
        lines.append(content)
    return lines


def fetch_log_once(job):
    rc, out, err = run_cmd(["gh", "run", "view", str(job["run_id"]), "-R",
                            REPO, "--log"], timeout=180)
    if rc != 0 or not out:
        job["log_pending"] = True
        ledger("log_fetch_failed", job_id=job["id"], key=job["key"],
               run_id=job["run_id"], rc=rc)
        return False
    lines = extract_log_lines(out)
    job["log_tail"] = lines[-200:]
    job["markers"] = [ln for ln in lines if MARKER_RE.match(ln.strip())]
    job["log_fetched_at"] = now_iso()
    job["log_pending"] = False
    job["verdict_source"] = "markers"
    ledger("log_harvested", job_id=job["id"], key=job["key"],
           run_id=job["run_id"], markers=len(job["markers"]),
           log_lines=len(lines))
    return True


def exec_thresholds(job):
    exp = job.get("expected_min")
    lane = job["lane"]
    if lane in EXEC_WM_FIXED:
        return EXEC_WM_FIXED[lane]
    f1, f2 = EXEC_WM_FLOOR[lane]
    if exp:
        return (max(exp * 1.5, f1), max(exp * 2.0, f2))
    return (f1, f2)


def eval_watermarks(job, run):
    """Record Part 4 watermark breaches. Never cancels, never escalates
    beyond the ledger + job flags. Queued W1 is record-only during the
    pre-lane transition; queued W2 escalates (flag + ledger)."""
    events = 0
    wm = job.setdefault("watermarks", {})
    status = run.get("status")
    if status == "queued" or status in ("waiting", "requested", "pending"):
        start = parse_iso(job.get("run_created_at") or run.get("createdAt"))
        age = minutes_between(start, now_dt())
        if age is None:
            return 0
        w1, w2 = QUEUED_WM[job["lane"]]
        if age >= w1 and "queued_w1" not in wm:
            wm["queued_w1"] = now_iso()
            ledger("watermark_breach", job_id=job["id"], key=job["key"],
                   run_id=job["run_id"], lane=job["lane"], level="W1",
                   state="queued", age_min=round(age, 1), threshold_min=w1,
                   classification="starvation")
            events += 1
        if age >= w2 and "queued_w2" not in wm:
            wm["queued_w2"] = now_iso()
            if "watermark_queued_w2" not in job["flags"]:
                job["flags"].append("watermark_queued_w2")
            ledger("watermark_escalation", job_id=job["id"], key=job["key"],
                   run_id=job["run_id"], lane=job["lane"], level="W2",
                   state="queued", age_min=round(age, 1), threshold_min=w2,
                   classification="starvation")
            events += 1
    elif status == "in_progress":
        start = parse_iso(job.get("first_seen_in_progress_at"))
        age = minutes_between(start, now_dt())
        if age is None:
            return 0
        w1, w2 = exec_thresholds(job)
        if age >= w1 and "exec_w1" not in wm:
            wm["exec_w1"] = now_iso()
            step = current_step(job["run_id"])
            job["last_step_at_w1"] = step
            ledger("watermark_breach", job_id=job["id"], key=job["key"],
                   run_id=job["run_id"], lane=job["lane"], level="W1",
                   state="executing", age_min=round(age, 1),
                   threshold_min=w1, current_step=step)
            events += 1
        if age >= w2 and "exec_w2" not in wm:
            wm["exec_w2"] = now_iso()
            if "watermark_exec_w2" not in job["flags"]:
                job["flags"].append("watermark_exec_w2")
            step = current_step(job["run_id"])
            prev = job.get("last_step_at_w1")
            progression = ("step_advanced" if step != prev
                           else "step_frozen_or_unknown")
            job["last_step_at_w2"] = step
            ledger("watermark_escalation", job_id=job["id"], key=job["key"],
                   run_id=job["run_id"], lane=job["lane"], level="W2",
                   state="executing", age_min=round(age, 1),
                   threshold_min=w2, current_step=step,
                   step_progression=progression)
            events += 1
    return events


def watch_pass(jobs, runs_by_id):
    changes = 0
    breaches = 0
    for job in jobs:
        if job["state"] not in ("dispatched", "watching"):
            continue
        if not job.get("run_id"):
            continue
        run = runs_by_id.get(str(job["run_id"]))
        if run is None:
            if not job.get("not_in_list_noted"):
                job["not_in_list_noted"] = True
                save_job(job)
                ledger("run_not_in_list", job_id=job["id"], key=job["key"],
                       run_id=job["run_id"])
            continue
        job["not_in_list_noted"] = False
        if not job.get("run_created_at"):
            job["run_created_at"] = run.get("createdAt")
        old_status = job.get("run_status")
        new_status = run.get("status")
        if new_status == "in_progress" and not job.get(
                "first_seen_in_progress_at"):
            job["first_seen_in_progress_at"] = now_iso()
        if new_status != old_status:
            job["run_status"] = new_status
            job["run_conclusion"] = run.get("conclusion")
            changes += 1
            ledger("state_change", job_id=job["id"], key=job["key"],
                   run_id=job["run_id"], from_status=old_status,
                   to_status=new_status,
                   conclusion=run.get("conclusion"))
        if new_status == "completed":
            job["run_conclusion"] = run.get("conclusion")
            if not job.get("log_fetched_at"):
                fetch_log_once(job)
            job["state"] = "completed"
            job["completed_at"] = job.get("completed_at") or now_iso()
            save_job(job)
        else:
            breaches += eval_watermarks(job, run)
            save_job(job)
    return changes, breaches


# --- sweep: main ------------------------------------------------------------

def acquire_lock():
    try:
        os.mkdir(LOCK_DIR)
        return True
    except FileExistsError:
        age = minutes_between(
            datetime.fromtimestamp(os.path.getmtime(LOCK_DIR),
                                   tz=timezone.utc), now_dt())
        if age is not None and age > LOCK_STALE_MIN:
            try:
                os.rmdir(LOCK_DIR)
                os.mkdir(LOCK_DIR)
                return True
            except OSError:
                return False
        return False


def cmd_sweep(_args):
    if not acquire_lock():
        print("SWEEP skipped: another sweep holds the lock")
        return 0
    try:
        remaining, err = rate_limit_remaining()
        if err:
            ledger("api_error", where="rate_limit", error=err)
            print("SWEEP budget=unknown (rate_limit error) dispatched=0 "
                  "changes=0 breaches=0")
            return 0
        if remaining < CRITICAL_REMAINING:
            ledger("budget_critical", remaining=remaining)
            print("SWEEP budget_remaining=%d CRITICAL: no dispatch, no "
                  "watch calls" % remaining)
            return 0
        standdown = remaining < STANDDOWN_REMAINING
        if standdown:
            ledger("budget_standdown", remaining=remaining)
        runs, lerr = list_runs(50)
        runs_by_id = {}
        if lerr:
            ledger("api_error", where="run_list", error=lerr)
        else:
            runs_by_id = {str(r["databaseId"]): r for r in runs}
        jobs = load_jobs()
        dispatched = 0
        if not standdown and not lerr:
            dispatched = dispatch_pass(jobs, runs_by_id)
            jobs = load_jobs()  # dispatch_one saved as it went; reload fresh
        changes = breaches = 0
        if not lerr:
            changes, breaches = watch_pass(jobs, runs_by_id)
        active = len([j for j in load_jobs()
                      if j["state"] in RUN_HOLDING_STATES
                      and j.get("run_status") != "completed"])
        waiting = len([j for j in load_jobs() if j["state"] == "submitted"])
        print("SWEEP %s budget_remaining=%d%s dispatched=%d changes=%d "
              "breaches=%d active=%d waiting=%d"
              % (now_iso(), remaining,
                 " STANDDOWN" if standdown else "", dispatched, changes,
                 breaches, active, waiting))
        return 0
    finally:
        try:
            os.rmdir(LOCK_DIR)
        except OSError:
            pass


# --- status ------------------------------------------------------------------

def cmd_status(_args):
    jobs = load_jobs()
    by_state = {}
    for j in jobs:
        by_state[j["state"]] = by_state.get(j["state"], 0) + 1
    print("GATEKEEPER STATUS %s" % now_iso())
    print("jobs by state: %s" % (", ".join(
        "%s=%d" % (k, by_state[k]) for k in sorted(by_state)) or "none"))
    print("")
    print("%-46s %-16s %-7s %-11s %-12s %s" % ("KEY", "PROGRAM", "LANE",
                                               "STATE", "RUN_STATUS",
                                               "RUN_ID / FLAGS"))
    for j in sorted(jobs, key=lambda x: x["created_at"]):
        if j["state"] in ("completed", "cancelled") and not j.get("run_id"):
            continue
        print("%-46s %-16s %-7s %-11s %-12s %s%s"
              % (j["key"][:46], j["program"][:16], j["lane"], j["state"],
                 str(j.get("run_status")), str(j.get("run_id") or "-"),
                 ("  flags=" + ",".join(j["flags"])) if j["flags"] else ""))
    done = [j for j in jobs if j["state"] == "completed"]
    if done:
        print("\ncompleted:")
        for j in done:
            print("  %s run=%s conclusion=%s verdict_source=%s markers=%d"
                  % (j["key"], j.get("run_id"), j.get("run_conclusion"),
                     j.get("verdict_source"),
                     len(j.get("markers", []))))
    if os.path.isfile(LEDGER):
        with open(LEDGER, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        print("\nlast ledger events:")
        for ln in lines[-10:]:
            try:
                e = json.loads(ln)
                print("  %s %-24s %s" % (e.get("ts"), e.get("event"),
                                         e.get("key") or e.get("run_id")
                                         or ""))
            except ValueError:
                print("  " + ln)
    return 0


# --- CLI ----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="gk", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("submit")
    p.add_argument("--program", required=True)
    p.add_argument("--workflow", required=True, choices=WORKFLOWS)
    p.add_argument("--lane", required=True, choices=LANES)
    p.add_argument("--script")
    p.add_argument("--grab-path")
    p.add_argument("--cwd")
    p.add_argument("--expected-min", type=float)
    p.add_argument("--key", required=True)
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("adopt")
    p.add_argument("--run-id", required=True)
    p.add_argument("--program", required=True)
    p.add_argument("--workflow", required=True, choices=WORKFLOWS)
    p.add_argument("--lane", required=True, choices=LANES)
    p.add_argument("--expected-min", type=float)
    p.add_argument("--key", required=True)
    p.set_defaults(fn=cmd_adopt)

    p = sub.add_parser("cancel")
    p.add_argument("job", help="job id or key (local only, pre-dispatch)")
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("sweep")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("status")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    os.makedirs(QUEUE_DIR, exist_ok=True)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
