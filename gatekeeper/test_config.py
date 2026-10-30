#!/usr/bin/env python3
"""Config loader battery (spec 010 FR-001/FR-002, T005 slice).

Run: python3 test_config.py [example.yaml]
Asserts:
  1. The shipped example config parses and validates.
  2. GOLDEN: the example reproduces the pre-config constants
     exactly (lanes, watermarks, budgets, repos, workflows,
     default cwds, marker pattern, log cap).
  3. No file at all -> defaults equal the same constants.
  4. A partial override merges over defaults.
  5. Invalid files fail closed with named ConfigErrors
     (warn>=escalate, unknown host, bad budget order,
     duplicate key, bad executing mode).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfgmod  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    HERE, "..", "config", "syncyard.example.yaml")

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def expect_error(name, text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        cfgmod.load_config(path)
        check(name, False, "loaded without error")
    except cfgmod.ConfigError as e:
        check(name, True)
        print(f"     error: {e}")
    finally:
        os.unlink(path)


# 1+2: example parses and is golden against the constants.
cfg = cfgmod.load_config(EXAMPLE)
check("example loads", True)
check("golden door_repo", cfg["door_repo"] == "tbitcs/desktop-runner")
check("golden project_repo", cfg["project_repo"] == "AXIOVEX/syncyard")
check("golden workflows", cfg["workflows"] == ["run.yml", "wsl.yml", "grab.yml"])
check("golden budget", (cfg["budget"]["standdown_remaining"],
                        cfg["budget"]["critical_remaining"]) == (1000, 500))
check("golden marker pattern",
      cfg["markers"]["pattern"] == r"^[A-Z][A-Z0-9_]{2,}([ :]|$)")
check("golden log cap", cfg["retention"]["human_log_max_bytes"] == 1000000)
check("golden cwd windows", cfg["hosts"]["desktop"]["cwd"]["run.yml"] == r"C:\Users\trist")
check("golden cwd grab null", cfg["hosts"]["desktop"]["cwd"]["grab.yml"] is None)
check("golden cwd wsl", cfg["hosts"]["desktop-wsl"]["cwd"]["wsl.yml"] == "/home/tpierson")
check("golden wsl via+distro", cfg["hosts"]["desktop-wsl"]["via"] == "desktop"
      and cfg["hosts"]["desktop-wsl"]["distro"] == "Ubuntu-24.04")
for lane, (q, mode, vals) in {
    "quick": ((10, 30), "fixed", (5, 15)),
    "normal": ((20, 45), "fixed", (45, 90)),
    "long": ((45, 120), "expectation", (90, 180)),
    "gpu": ((30, 90), "expectation", (120, 240)),
}.items():
    L = cfg["lanes"][lane]
    key = "values" if mode == "fixed" else "floor"
    check(f"golden lane {lane}",
          tuple(L["queued"]) == q and L["executing"]["mode"] == mode
          and tuple(L["executing"][key]) == vals
          and L["runner_label"] == f"lane-{lane}" and L["host"] == "desktop")

# 3: defaults (no file) equal the golden example on the fleet surface.
os.environ.pop(cfgmod.ENV_VAR, None)
dflt = cfgmod.load_config("/nonexistent/path.yaml") if False else None
import importlib
# load with an explicit missing default location: point env at a tmp name that does not exist is an error by design;
# instead call with path=None after removing any beside-file config.
beside = os.path.join(HERE, cfgmod.CONFIG_FILENAME)
check("no beside-file config in repo gatekeeper dir", not os.path.exists(beside))
dflt = cfgmod.load_config(None)
check("defaults == example fleet surface",
      dflt["lanes"] == cfg["lanes"] and dflt["hosts"] == cfg["hosts"]
      and dflt["budget"] == cfg["budget"] and dflt["workflows"] == cfg["workflows"])

# 4: partial override merges.
with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
    f.write("budget:\n  standdown_remaining: 2000\nlanes:\n  quick:\n    queued: [5, 15]\n")
    path = f.name
over = cfgmod.load_config(path)
os.unlink(path)
check("override merges", over["budget"]["standdown_remaining"] == 2000
      and over["budget"]["critical_remaining"] == 500
      and over["lanes"]["quick"]["queued"] == [5, 15]
      and over["lanes"]["quick"]["executing"]["values"] == [5, 15])

# 5: invalid files fail closed, named.
expect_error("reject warn>=escalate",
             "lanes:\n  quick:\n    queued: [30, 30]\n")
expect_error("reject unknown lane host",
             "lanes:\n  quick:\n    host: nowhere\n")
expect_error("reject budget order",
             "budget:\n  standdown_remaining: 100\n  critical_remaining: 500\n")
expect_error("reject duplicate key",
             "version: 1\nversion: 1\n")
expect_error("reject bad executing mode",
             "lanes:\n  quick:\n    executing:\n      mode: sideways\n")
expect_error("reject bad version", "version: 2\n")

print()
if fails:
    print(f"TEST_CONFIG: FAIL ({len(fails)} failing)")
    sys.exit(1)
print("TEST_CONFIG: ALL PASS")
