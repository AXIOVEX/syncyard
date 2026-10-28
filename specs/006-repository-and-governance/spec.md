# Feature Specification: The Repository as a Serious Open Tool

**Feature Branch**: `006-repository-and-governance`

**Created**: 2026-10-27

**Status**: **In progress.** The repository is public with full
branch protection, security scanning, templates, and CI. The brand
and governance layer — logo set, community documents, badges, the
SKILL.md currency rule, and this spec-kit + AEE catch-up — is
staged and lands as one pull request.

**Direction (operator, 2026-10-27)**: "add cool icon/logo for
Syncyard that we can use with the repo and stuff. and make sure the
repo is professionally done as a serious opensource tool." And the
same day: "make sure the skills.md is always updated anytime we
make changes. and use spec-kit + AEE for this project too. get that
set up and caught up with all the specs/requirements based on what
I've asked you to do and what is done."

## The gap

A tool other people (and other agents) are asked to trust needs the
surface of a serious project: a mark, the community documents,
honest badges, and — more than surface — a governance trail that
shows what was required, what was built, and what evidence separates
the two. Syncyard shipped its machinery first; this spec is the
professional layer, including the spec set that governs the whole
project retroactively to day one.

## Functional requirements

- **FR-001 — Professional baseline.** The repository carries:
  README with the project's narrative and operating discipline;
  SECURITY.md; pull-request and issue templates; Dependabot for
  GitHub Actions; code owners; branch protection on main (required
  review, code-owner review, required CI, no force pushes, no
  deletions); secret scanning with push protection.
- **FR-002 — The mark.** A logo set: one canonical vector
  (`assets/logo.svg`) — three lanes converging through one gate, the
  system's whole idea in one mark — plus a rendered
  `assets/logo.png` and `assets/social-preview.png` derived from
  the same geometry. The README header uses the vector.
- **FR-003 — Community documents.** CONTRIBUTING.md (development
  setup, the security invariant as an absolute contribution rule,
  review and changelog discipline, the SKILL.md currency rule) and
  CODE_OF_CONDUCT.md (Contributor Covenant 2.1). README badges show
  CI status and the latest release, and link only to live endpoints.
- **FR-004 — SKILL.md currency.** SKILL.md is updated in the same
  change as any change to behavior, commands, lanes, workflows, or
  operations (constitution §VII). A change that leaves it stale is
  incomplete and is called out in review.
- **FR-005 — Spec-kit + AEE governance.** The project is governed
  by `.specify/memory/constitution.md` and numbered specs under
  `specs/`, each with an `aee-claims.json`: every requirement a
  claim with evidence and a falsification test, its status honest
  (implemented only with the evidence named). This spec set —
  001 through 006 — is the catch-up covering everything the
  operator has asked for and everything built to date; new work
  gets a spec before or with its change.
- **FR-006 — CI.** Continuous integration runs on GitHub-hosted
  runners only and includes the security guard: a check that fails
  if any workflow binds self-hosted labels to an
  externally-triggerable event (constitution §II). CI must be green
  for a merge.
- **FR-007 — A real open-source license.** The project is licensed
  under the Apache License, Version 2.0 (owner decision, below):
  the LICENSE file carries the canonical text with the appendix
  copyright naming Axiovex Systems, LLC, and the README's license
  section says the same. No repository text may imply terms the
  license does not grant.

## Decisions (owner, 2026-10-27)

- **License — DECIDED: Apache License 2.0.** The operator directed
  "this should have real open source license." Apache-2.0 was
  chosen over MIT for its express patent grant, the standard choice
  for infrastructure tooling others are invited to adopt. It
  supersedes the all-rights-reserved terms the 0.1.x releases
  shipped with; the change is recorded in the changelog, and the
  historical release entries are not rewritten.
- **Merge path — DECIDED: the one-time pause, as the standing
  path.** Branch protection requires a code-owner review and the
  sole code owner cannot approve their own pull requests. The
  accepted path, first used for the rename merge on 2026-10-27 and
  ratified by the operator the same day ("merge path is
  accepted"): for each merge, the owner authorizes a brief pause of
  the PR-review subrule only, the pull request merges, and
  protection is restored and verified byte-identical against the
  pre-pause snapshot. The co-owner alternative was considered and
  not chosen.

## Claims discipline

"Professionally done" is claimed from the artifacts themselves —
the documents present, the protection read back, CI green on the
merge commit — never from the intention to polish.

## Out of scope

- Marketing surfaces (a website, launch posts): the repository is
  the whole surface for now.
- Any further license change (the Apache-2.0 adoption is decided,
  above).
