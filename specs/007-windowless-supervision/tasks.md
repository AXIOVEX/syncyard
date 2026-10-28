# Tasks — 007 Windowless Supervision

- [x] T001 — Fix `setup-runner.ps1` to start runners hidden
      (-WindowStyle Hidden) and drop the "keep the window open"
      instruction.
- [x] T002 — Write the tray supervisor (`runner/tray/SyncyardTray.cs`):
      per-lane state, hidden starts, restart cap 3/hour then OWNER
      NEEDED, stray-console hiding, HKCU Run logon start, log file.
- [x] T003 — Write the installer (`runner/tray/install-tray.ps1`):
      fetch source, compile with in-box csc, install under
      Development\Syncyard\tray, register the Run key, launch.
- [ ] T004 — Owner-session install on TRISTEN-DESKTOP; verify the tray
      is present and all lanes show running. (Owner session, with the
      lanes stand-up.)
- [ ] T005 — Post-install window/process inventory job: no visible
      runner consoles, no lingering payload processes.
- [ ] T006 — Lane identity jobs pass under tray supervision (spec 002
      T005), then the fleet resumes on lanes.
