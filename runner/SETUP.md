# Runner setup — the owner session runbook

Everything in this runbook happens **in one sitting, in the owner's own
signed-in session on the machine** — not from inside an Actions job
(job teardown kills child processes, so a job can never install or
start the runner that would replace it) and not under any other user's
profile. Runners run as **user-window processes** under the owner's
account, never as a Windows service.

You will: register four lane runners to this repository, install the
runner watchdog, and prove each lane with an identity job. Budget about
half an hour of mostly waiting.

## Before you start

- The machine is powered on, signed in as the owner, and will not sleep
  or reboot during the session.
- You have `gh` authenticated on some machine where you can run one
  command at step 2 (the control machine is fine — the token travels by
  your hands only, is used once, and is never written down anywhere
  that persists).
- Any jobs queued against a previous runner repository have finished
  or been accounted for by their programs (see
  [docs/MIGRATION.md](../docs/MIGRATION.md), gate 5).
- PowerShell 7 (`pwsh`) is installed — the dispatch workflows run their
  steps under it. PowerShell 5.1 also works for the setup and watchdog
  scripts (they are ASCII-only on purpose).

## Step 1 — Lay out the lanes

Four registrations, one directory each:

| Lane | Runner name (example) | Directory | Extra label |
|---|---|---|---|
| quick | `desktop-quick` | `C:\actions-runner-quick` | `lane-quick` |
| normal | `desktop-normal` | `C:\actions-runner-normal` | `lane-normal` |
| long | `desktop-long` | `C:\actions-runner-long` | `lane-long` |
| gpu | `desktop-gpu` | `C:\actions-runner-gpu` | `lane-gpu` |

If the machine already has a runner from a previous setup, it becomes
the **long** lane: re-register its existing directory under this
repository with the `lane-long` label (step 3 with `--replace` handles
the re-registration; the directory stays).

Names above are examples — use a consistent `<machine>-<lane>` scheme
of your own. What matters is the label, the directory, and one runner
per directory.

## Step 2 — Fetch a registration token

Registration tokens **expire in about an hour**, and steps 2–4 are one
sitting for exactly that reason. From the control machine:

```bash
gh api -X POST repos/AXIOVEX/sallyport/actions/runners/registration-token --jq .token
```

Keep the value in the terminal only. If it expires mid-session, fetch
a fresh one and continue — nothing is harmed. One token can register
several runners while it lives.

## Step 3 — Register and start each lane

From this repository's checkout, in PowerShell on the machine, once per
lane (substitute your token, names, and directories from step 1):

```powershell
.\runner\setup-runner.ps1 -Name "desktop-quick"  -Labels "lane-quick"  -RunnerDir "C:\actions-runner-quick"  -RegistrationToken <token> -Start
.\runner\setup-runner.ps1 -Name "desktop-normal" -Labels "lane-normal" -RunnerDir "C:\actions-runner-normal" -RegistrationToken <token> -Start
.\runner\setup-runner.ps1 -Name "desktop-long"   -Labels "lane-long"   -RunnerDir "C:\actions-runner-long"   -RegistrationToken <token> -Start
.\runner\setup-runner.ps1 -Name "desktop-gpu"    -Labels "lane-gpu"    -RunnerDir "C:\actions-runner-gpu"    -RegistrationToken <token> -Start
```

Each run downloads the pinned runner package, registers the runner to
this repository only, and opens its `run.cmd` in a user window. Leave
the four windows open — closing one stops that lane's runner (the
watchdog in step 4 restarts it within minutes, but an open window is
the expected resting state).

Confirm all four show as **online** (one API call):

```bash
gh api repos/AXIOVEX/sallyport/actions/runners --jq '.runners[] | "\(.name) \(.status) labels=\([.labels[].name] | join(","))"'
```

## Step 4 — Install the runner watchdog

The watchdog checks every 5 minutes whether each runner's listener
process is alive and restarts a dead one (cap: 3 restarts per runner
per rolling hour; past the cap it logs OWNER NEEDED and stops
restarting that runner).

1. Copy `runner\runner-watchdog.ps1` to
   `C:\actions-runner-watchdog\runner-watchdog.ps1` on the machine.
2. Edit its `$RunnerDirs` config array to list **all four** lane
   directories from step 1.
3. Create the scheduled task (in the owner's session, PowerShell):

```powershell
schtasks /Create /TN "RunnerWatchdog" /SC MINUTE /MO 5 /RU <owner-user> /RL LIMITED /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\actions-runner-watchdog\runner-watchdog.ps1"
```

4. Run it once by hand (`schtasks /Run /TN "RunnerWatchdog"`) and check
   `C:\actions-runner-watchdog\status.json`: every runner should report
   `listener_alive: true` and `last_action: "none (listener alive)"`.

## Step 5 — Prove each lane (identity jobs)

No real dispatch routes to a lane before its identity proof is on
record. For each lane, dispatch the matching workflow through the
gatekeeper (or, for this proof only, directly) with a script that
prints markers:

- Windows proof (`run.yml`): prints
  `IDENTITY host=<computername> user=<domain\user>` from
  `$env:COMPUTERNAME` and `whoami`.
- WSL proof (`wsl.yml`): prints `IDENTITY_WSL user=<user> home=$HOME`
  from `whoami` and the home path.
- GPU lane extra (Windows side): prints both graphics cards, for
  example `GPU_LIST <name 1> | <name 2>` from the display-driver query.

Read the verdicts from the marker lines in the run logs — never from
the green checkmark alone. Record, per lane: runner name, machine
name, Windows user, WSL user, and the run ids. File the record with the
fleet's program notes. A lane whose proof fails carries no real work
until it passes.

## Troubleshooting

- **Registration token rejected / expired.** Fetch a fresh token
  (step 2) and re-run the failing lane's setup. The script skips the
  download when the package is already extracted.
- **A runner shows offline.** Check its window first — most "offline"
  runners are a closed window. Start it again with
  `& "C:\actions-runner-<lane>\run.cmd"`, and confirm the watchdog's
  `status.json` sees the listener.
- **Watchdog says OWNER NEEDED.** The restart cap tripped: the runner
  is dying repeatedly, which is a real fault, not a watchdog fault.
  Read `C:\actions-runner-watchdog\watchdog.log` and the runner's own
  `_diag` logs in its directory before restarting anything by hand.
- **A dispatch queues forever on one lane.** Check the runner is
  online *and carries the exact lane label* — a label mismatch queues
  silently forever. `gh api .../actions/runners` (step 3) shows every
  label.
- **WSL-side jobs cannot reach a device on the machine's local
  network.** Some networks are visible only from the owner's own WSL
  distribution, not from the runner's default WSL context. Hardware
  scenario jobs handle this by invoking the owner's distribution
  explicitly — see the board-job rules in [SKILL.md](../SKILL.md).
