#!/usr/bin/env python3
"""Golden battery for the spec 010 Phase 1 config wiring (T003/T004).

Proves the config-driven gatekeeper behaves byte-identically to the
pre-config constants:

 1. Constants anchor — with no config file, the wired module's
    effective constants equal the legacy literal table below.
 2. Dispatch equivalence — a fixture queue driven through
    dispatch_pass (dispatch_one stubbed; decisions + ledger events
    recorded) produces identical decision streams under (A) no
    config file (built-in defaults) and (B) the fleet example
    config (config/syncyard.example.yaml) placed beside gk.py.
 3. Each scenario's decisions also match hand-computed expectations
    pinning the CURRENT semantics (lane serialization, the pre-lane
    global cap, duplicate-hash refusal, maintenance bypass), so a
    future behavior change fails loudly here instead of slipping
    through as an A==B pass.

Stdlib only. Run: python3 gatekeeper/test_golden.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(HERE, "..", "config", "syncyard.example.yaml")

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


# --- Legacy literal table (the pre-config constants, verbatim) -----
LEGACY = {
    "REPO": "tbitcs/desktop-runner",
    "PROJECT_REPO": "AXIOVEX/syncyard",
    "HLOG_MAX_BYTES": 1000000,
    "MAX_ACTIVE_DISPATCHED": 2,
    "STANDDOWN_REMAINING": 1000,
    "CRITICAL_REMAINING": 500,
    "STALE_DISPATCHING_MIN": 10,
    "LOCK_STALE_MIN": 10,
    "WORKFLOWS": ("run.yml", "wsl.yml", "grab.yml"),
    "LANES": ("quick", "normal", "long", "gpu"),
    "DEFAULT_CWD": {"run.yml": r"C:\Users\trist", "wsl.yml": "/home/tpierson",
                    "grab.yml": None},
    "QUEUED_WM": {"quick": (10, 30), "normal": (20, 45), "long": (45, 120),
                  "gpu": (30, 90)},
    "EXEC_WM_FIXED": {"quick": (5, 15), "normal": (45, 90)},
    "EXEC_WM_FLOOR": {"long": (90, 180), "gpu": (120, 240)},
    "MARKER_RE": r"^[A-Z][A-Z0-9_]{2,}([ :]|$)",
    "LANE_LABEL": {"quick": "lane-quick", "normal": "lane-normal",
                   "long": "lane-long", "gpu": "lane-gpu"},
    "LANE_CONCURRENCY": {"quick": 1, "normal": 1, "long": 1, "gpu": 1},
}


def job(jid, lane, state, t, workflow="run.yml", sha=None, maint=False,
        run_status=None):
    return {
        "id": jid, "key": jid, "program": "golden", "workflow": workflow,
        "lane": lane, "state": state, "created_at": f"2026-10-31T00:00:{t:02d}Z",
        "script_sha256": sha, "maintenance": maint, "run_id": None,
        "run_status": run_status, "flags": [], "watermarks": {},
        "expected_min": None,
    }


FIXTURE = [
    job("h1", "quick", "dispatched", 1, sha="AAA", run_status="in_progress"),
    job("w1", "quick", "submitted", 2, sha="W1S"),
    job("w2", "normal", "submitted", 3, sha="BBB"),
    job("w3", "normal", "submitted", 4, sha="W3S"),
    job("w4", "gpu", "submitted", 5, workflow="wsl.yml", sha="AAA"),
    job("w5", "long", "submitted", 6, sha="AAA"),
    job("w6", "quick", "submitted", 7, sha="W6S", maint=True),
]

DRIVER = r"""
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("gk_under_test",
                                              os.path.join(BASE_DIR, "gk.py"))
gk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gk)
consts = {k: getattr(gk, k) for k in KEYS}
consts["WORKFLOWS"] = list(consts["WORKFLOWS"])
consts["LANES"] = list(consts["LANES"])
consts["MARKER_RE"] = gk.MARKER_RE.pattern
decided, events = [], []
gk.dispatch_one = lambda job, jobs: (decided.append(job["id"]), True)[1]
gk.ledger = lambda event, **kw: events.append([event, kw.get("job_id")])
jobs = gk.load_jobs()
gk.dispatch_pass(jobs, {})
# default=str: any non-JSON value surfaces as its repr for comparison.
print(json.dumps({"consts": consts, "decided": decided, "events": events},
                 sort_keys=True, default=str))
"""

KEYS = list(LEGACY.keys())


def run_scenario(with_yaml, lanes_live):
    d = tempfile.mkdtemp(prefix="gk-golden-")
    try:
        shutil.copy(os.path.join(HERE, "gk.py"), d)
        shutil.copy(os.path.join(HERE, "config.py"), d)
        if with_yaml:
            shutil.copy(EXAMPLE, os.path.join(d, "syncyard.yaml"))
        os.mkdir(os.path.join(d, "queue"))
        for j in FIXTURE:
            with open(os.path.join(d, "queue", j["id"] + ".json"), "w") as f:
                json.dump(j, f)
        if lanes_live:
            open(os.path.join(d, "LANES_LIVE"), "w").close()
        env = {k: v for k, v in os.environ.items()
               if k not in ("SYNCYARD_CONFIG", "SYNCARD_CONFIG")}
        driver = "BASE_DIR = %r\nKEYS = %r\n%s" % (d, KEYS, DRIVER)
        r = subprocess.run([sys.executable, "-c", driver],
                           capture_output=True, text=True, env=env, cwd=d)
        if r.returncode != 0:
            raise RuntimeError("driver failed: " + r.stderr[-800:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


# 1: constants anchor (no config file anywhere)
base = run_scenario(False, True)
for k, want in LEGACY.items():
    got = base["consts"][k]
    if isinstance(want, tuple):
        got = tuple(got)
    if isinstance(want, dict):
        got = {kk: (tuple(vv) if isinstance(vv, list) else vv)
               for kk, vv in got.items()}
    check(f"anchor {k}", got == want, f"got {got!r} want {want!r}")

# 2+3: dispatch equivalence + expected decisions
EXPECTED = {
    True: {"decided": ["w2", "w4", "w6"],
           "events": [["dispatch_skipped_duplicate", "w5"]]},
    False: {"decided": ["w2", "w6"],
            "events": [["dispatch_deferred_cap", "w3"],
                       ["dispatch_deferred_cap", "w4"],
                       ["dispatch_deferred_cap", "w5"]]},
}
for lanes_live in (True, False):
    a = run_scenario(False, lanes_live)
    b = run_scenario(True, lanes_live)
    tag = "lanes-live" if lanes_live else "pre-lane-cap"
    check(f"{tag}: defaults == fleet-yaml decisions",
          a["decided"] == b["decided"] and a["events"] == b["events"],
          f"A={a['decided']}/{a['events']} B={b['decided']}/{b['events']}")
    exp = EXPECTED[lanes_live]
    check(f"{tag}: decisions match pinned semantics",
          a["decided"] == exp["decided"] and a["events"] == exp["events"],
          f"got {a['decided']}/{a['events']} want {exp}")

print()
if fails:
    print(f"TEST_GOLDEN: FAIL ({len(fails)} failing)")
    sys.exit(1)
print("TEST_GOLDEN: ALL PASS")
