# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-27

### Fixed

- Clients: the run-discovery polling loop used an unused loop variable
  (`for i in $(seq ...)`), which failed the ShellCheck CI step
  (SC2034). The loops now use the conventional throwaway variable;
  behavior is unchanged. Caught by the first CI run of the scaffold.

## [0.1.0] - 2026-10-27

### Added

- Project scaffold: README with the architecture, security model,
  quickstart, and lane table; the Sallyport logo
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
