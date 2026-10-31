# Backchannel recovery runbook (spec 009 FR-007, spec 010 T013)

The failsafe backchannel exists for the moments the normal door
cannot help: Syncyard itself is down or blocked, the tray is the
casualty, or a runner process cannot do what only the owner's
interactive session can. It is a **development and recovery
channel only** — never a job route. The gatekeeper remains the
sole dispatch door; the agent never writes queue records.

Channel facts: private repo `tbitcs/syncyard-backchannel`,
channel dir `channels/syncyard-dev/`, files `cmd.json` /
`out.json` / `heartbeat.json` / `STOP`. Client: `backchannel/
bc.py` (`heartbeat`, `status`, `send`, `wait`). Agent:
`backchannel/agent.sh`, a WSL systemd user service
(`syncyard-backchannel.service`) on the desktop, ~60 s cycle,
git-protocol sync only (no REST quota).

## Health checks (run these first)

- `python3 backchannel/bc.py heartbeat` — prints the heartbeat,
  its age, and the agent's start-up self-test
  (`BC_SELFTEST ok=...`). **Stale = age > 300 s.**
- `gk status` prints the same heartbeat age as its second line
  and raises `!! BACKCHANNEL STALE` past 300 s (spec 010 T011).
- On the desktop (WSL): `systemctl --user status
  syncyard-backchannel.service` and the tail of
  `~/syncyard-backchannel/agent.log`.

## The four recovery cases (FR-007)

Send each body with `bc.py send --file body.sh` (it stamps a
fresh id + sha256), then `bc.py wait --id <id>`.

### 1. Restart the Syncyard tray in the owner's session

A runner job cannot start a process in the owner's interactive
session when the tray itself is the casualty; a one-shot
scheduled task can. This body registers, runs, and removes it
(paths are the packaged install's; adjust the user if needed):

```bash
powershell.exe -NoProfile -Command "
  \$exe = \"\$env:LOCALAPPDATA\Programs\SyncyardTray\SyncyardTray.exe\";
  \$a = New-ScheduledTaskAction -Execute \$exe;
  \$t = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1);
  Register-ScheduledTask -TaskName SyncyardTrayRestart -Action \$a -Trigger \$t -Force | Out-Null;
  Start-ScheduledTask -TaskName SyncyardTrayRestart;
  Start-Sleep -Seconds 5;
  Unregister-ScheduledTask -TaskName SyncyardTrayRestart -Confirm:\$false
"
```

Verify: the tray icon is back, and `tray.log` (case 2) shows a
fresh "tray started".

### 2. Read tray.log

```bash
tail -n 200 "/mnt/c/Users/trist/AppData/Local/SyncyardTray/tray.log"
```

### 3. Restart a runner lane

The tray supervises the runners and restarts a dead one (it
caps restarts at 3 per runner per hour, then raises OWNER
NEEDED). Stopping the lane's runner process is enough:

```bash
powershell.exe -NoProfile -Command "
  Get-CimInstance Win32_Process -Filter \"Name='actions.runner.exe'\" |
    Where-Object { \$_.CommandLine -like '*Syncyard\runners\lane-normal*' } |
    ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }
"
```

(Name the lane you mean — `lane-quick`, `lane-normal`,
`lane-long`, `lane-gpu`.) Verify in `tray.log` and with the
runner's service state; if the tray has hit its restart cap,
that is an owner decision, not a retry loop.

### 4. Read-only network diagnostics

```bash
powershell.exe -NoProfile -Command "
  Get-NetAdapter | Format-Table Name, Status, LinkSpeed;
  Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias, IPAddress, PrefixOrigin;
  Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Format-Table InterfaceAlias, NextHop, RouteMetric
"
```

## Failure triage

- **Heartbeat stale, service inactive** — start it:
  `systemctl --user start syncyard-backchannel.service`. If it
  fails, `agent.log` holds the reason; the common one is a git
  credential problem on the channel repo.
- **Heartbeat stale, service active** — read the tail of
  `agent.log`: a hung `git pull` (network) or a long-running
  command body (default timeout 600 s) are the usual causes.
  The agent is single-threaded by design; a command that must
  run longer should say so (`timeout_s` in cmd.json).
- **`BC_SELFTEST ok=False`** — the failing check names itself:
  `repo_reachable` (network/credential), `channel_writable`
  (clone damaged — delete `~/syncyard-backchannel/repo` and
  restart the service; it re-clones), `log_writable` /
  `base_writable` (disk/permissions on the WSL home).
- **STOP present** — execution is halted on purpose
  (`heartbeat stopped=true`). To resume, delete
  `channels/syncyard-dev/STOP` in a channel commit; the agent
  resumes on its next cycle.
- **A command was not executed** — check `agent.log` for
  `SHA MISMATCH` (recompute the sha256 over the exact body and
  re-send with a FRESH id; ids are never reused), and confirm
  the id differs from `last_executed_id` in the heartbeat (a
  replayed id is refused by design).
- **Corrupt cmd.json** — harmless by design (the agent skips
  it and keeps heartbeating); overwrite it with a fresh send.
- **Reinstall** — from a checkout of AXIOVEX/syncyard, run
  `backchannel/install-backchannel.sh` inside WSL. It is
  idempotent: it refreshes the agent copy, rewrites the unit,
  restarts the service, and prints `SYNCBC_INSTALL_OK 1` when
  the service is active.

Every backchannel problem is reported to the **Desktop Access
chat**, which owns Syncyard (owner's order, 2026-10-27). Do not
work around a sick backchannel in a program chat.
