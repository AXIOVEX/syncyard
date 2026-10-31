#!/usr/bin/env python3
"""Chaos battery for the backchannel agent (spec 010 T012).

Runs the REAL backchannel/agent.sh against a local file://
channel repo and subjects it to the failure cases:

  1. start: heartbeat appears carrying a passing self-test
  2. a command executes and its output lands (id-matched)
  3. duplicate id with a different body is NOT re-executed
  4. corrupt cmd.json: agent survives, heartbeat keeps moving
  5. STOP file: execution halts, heartbeat reports stopped
  6. STOP removed: execution resumes
  7. kill -9 + restart: heartbeat resumes, the last executed
     id is NOT replayed (the replay guard survives), and a
     fresh id executes

Everything lives in a temp dir; the agent is pointed at it via
SYNCBC_BASE / SYNCBC_REPO_URL / SYNCBC_POLL_S=1. Stdlib only.

Run: python3 backchannel/test_chaos.py   (a few minutes)
"""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(HERE, "agent.sh")
CHANNEL = "channels/syncyard-dev"
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name
          + (f" — {detail}" if detail and not cond else ""), flush=True)
    if not cond:
        fails.append(name)


def run(cmd, cwd=None, env=None, timeout=60):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def git_env(home):
    env = dict(os.environ)
    env["HOME"] = home
    return env


def wait_for(pred, timeout_s, what):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        val = pred()
        if val:
            return val
        time.sleep(0.5)
    print(f"  (timeout waiting for {what})", flush=True)
    return None


class Rig:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="bc-chaos-")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        with open(os.path.join(self.home, ".gitconfig"), "w") as f:
            f.write("[user]\n\tname = Chaos Test\n\temail = chaos@test\n"
                    "[init]\n\tdefaultBranch = main\n")
        self.env = git_env(self.home)
        self.remote = os.path.join(self.root, "remote.git")
        run(["git", "init", "--bare", "-b", "main", self.remote], env=self.env)
        self.driver = os.path.join(self.root, "driver")
        run(["git", "clone", "-q", self.remote, self.driver], env=self.env)
        chan = os.path.join(self.driver, CHANNEL)
        os.makedirs(chan)
        with open(os.path.join(chan, "README.md"), "w") as f:
            f.write("chaos channel\n")
        run(["git", "-C", self.driver, "add", "-A"], env=self.env)
        run(["git", "-C", self.driver, "commit", "-q", "-m", "seed"],
            env=self.env)
        run(["git", "-C", self.driver, "push", "-q", "origin", "main"],
            env=self.env)
        self.base = os.path.join(self.root, "agent-base")
        self.agent_env = dict(self.env)
        self.agent_env.update({
            "SYNCBC_BASE": self.base,
            "SYNCBC_REPO_URL": "file://" + self.remote,
            "SYNCBC_POLL_S": "1",
            "SYNCBC_TIMEOUT_S": "30",
        })
        self.proc = None
        self.agent_log = os.path.join(self.root, "agent-stdout.log")

    # -- channel helpers -------------------------------------------------
    def chan_file(self, name):
        return os.path.join(self.base, "repo", CHANNEL, name)

    def read_chan_json(self, name):
        try:
            with open(self.chan_file(name)) as f:
                return json.load(f)
        except Exception:
            return None

    def push(self, files):
        """files: {relpath: content-or-None(delete)} committed+pushed.
        The agent pushes heartbeat/out commits too, so the driver
        rebases onto the remote head before (and if needed during)
        each push."""
        run(["git", "-C", self.driver, "pull", "-q", "--rebase"], env=self.env)
        for rel, content in files.items():
            p = os.path.join(self.driver, rel)
            if content is None:
                run(["git", "-C", self.driver, "rm", "-q", "--ignore-unmatch",
                     rel], env=self.env)
                if os.path.exists(p):
                    os.unlink(p)
            else:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(content)
                run(["git", "-C", self.driver, "add", rel], env=self.env)
        run(["git", "-C", self.driver, "commit", "-q", "-m", "chaos push",
             "--allow-empty"], env=self.env)
        r = run(["git", "-C", self.driver, "push", "-q", "origin", "main"],
                env=self.env)
        if r.returncode != 0:  # the agent pushed in between; rebase + retry
            run(["git", "-C", self.driver, "pull", "-q", "--rebase"],
                env=self.env)
            r = run(["git", "-C", self.driver, "push", "-q", "origin", "main"],
                    env=self.env)
        assert r.returncode == 0, "driver push failed: " + r.stderr

    def push_cmd(self, cid, body):
        doc = {"id": cid, "body": body,
               "sha256": hashlib.sha256(body.encode()).hexdigest(),
               "created_at": "2026-10-31T00:00:00Z"}
        self.push({CHANNEL + "/cmd.json": json.dumps(doc, indent=1)})

    # -- agent process ---------------------------------------------------
    def start_agent(self):
        out = open(self.agent_log, "ab")
        self.proc = subprocess.Popen(
            ["bash", AGENT], env=self.agent_env, stdout=out,
            stderr=subprocess.STDOUT, start_new_session=True)

    def kill_agent(self, sig=signal.SIGKILL):
        if self.proc and self.proc.poll() is None:
            os.killpg(os.getpgid(self.proc.pid), sig)
            self.proc.wait(timeout=15)

    def agent_log_text(self):
        try:
            with open(os.path.join(self.base, "agent.log")) as f:
                return f.read()
        except Exception:
            return ""

    def cleanup(self):
        self.kill_agent()
        if os.environ.get("CHAOS_KEEP"):
            print(f"rig preserved at {self.root}")
        else:
            shutil.rmtree(self.root, ignore_errors=True)


def main():
    rig = Rig()
    try:
        # 1: start + self-test heartbeat
        rig.start_agent()
        hb = wait_for(lambda: rig.read_chan_json("heartbeat.json"),
                      60, "first heartbeat")
        check("start: heartbeat written", hb is not None)
        st = (hb or {}).get("self_test") or {}
        check("start: self-test present and ok", st.get("ok") is True,
              f"self_test={st}")
        check("start: self-test checks all true",
              all((st.get("checks") or {}).values()) and len(st.get("checks") or {}) == 6,
              f"checks={st.get('checks')}")

        # 2: a command executes
        rig.push_cmd("chaos-1", "echo CHAOS_ONE")
        out = wait_for(lambda: (rig.read_chan_json("out.json") or {}).get("id") == "chaos-1"
                       and rig.read_chan_json("out.json"), 45, "chaos-1 out")
        check("execute: out.json id-matched", out is not None)
        check("execute: stdout carries the marker",
              out is not None and "CHAOS_ONE" in (out.get("stdout_tail") or ""))

        # 3: duplicate id, different body: NOT re-executed
        rig.push_cmd("chaos-1", "echo CHAOS_TWO")
        time.sleep(5)
        out = rig.read_chan_json("out.json") or {}
        check("duplicate: out still the first execution",
              "CHAOS_ONE" in (out.get("stdout_tail") or "")
              and "CHAOS_TWO" not in (out.get("stdout_tail") or ""))
        check("duplicate: executed exactly once in agent log",
              rig.agent_log_text().count("executing id=chaos-1") == 1)

        # 4: corrupt cmd.json
        hb_ts_before = (rig.read_chan_json("heartbeat.json") or {}).get("ts")
        rig.push({CHANNEL + "/cmd.json": "this is not json{{{\n"})
        check("corrupt: agent process alive", rig.proc.poll() is None)
        moved = wait_for(lambda: (rig.read_chan_json("heartbeat.json") or {}).get("ts")
                         not in (None, hb_ts_before), 25, "heartbeat advance")
        check("corrupt: heartbeat keeps moving", bool(moved),
              f"ts stuck at {hb_ts_before}")
        out = rig.read_chan_json("out.json") or {}
        check("corrupt: nothing new executed", out.get("id") == "chaos-1")

        # 5: STOP halts execution, heartbeat reports stopped
        rig.push({CHANNEL + "/STOP": "chaos test\n"})
        rig.push_cmd("chaos-2", "echo CHAOS_STOPPED")
        stopped = wait_for(lambda: (rig.read_chan_json("heartbeat.json") or {}).get("stopped") is True,
                           25, "stopped heartbeat")
        check("STOP: heartbeat reports stopped=true", bool(stopped))
        time.sleep(3)
        out = rig.read_chan_json("out.json") or {}
        check("STOP: queued command not executed", out.get("id") != "chaos-2")

        # 6: STOP removed: execution resumes
        rig.push({CHANNEL + "/STOP": None})
        rig.push_cmd("chaos-3", "echo CHAOS_THREE")
        out = wait_for(lambda: (rig.read_chan_json("out.json") or {}).get("id") == "chaos-3"
                       and rig.read_chan_json("out.json"), 45, "chaos-3 out")
        check("resume: command executes after STOP removed",
              out is not None and "CHAOS_THREE" in (out.get("stdout_tail") or ""))

        # 7: kill -9 + restart: no replay, fresh ids execute
        hb_ts_pre = (rig.read_chan_json("heartbeat.json") or {}).get("ts")
        rig.kill_agent(signal.SIGKILL)
        time.sleep(1)
        rig.start_agent()
        # The pre-kill heartbeat file persists in the clone, so a bare
        # ts read proves nothing (it returns the stale value instantly
        # and races the restarted agent's first cycle - the PR #26 CI
        # flake). Require the ts to ADVANCE past the pre-kill value,
        # twice (two full post-restart cycles), before the replay probe.
        def advanced_past(prev):
            ts = (rig.read_chan_json("heartbeat.json") or {}).get("ts")
            return ts if ts and prev and ts > prev else None
        hb_first = wait_for(lambda: advanced_past(hb_ts_pre), 60,
                            "post-restart heartbeat advance")
        check("restart: heartbeat resumes", hb_first is not None)
        hb_second = wait_for(lambda: advanced_past(hb_first), 60,
                             "second post-restart heartbeat") if hb_first else None
        check("restart: heartbeat advances twice", hb_second is not None)
        rig.push_cmd("chaos-3", "echo CHAOS_REPLAY")
        # Poll the whole window: any appearance of the replay body in
        # out.json fails fast; a full quiet window is the pass.
        replayed = None
        deadline = time.time() + 12
        while time.time() < deadline:
            out = rig.read_chan_json("out.json") or {}
            if "CHAOS_REPLAY" in (out.get("stdout_tail") or ""):
                replayed = out
                break
            time.sleep(0.5)
        out = rig.read_chan_json("out.json") or {}
        check("restart: last executed id not replayed",
              replayed is None
              and "CHAOS_THREE" in (out.get("stdout_tail") or ""))
        check("restart: chaos-3 executed exactly once across restart",
              rig.agent_log_text().count("executing id=chaos-3") == 1)
        rig.push_cmd("chaos-4", "echo CHAOS_FOUR")
        out = wait_for(lambda: (rig.read_chan_json("out.json") or {}).get("id") == "chaos-4"
                       and rig.read_chan_json("out.json"), 45, "chaos-4 out")
        check("restart: fresh id executes",
              out is not None and "CHAOS_FOUR" in (out.get("stdout_tail") or ""))
    finally:
        rig.cleanup()

    print()
    if fails:
        print(f"TEST_CHAOS: FAIL ({len(fails)} failing)")
        sys.exit(1)
    print("TEST_CHAOS: ALL PASS")


if __name__ == "__main__":
    main()
