# Feature Specification: Windowless Runner Supervision

**Feature Branch**: `007-windowless-supervision`

**Created**: 2026-10-27

**Status**: **In progress.** The tray supervisor is written
(`runner/tray/`); install on the desktop is an owner-session act
scheduled with the lanes stand-up.

**Direction (operator, 2026-10-27)**: desktop jobs spawning console
windows that stay open in his interactive session are a defect —
"don't do that; make this more robust." He ordered the RealLoom
pattern: a tray icon that supervises the runners, processes managed
the way systemd manages them on Linux; Linux targets use systemd
units.

## The gap

The runners were started by hand in visible console windows
(`setup-runner.ps1 -Start` opened `run.cmd` and told the operator to
keep the window open). Every registration added another permanent
window to the owner's desktop, and a closed window silently stopped
that runner. Job scripts that launch payloads without window
discipline compounded it (a capture job left a shell window behind).

Windows services — the usual "run it in the background" answer — are
the wrong tool for these runners: a service lives in session 0 and
cannot reliably reach the owner's WSL distro, audio devices, or
bench hardware, all of which real jobs use. The supervision has to
live in the owner's session, windowless. That is what a tray
supervisor is.

## Requirements

- **FR-001 — No runner console windows.** Runners are started with
  no console window created, and none is left open or lingering in
  the owner's interactive session. Stray runner consoles (for
  example from a manual `run.cmd`) are hidden by the supervisor.
- **FR-002 — Tray supervision.** A per-user tray application
  supervises every registered runner: it shows per-lane state in the
  tray, starts missing runners hidden, restarts a dead runner with
  the same cap discipline as the watchdog (3 restarts per runner per
  hour, then OWNER NEEDED, surfaced as a tray alert), and offers
  start/stop per lane. It starts at logon via the HKCU Run key, has
  no window of its own, and exiting it never kills a runner.
- **FR-003 — Session preserved.** Supervised runners stay in the
  owner's interactive session as his user, so jobs keep access to
  his WSL distro, GPU, audio, and attached devices. Runners are not
  converted to Windows services.
- **FR-004 — Job payload discipline.** A job script that starts a
  program starts it hidden or headless and cleans it up when the job
  ends. A visible window or a lingering payload process after a job
  completes is a defect in that job's script.
- **FR-005 — Linux targets use systemd.** Long-lived agents on Linux
  or WSL targets run as systemd units (the pattern the retired relay
  already used), never as detached shell windows.
- **FR-006 — Watchdog subsumed.** The tray supervisor replaces the
  planned `runner-watchdog.ps1` scheduled task (spec 002 FR-005);
  that task is not installed. The watchdog script remains in the
  repo as the headless fallback for a machine where the tray cannot
  run.

## Acceptance

- The tray installs from `runner/tray/install-tray.ps1` on the
  desktop, compiles with the in-box csc, and appears in the tray
  with all registered lanes shown.
- After install, a window/process inventory job reports no visible
  runner console windows and no lingering payload processes.
- Each lane passes its spec-002 identity job under tray supervision
  before real dispatch resumes.
- **FR-007 — The tray icon IS the project mark, and it shows
  connection at a glance (owner order 2026-10-27).** The
  notification-area icon is the official Syncyard mark, loaded from
  a copy embedded in the program itself (a mark file next to the
  program is only a fallback), in three states that read differently
  at a glance: all runners up = the clean mark in full color; some
  runners down = the color mark with an amber slash; no runners up,
  or a runner faulted = the mark in GRAYSCALE with a red slash, so
  all-disconnected never looks like all-connected.
  A plain colored dot is never the shipped icon.
- **FR-008 — Bulk controls in the tray menu (owner order
  2026-10-27).** The tray menu offers Start all and Stop all above
  the per-lane controls: Start all starts every stopped runner and
  clears any faulted state; Stop all asks once for confirmation,
  then stops every running runner.
