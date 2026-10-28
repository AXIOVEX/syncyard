#!/usr/bin/env python3
"""gk.py - Desktop Access gatekeeper: the single dispatch/watch door for the
tbitcs/desktop-runner self-hosted runner fleet.

Implements the fleet standard (github-polling-census-and-standard-2026-10-27,
Parts 2 and 4):
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
PAUSE_FILE = os.path.join(BASE, "PAUSED.json")
STOP_FILE = os.path.join(BASE, "STOPPED.json")
OUTBOX_CURSOR = os.path.join(BASE, "outbox-cursor.json")
LANES_LIVE_FILE = os.path.join(BASE, "LANES_LIVE")

REPO = "tbitcs/desktop-runner"
PROJECT_REPO = "AXIOVEX/syncyard"   # canonical project repo (status --repo)
HLOG = os.path.join(BASE, "gatekeeper.log")   # human-readable rotating log
HLOG_MAX_BYTES = 1000000

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


def hlog(msg):
    """Append one line to the human-readable gatekeeper log, rotating at
    HLOG_MAX_BYTES (one backup kept). Best-effort by design: a logging
    failure must never break a sweep, so every error is swallowed."""
    try:
        if os.path.isfile(HLOG) and os.path.getsize(HLOG) > HLOG_MAX_BYTES:
            os.replace(HLOG, HLOG + ".1")
        with open(HLOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (now_iso(), msg))
    except OSError:
        pass


def _write_verified_bytes(path, data, attempts=8):
    """WRITE-VERIFY-RETRY (spec 001 FR-012): write data to path with
    unbuffered syscalls, fsync, then READ BACK and byte-compare.
    Retries with backoff (0.25s doubling, capped at 8s). Returns True
    only when the bytes on disk are exactly the bytes given - the VM
    write restriction can drop a buffered write silently and leave a
    0-byte file standing, so an unverified success is never trusted.
    Returns False after the bounded retries are exhausted."""
    for i in range(attempts):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                         0o644)
            try:
                view = memoryview(data)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            with open(path, "rb") as f:
                back = f.read()
            if back == data and len(back) > 0:
                return True
        except OSError:
            pass
        if i + 1 < attempts:
            time.sleep(min(0.25 * (2 ** i), 8.0))
    return False


def _append_verified(path, line, attempts=8):
    """Append one line and verify it landed (file size grows by
    exactly len(line)); same retry discipline as
    _write_verified_bytes. Returns True only when verified."""
    data = line.encode("utf-8")
    for i in range(attempts):
        try:
            before = os.path.getsize(path) if os.path.isfile(path) else 0
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                         0o644)
            try:
                view = memoryview(data)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.path.getsize(path) == before + len(data):
                return True
        except OSError:
            pass
        if i + 1 < attempts:
            time.sleep(min(0.25 * (2 ** i), 8.0))
    return False


def ledger(event, **kw):
    rec = {"ts": now_iso(), "event": event}
    rec.update(kw)
    line = json.dumps(rec, sort_keys=True) + "\n"
    if not _append_verified(LEDGER, line):
        raise IOError("ledger append could not be verified after "
                      "retries: %s" % event)
    return rec


def job_path(job_id):
    return os.path.join(QUEUE_DIR, job_id + ".json")


def pause_state():
    """The pause record, or None when not paused. The file's mere
    existence means paused (a corrupt record still pauses — the
    operator's intent is the safe side)."""
    if not os.path.isfile(PAUSE_FILE):
        return None
    try:
        with open(PAUSE_FILE, encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else {"ts": None, "reason": ""}
    except (OSError, ValueError):
        return {"ts": None, "reason": ""}


def _write_text_file(path, text):
    """Write a small text file through the write-verify-retry path
    (spec 001 FR-012). Raises IOError when the write cannot be
    verified - a pause/stop record that silently did not land is a
    safety failure, not a soft one."""
    if not _write_verified_bytes(path, text.encode("utf-8")):
        raise IOError("could not write verified file: %s" % path)


def cmd_pause(args):
    cur = pause_state()
    if cur is not None:
        print("ALREADY PAUSED since %s reason=%s"
              % (cur.get("ts"), cur.get("reason") or ""))
        return 0
    rec = {"ts": now_iso(), "reason": args.reason or ""}
    try:
        _write_text_file(PAUSE_FILE,
                         json.dumps(rec, indent=2, sort_keys=True))
    except (OSError, subprocess.SubprocessError) as exc:
        print("ERROR: could not write the pause file (%s). The pause is "
              "NOT in effect." % exc)
        return 1
    ledger("paused", reason=rec["reason"])
    hlog("PAUSED at %s reason=%s" % (rec["ts"], rec["reason"]))
    print("PAUSED at %s — dispatch of program jobs is held; "
          "maintenance jobs still dispatch; the watch pass continues."
          % rec["ts"])
    return 0


def cmd_resume(_args):
    if pause_state() is None:
        print("NOT PAUSED")
        return 0
    try:
        os.unlink(PAUSE_FILE)
    except OSError:
        subprocess.run(["/bin/sh", "-c", 'rm -f "$1"', "sh", PAUSE_FILE],
                       check=True)
    ledger("resumed")
    hlog("RESUMED at %s" % now_iso())
    print("RESUMED — dispatch is flowing again.")
    return 0


def stop_state():
    """The stop record, or None when not stopped. Like the pause, the
    file's mere existence means stopped."""
    if not os.path.isfile(STOP_FILE):
        return None
    try:
        with open(STOP_FILE, encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else {"ts": None, "reason": ""}
    except (OSError, ValueError):
        return {"ts": None, "reason": ""}


def _clear_marker(path):
    try:
        os.unlink(path)
    except OSError:
        subprocess.run(["/bin/sh", "-c", 'rm -f "$1"', "sh", path],
                       check=True)


def cmd_start(_args):
    """Start: clear any stop and any pause — fully running."""
    cleared = []
    for path, name in ((STOP_FILE, "stop"), (PAUSE_FILE, "pause")):
        if os.path.isfile(path):
            _clear_marker(path)
            cleared.append(name)
    if not cleared:
        print("ALREADY RUNNING (no stop or pause in effect)")
        return 0
    ledger("started", cleared=cleared)
    hlog("STARTED at %s (cleared: %s)" % (now_iso(), ", ".join(cleared)))
    print("RUNNING — cleared %s. Dispatch and watch are live."
          % " + ".join(cleared))
    return 0


def cmd_stop(args):
    """Stop: the hard halt. Sweeps no-op (no budget spent, no watch,
    no dispatch) until `gk start`. Stronger than pause; jobs already
    dispatched are untouched, as always."""
    cur = stop_state()
    if cur is not None:
        print("ALREADY STOPPED since %s reason=%s"
              % (cur.get("ts"), cur.get("reason") or ""))
        return 0
    rec = {"ts": now_iso(), "reason": args.reason or ""}
    try:
        _write_text_file(STOP_FILE,
                         json.dumps(rec, indent=2, sort_keys=True))
    except (OSError, subprocess.SubprocessError) as exc:
        print("ERROR: could not write the stop file (%s). The stop is "
              "NOT in effect." % exc)
        return 1
    ledger("stopped", reason=rec["reason"])
    hlog("STOPPED at %s reason=%s" % (rec["ts"], rec["reason"]))
    print("STOPPED at %s — sweeps will no-op until `gk start`."
          % rec["ts"])
    return 0


def cmd_purge(args):
    """Purge housekeeping: remove terminal (completed/cancelled) job
    records, optionally only those older than N days from creation,
    and optionally archive the ledger to a fresh one. DRY RUN unless
    --yes. Active and submitted records are never touched."""
    jobs = load_jobs()
    targets = []
    for j in jobs:
        if j["state"] not in ("completed", "cancelled"):
            continue
        if args.older_than_days is not None:
            created = parse_iso(j.get("created_at"))
            age_min = minutes_between(created, now_dt())
            if age_min is None or age_min < args.older_than_days * 1440:
                continue
        targets.append(j)
    verb = "purged" if args.yes else "would purge"
    for j in targets:
        print("  %s %s key=%s state=%s"
              % (verb, j["id"], j["key"], j["state"]))
    if args.ledger:
        print("  %s the ledger (archive ledger.jsonl, start fresh)"
              % verb)
    if not targets and not args.ledger:
        print("PURGE: nothing matches (terminal states: completed, "
              "cancelled%s)"
              % ("" if args.older_than_days is None
                 else "; older than %s day(s) from creation"
                      % args.older_than_days))
        return 0
    if not args.yes:
        print("DRY RUN — nothing deleted. Re-run with --yes to purge "
              "%d job record(s)%s."
              % (len(targets), " and archive the ledger" if args.ledger
                 else ""))
        return 0
    removed = 0
    for j in targets:
        _clear_marker(os.path.join(QUEUE_DIR, j["id"] + ".json"))
        removed += 1
    archived = False
    if args.ledger and os.path.isfile(LEDGER):
        stamp = now_iso().replace(":", "").replace("-", "")
        dest = os.path.join(BASE, "ledger-archived-%s.jsonl" % stamp)
        os.replace(LEDGER, dest)
        open(LEDGER, "a", encoding="utf-8").close()
        archived = True
        print("  ledger archived to %s" % os.path.basename(dest))
    ledger("purged", jobs=removed, ledger_archived=archived)
    hlog("PURGED %d job record(s) at %s" % (removed, now_iso()))
    print("PURGED %d job record(s)%s."
          % (removed, "; ledger archived" if archived else ""))
    return 0


def cmd_outbox(args):
    """Push-notification outbox. Reads ledger events past the stored
    cursor and prints, grouped by each job's notify_chat, the pushes
    owed: STARTED (with the job's expected length), COMPLETED
    (conclusion plus verdict highlights from the job's harvested
    markers), ESCALATED (W2 watermark). The cursor starts at the
    current ledger end the first time — history is never replayed.
    --ack advances the cursor once the caller has delivered the
    pushes; delivery itself is the caller's act (the coordination
    chat forwards each group into the named chat)."""
    try:
        with open(LEDGER, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []
    cursor = None
    if os.path.isfile(OUTBOX_CURSOR):
        try:
            with open(OUTBOX_CURSOR, encoding="utf-8") as f:
                cursor = int(json.load(f)["line"])
        except (OSError, ValueError, KeyError, TypeError):
            cursor = None
    if cursor is None:
        _write_text_file(OUTBOX_CURSOR, json.dumps({"line": len(lines)}))
        print("OUTBOX initialized at line %d (history not replayed)"
              % len(lines))
        return 0
    if args.ack:
        _write_text_file(OUTBOX_CURSOR, json.dumps({"line": len(lines)}))
        print("OUTBOX ACK line=%d" % len(lines))
        return 0
    jobs = {j["id"]: j for j in load_jobs()}
    groups = {}
    for raw in lines[cursor:]:
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        job = jobs.get(ev.get("job_id") or "")
        if not job or not job.get("notify_chat"):
            continue
        head = "[%s] %s" % (job["program"], job["key"])
        msg = None
        if (ev.get("event") == "state_change"
                and ev.get("to_status") == "in_progress"):
            exp = job.get("expected_min")
            msg = "%s STARTED run %s%s" % (
                head, ev.get("run_id"),
                (" expected ~%g min" % exp) if exp else "")
        elif (ev.get("event") == "state_change"
                and ev.get("to_status") == "completed"):
            marks = job.get("markers") or []
            hl = [m for m in marks if ("RESULT" in m or "VERDICT" in m)][:3]
            msg = "%s COMPLETED run %s conclusion=%s markers=%d%s" % (
                head, ev.get("run_id"), ev.get("conclusion") or "?",
                len(marks),
                (" | " + " ;; ".join(hl)) if hl
                else (" | verdict pending harvest" if not marks else ""))
        elif (ev.get("event") == "watermark_escalation"
                and ev.get("level") == "W2"):
            msg = "%s ESCALATED W2 %s run %s age=%s min" % (
                head, ev.get("classification"), ev.get("run_id"),
                ev.get("age_min"))
        if msg:
            groups.setdefault(job["notify_chat"], []).append(msg)
    if not groups:
        print("OUTBOX empty")
        return 0
    for chat in sorted(groups):
        print("NOTIFY %s" % chat)
        for msg in groups[chat]:
            print("  %s" % msg)
    return 0


def save_job(job):
    """Persist a job record under WRITE-VERIFY-RETRY (spec 001
    FR-012): the payload is written to a unique temp file and read
    back byte-for-byte before it is moved into place; if the move
    itself is refused, the payload is written directly to the final
    path and verified there. Raises IOError when no verified write
    lands - callers must never treat an unverified save as done, and
    a 0-byte or partial file is never left standing as the record."""
    payload = json.dumps(job, indent=2, sort_keys=True).encode("utf-8")
    final = job_path(job["id"])
    tmp = os.path.join(QUEUE_DIR, ".%s.%d.tmp"
                       % (job["id"], os.getpid()))
    try:
        if _write_verified_bytes(tmp, payload):
            for i in range(8):
                try:
                    os.replace(tmp, final)
                    with open(final, "rb") as f:
                        if f.read() == payload:
                            return
                except OSError:
                    pass
                if i + 1 < 8:
                    time.sleep(min(0.25 * (2 ** i), 8.0))
        # The move would not land (or the temp write never verified):
        # write the final path directly and verify it there.
        if _write_verified_bytes(final, payload):
            return
        raise IOError("save_job could not verify a write for job %s"
                      % job["id"])
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def load_jobs():
    jobs = []
    if not os.path.isdir(QUEUE_DIR):
        return jobs
    for name in sorted(os.listdir(QUEUE_DIR)):
        if name.endswith(".json"):
            try:
                with open(os.path.join(QUEUE_DIR, name),
                          encoding="utf-8") as f:
                    jobs.append(json.load(f))
            except (OSError, ValueError) as e:
                # A 0-byte or partial record (the silent-drop write
                # mode) must not crash every command or pose as a
                # job: skip it loudly (spec 001 FR-012).
                print("WARNING: skipping unreadable job file %s: %s"
                      % (name, e), file=sys.stderr)
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
        "maintenance": bool(getattr(args, "maintenance", False)),
        "notify_chat": getattr(args, "notify_chat", None),
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
    # FR-012: a submission is only reported queued after the loader
    # reads back the exact record that was written.
    landed = find_active(load_jobs(), key=job["key"])
    if (landed is None or landed["id"] != job["id"]
            or landed.get("script_sha256") != job["script_sha256"]):
        print("ERROR: submission %s did not verify on read-back; "
              "it is NOT queued" % job["id"])
        return 4
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
        "notify_chat": getattr(args, "notify_chat", None),
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
    lane_label = "lane-" + job["lane"]
    if job["workflow"] == "grab.yml":
        gh_args = ["workflow", "run", "grab.yml", "-R", REPO,
                   "-f", "path=" + job["grab_path"],
                   "-f", "lane=" + lane_label]
    else:
        with open(job["script_path"], "rb") as f:
            payload = base64.b64encode(f.read()).decode("ascii")
        gh_args = ["workflow", "run", job["workflow"], "-R", REPO,
                   "-f", "cmd_b64=" + payload,
                   "-f", "lane=" + lane_label]
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
    paused = (pause_state() is not None or stop_state() is not None)
    lanes_live = os.path.isfile(LANES_LIVE_FILE)
    for job in waiting:
        maint = bool(job.get("maintenance"))
        if paused and not maint:
            continue  # paused: program work holds; maintenance flows
        if not lanes_live and active_count >= MAX_ACTIVE_DISPATCHED \
                and not maint:
            ledger("dispatch_deferred_cap", job_id=job["id"], key=job["key"],
                   active=active_count, cap=MAX_ACTIVE_DISPATCHED)
            continue
        if job["lane"] in held_lanes and not maint:
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


def fetch_log_archive(run_id):
    """Fallback log source: the REST logs archive (a zip of per-step text
    files). Some runs' logs cannot be read by `gh run view --log` at all
    (observed 2026-10-27, run 40512763692: --log failed on every attempt
    while the archive read fine). Returns combined text or None."""
    import io
    import zipfile
    try:
        p = subprocess.run(
            ["gh", "api", "repos/%s/actions/runs/%s/logs" % (REPO, run_id)],
            capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0 or not p.stdout:
        return None
    try:
        zf = zipfile.ZipFile(io.BytesIO(p.stdout))
    except zipfile.BadZipFile:
        return None
    chunks = []
    for name in sorted(zf.namelist()):
        if name.endswith(".txt"):
            chunks.append(zf.read(name).decode("utf-8", "replace"))
    return "\n".join(chunks) if chunks else None


def fetch_log_once(job):
    rc, out, err = run_cmd(["gh", "run", "view", str(job["run_id"]), "-R",
                            REPO, "--log"], timeout=180)
    via = "gh-log"
    if rc != 0 or not out:
        out = fetch_log_archive(job["run_id"])
        via = "api-archive"
    if not out:
        job["log_pending"] = True
        ledger("log_fetch_failed", job_id=job["id"], key=job["key"],
               run_id=job["run_id"], rc=rc)
        return False
    lines = extract_log_lines(out)
    job["log_tail"] = lines[-200:]
    job["markers"] = [ln for ln in lines if MARKER_RE.match(ln.strip())]
    job["log_fetched_at"] = now_iso()
    job["log_pending"] = False
    job["log_source"] = via
    job["verdict_source"] = "markers"
    ledger("log_harvested", job_id=job["id"], key=job["key"],
           run_id=job["run_id"], markers=len(job["markers"]),
           log_lines=len(lines), via=via)
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
        stopped = stop_state()
        if stopped is not None:
            print("SWEEP %s STOPPED since %s (%s) — nothing spent, "
                  "nothing watched, nothing dispatched"
                  % (now_iso(), stopped.get("ts"),
                     stopped.get("reason") or "no reason recorded"))
            return 0
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
            hlog("SWEEP budget_remaining=%d CRITICAL: no dispatch, no "
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
        summary = ("SWEEP %s budget_remaining=%d%s%s dispatched=%d "
                   "changes=%d breaches=%d active=%d waiting=%d"
                   % (now_iso(), remaining,
                      " STANDDOWN" if standdown else "",
                      " PAUSED" if pause_state() is not None else "",
                      dispatched, changes, breaches, active, waiting))
        print(summary)
        hlog(summary)
        return 0
    finally:
        try:
            os.rmdir(LOCK_DIR)
        except OSError:
            pass


# --- status ------------------------------------------------------------------

def job_issues(j):
    """One job's current issue list, derived from its saved state only."""
    out = []
    for fl in j.get("flags", []):
        if fl.startswith("watermark"):
            out.append(fl.replace("_", " "))
    if j.get("log_pending"):
        out.append("log harvest failed/pending (verdict not yet readable)")
    if j["state"] == "dispatching":
        out.append("dispatch in progress (stale-dispatching is flagged "
                   "for a human, never auto-redispatched)")
    if j["state"] == "completed" and j.get("run_conclusion") not in (
            None, "success") and not j.get("markers"):
        out.append("completed with conclusion=%s and no markers"
                   % j.get("run_conclusion"))
    if j["state"] == "completed" and j.get("run_conclusion") == "success" \
            and j.get("verdict_source") != "markers":
        out.append("completed successfully but no marker verdict harvested")
    return out


def repo_health():
    """Project-repo health for `status --repo`: latest CI runs on main,
    open Dependabot alerts, and open Dependabot pull requests. Three API
    calls, made only when the flag is passed (never in the default
    local-only status). Failures degrade to an 'unavailable' line."""
    print("\nrepo health (%s):" % PROJECT_REPO)
    rc, out, _ = run_cmd(["gh", "run", "list", "-R", PROJECT_REPO, "-L", "3",
                          "--json", "workflowName,status,conclusion,"
                          "createdAt"], timeout=60)
    if rc == 0 and out:
        try:
            for r in json.loads(out):
                print("  CI %-10s %-12s %s (%s)"
                      % (r.get("workflowName"), r.get("status"),
                         r.get("conclusion") or "-", r.get("createdAt")))
        except ValueError:
            print("  CI unavailable (unparsable response)")
    else:
        print("  CI unavailable")
    rc, out, _ = run_cmd(["gh", "api", "repos/%s/dependabot/alerts"
                          "?state=open&per_page=30" % PROJECT_REPO],
                         timeout=60)
    if rc == 0 and out is not None:
        try:
            alerts = json.loads(out or "[]")
            if alerts:
                for a in alerts:
                    adv = a.get("security_advisory") or {}
                    print("  DEPENDABOT ALERT #%s %s (%s)"
                          % (a.get("number"), adv.get("summary", "?"),
                             adv.get("severity", "?")))
            else:
                print("  dependabot alerts: none open")
        except ValueError:
            print("  dependabot alerts: unavailable (unparsable response)")
    else:
        print("  dependabot alerts: unavailable")
    rc, out, _ = run_cmd(["gh", "pr", "list", "-R", PROJECT_REPO,
                          "--author", "app/dependabot", "--json",
                          "number,title"], timeout=60)
    if rc == 0 and out:
        try:
            prs = json.loads(out)
            for pr in prs:
                print("  DEPENDABOT PR #%s %s" % (pr.get("number"),
                                                  pr.get("title")))
            if not prs:
                print("  dependabot PRs: none open")
        except ValueError:
            print("  dependabot PRs: unavailable (unparsable response)")
    else:
        print("  dependabot PRs: unavailable")


def cmd_status(args):
    jobs = load_jobs()
    by_state = {}
    for j in jobs:
        by_state[j["state"]] = by_state.get(j["state"], 0) + 1
    print("GATEKEEPER STATUS %s" % now_iso())
    st = stop_state()
    if st is not None:
        print("!! STOPPED since %s — %s (sweeps no-op until `gk start`)"
              % (st.get("ts"), st.get("reason") or "no reason recorded"))
    ps = pause_state()
    if ps is not None:
        print("!! PAUSED since %s — %s (program dispatch held; "
              "maintenance jobs still flow)"
              % (ps.get("ts"), ps.get("reason") or "no reason recorded"))
    print("jobs by state: %s" % (", ".join(
        "%s=%d" % (k, by_state[k]) for k in sorted(by_state)) or "none"))
    queued = [j for j in jobs if j.get("run_status") == "queued"
              or j["state"] in ("submitted", "dispatched")]
    running = [j for j in jobs if j.get("run_status") == "in_progress"]
    print("queued: %d   running: %d" % (len(queued), len(running)))
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
    issues = [(j, job_issues(j)) for j in jobs]
    issues = [(j, i) for (j, i) in issues if i]
    print("\nISSUES: %d" % len(issues))
    for j, iss in issues:
        for s in iss:
            print("  [%s] %s — %s" % (j["program"], j["key"], s))
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
    if getattr(args, "repo", False):
        repo_health()
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
    p.add_argument("--maintenance", action="store_true",
                   help="operator maintenance job: dispatches even while "
                        "paused, bypassing the active cap and lane "
                        "serialization (never the duplicate check)")
    p.add_argument("--notify-chat", default=None,
                   help="chat id to push started/completed/escalated "
                        "updates for this job to (see `gk outbox`)")
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("pause")
    p.add_argument("--reason", default="")
    p.set_defaults(fn=cmd_pause)

    p = sub.add_parser("resume")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("start")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("stop")
    p.add_argument("--reason", default="")
    p.set_defaults(fn=cmd_stop)

    p = sub.add_parser("purge")
    p.add_argument("--older-than-days", type=float, default=None,
                   help="only purge terminal records created more than "
                        "N days ago (default: all terminal records)")
    p.add_argument("--ledger", action="store_true",
                   help="also archive ledger.jsonl and start a fresh one")
    p.add_argument("--yes", action="store_true",
                   help="actually delete (default is a dry run)")
    p.set_defaults(fn=cmd_purge)

    p = sub.add_parser("outbox")
    p.add_argument("--ack", action="store_true",
                   help="advance the outbox cursor to the current "
                        "ledger end (after the pushes are delivered)")
    p.set_defaults(fn=cmd_outbox)

    p = sub.add_parser("adopt")
    p.add_argument("--run-id", required=True)
    p.add_argument("--program", required=True)
    p.add_argument("--workflow", required=True, choices=WORKFLOWS)
    p.add_argument("--lane", required=True, choices=LANES)
    p.add_argument("--expected-min", type=float)
    p.add_argument("--key", required=True)
    p.add_argument("--notify-chat", default=None,
                   help="chat id to push started/completed/escalated "
                        "updates for this job to (see `gk outbox`)")
    p.set_defaults(fn=cmd_adopt)

    p = sub.add_parser("cancel")
    p.add_argument("job", help="job id or key (local only, pre-dispatch)")
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("sweep")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("status")
    p.add_argument("--repo", action="store_true",
                   help="also show project-repo CI + Dependabot health")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    os.makedirs(QUEUE_DIR, exist_ok=True)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
