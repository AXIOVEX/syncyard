# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Fixed
- Gatekeeper durable writes (spec 001 FR-012): every queue, ledger
  and control-file write is now write-verify-retry — unbuffered
  write, read-back byte verification, bounded retries with backoff,
  loud failure when unverifiable. The loader skips unreadable
  records with a warning, and a submission reports queued only
  after the loader verifies the record written. Defect escalation
  2026-10-27: the host VM intermittently refuses writes and can
  silently drop a buffered write, leaving a 0-byte file.


### Added

- Tray offline state is unmistakable: with no runners up (or one
  faulted) the tray mark renders in grayscale under its red slash;
  the color states mean at least one runner is live (FR-007).
- Tray icon and menu (spec 007 FR-007/FR-008): the notification
  icon is the official mark loaded from a copy embedded in the
  program itself — clean when all runners are up, amber slash when
  some are down, red slash when none are up or one has faulted. The
  menu gains Start all and Stop all above the per-lane controls.
- Runner directories move under the user profile
  (`%USERPROFILE%\Development\Syncyard\runners\<lane>`) — nothing
  Syncyard-owned sits in the drive root. Tray and watchdog defaults
  and the setup docs follow; the tray installer is rebuilt against
  the new locations (spec 007 T010).
- Spec 007 T007 — a real Windows installer for the tray:
  `SyncyardTray-Setup-0.1.0.exe` (NSIS; per-user, silent `/S` mode,
  registered uninstaller), published as a GitHub Release asset with
  a SHA-256, plus `assets/logo.ico` and the tray icon now carrying
  the project mark with a state badge. README and SETUP.md document
  the download route and manual from-source installation.
- Spec 007 — windowless runner supervision: the Syncyard Tray app
  (`runner/tray/SyncyardTray.cs` + `install-tray.ps1`) supervises the
  runners from the owner's tray — hidden starts, per-lane state,
  capped restarts with an OWNER NEEDED alert, stray-console hiding,
  logon autostart. `setup-runner.ps1` now starts runners hidden too,
  and the tray subsumes the planned watchdog scheduled task.
- Gatekeeper push notifications: jobs register a chat with
  `--notify-chat` (on submit or adopt) and receive started (with
  expected length), completed (marker verdict), and W2-escalation
  pushes via the new `gk outbox` command — no polling and no new
  infrastructure (spec 001 FR-011).
- Spec 006 closed: the polish pull request merged 2026-10-27 under
  the owner's one-time protection pause, with protection verified
  identical afterward.
- New project logo: a marshalling-yard mark (three lanes converging through
  one gate) as `assets/logo.svg`, with rendered `assets/logo.png` and
  `assets/social-preview.png` alongside it. Replaces the previous emblem.
- `CONTRIBUTING.md` (development setup, the self-hosted security invariant
  for contributions, review and changelog discipline) and
  `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1).
- README badges for CI status and the latest release.
- `gk.py status` now leads with queued/running counts and an ISSUES
  section (watermark breaches, failed or pending log harvests, stale
  dispatches, completions without a marker verdict), and takes a
  `--repo` flag that adds project-repo health: latest CI runs, open
  Dependabot alerts, and open Dependabot pull requests.
- A daily health check reviews the status board, the ledger, CI, and
  Dependabot, and reports issues to the operating chat.
- Spec-kit + AEE governance: a project constitution
  (`.specify/memory/constitution.md`) and numbered specs under
  `specs/` (001 gatekeeper dispatch, 002 runner lanes, 003 status /
  logging / health, 004 WSL2 management, 005 fleet cutover,
  006 repository and governance), each with an `aee-claims.json`
  recording every requirement as a claim with evidence and a
  falsification test.
- The SKILL.md currency rule, stated in SKILL.md and CONTRIBUTING.md:
  SKILL.md is updated in the same change as any behavior change.
- Gatekeeper pause/resume: `gk pause --reason <text>` holds dispatch
  of program jobs (the watch pass continues; status shows the pause
  banner; sweep summaries print PAUSED) and `gk resume` clears it.
  Jobs submitted with `--maintenance` dispatch during a pause,
  bypassing the active cap and lane serialization but never the
  duplicate check — for operator work on the fleet itself.
- Gatekeeper stop/start and purge, completing the lifecycle CLI:
  `gk stop` is the hard halt (sweeps return before spending any API
  budget — no watch, no dispatch) and `gk start` clears both a stop
  and a pause. `gk purge` removes terminal (completed/cancelled) job
  records, dry-run unless `--yes`, with an optional
  `--older-than-days` filter and `--ledger` to archive the ledger
  to a fresh one.

### Fixed

- Log harvest now falls back to the REST logs archive when
  `gh run view --log` cannot read a run (observed in the field: some
  runs' logs are unreadable through the CLI but fine through the API).
  The harvest records which source supplied the log.
- Job-state saves fall back to a shell write when the host denies the
  native temp-file write path, so sweeps keep persisting state through
  intermittent write restrictions.

### Changed (logging)

- Sweeps now also write their one-line summary to a human-readable
  rotating log (`gatekeeper.log`, 1 MB, one backup) alongside the
  append-only JSON ledger.

### Changed

- **License: the project is now licensed under the Apache License,
  Version 2.0** (owner decision, 2026-10-27), superseding the
  all-rights-reserved terms the 0.1.x releases shipped with. The
  historical release entries below are unchanged.
- Project renamed from Sallyport to Syncyard. The repository is now
  `AXIOVEX/syncyard`; GitHub redirects the previous repository URL.
  Documentation, the agent skill, workflow and client repository
  constants, setup defaults, templates, and release metadata now use
  the Syncyard name.
- README now describes the project in terms of synchronized runner
  lanes: a marshalling yard for CPU and GPU jobs dispatched through
  GitHub Actions.
- The version stays at 0.1.1 for now, by owner decision: no version
  bump until the project is fully landed, passes full CI, and has
  served as the fleet's daily driver for a few days.

## [0.1.1] - 2026-10-27

### Fixed

- Clients: the run-discovery polling loop used an unused loop variable
  (`for i in $(seq ...)`), which failed the ShellCheck CI step
  (SC2034). The loops now use the conventional throwaway variable;
  behavior is unchanged. Caught by the first CI run of the scaffold.

## [0.1.0] - 2026-10-27

### Added

- Project scaffold: README with the architecture, security model,
  quickstart, and lane table; the project logo
  (`assets/logo.png` — a fortress gate with a raised portcullis and a
  dispatch arrow passing through).
- `SKILL.md`, the agent operating skill: gatekeeper commands, lane
  routing rules, the marker-verdict rule, API discipline, watermark
  escalation etiquette, hardware scenario-job rules, and the
  break-glass note.
- The gatekeeper (`gatekeeper/gk.py` with its README): one
  dispatch/watch door with API-headroom stand-down, duplicate-dispatch
  refusal, lane serialization, batched watching, marker harvesting,
  and watermark recording that never cancels.
- Runner kit (`runner/`): the dispatch-only workflows `run`, `wsl`,
  and `grab`; `setup-runner.ps1` for per-lane runner registration as a
  user-window process; `runner-watchdog.ps1` to keep runner listeners
  alive; `SETUP.md`, the owner-session runbook ending in per-lane
  identity proofs.
- Convenience clients (`clients/`) for interactive one-offs, with the
  gatekeeper named as the preferred route.
- `docs/STANDARD.md` — the fleet standard: API budget discipline,
  runner lanes, and job health (watermarks and the check-before-cancel
  ladder).
- `docs/MIGRATION.md` — the cutover plan with its gates: re-register
  runners under this repository during the setup session, prove each
  lane by identity job, delete the predecessor runner repositories
  only after that proof, and archive (never delete) the predecessor
  administration repository that holds the frozen emergency path.
- `SECURITY.md` — the security model for a public repository with
  self-hosted runners (dispatch-only triggers, hosted-only CI,
  repository-scoped registration, no secrets in the repo) and the
  private reporting route.
- Continuous integration on GitHub-hosted runners: Python syntax and
  an offline gatekeeper smoke test, ShellCheck on the clients, a
  PowerShell parse check on the runner scripts, a changelog/version
  check, and a guard that fails any workflow combining self-hosted
  runners with unprivileged triggers.
- Repository policies: pull request and issue templates, Dependabot
  for GitHub Actions, CODEOWNERS, and branch protection requiring a
  pull request, an approving review, and green CI.
- License: all rights reserved, © Axiovex Systems, LLC.
