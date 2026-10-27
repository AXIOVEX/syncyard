# Security policy

## Reporting a vulnerability

Please report security issues privately, not in public issues:

- Use GitHub's **private vulnerability reporting** for this repository
  (the "Report a vulnerability" button under the Security tab), or
- Contact the maintainers at Axiovex Systems, LLC directly.

We will acknowledge reports, investigate, and coordinate a fix and a
disclosure timeline with the reporter. Please give us a reasonable
window to fix an issue before publishing details.

## Supported versions

Only the latest release is supported. The version in the `VERSION` file
on the default branch is the current revision; fixes land there first,
with a version bump and a `CHANGELOG.md` entry.

## The security model

Syncyard is a **public** repository whose workflows run on the
operator's **own machines** through self-hosted GitHub Actions runners.
That combination is a known hazard class: on a typical public project,
anyone can open a pull request — and if a workflow that runs on a
self-hosted runner can be triggered by pull request activity, untrusted
code executes on the operator's hardware. Syncyard's design removes
that trigger surface. These rules are load-bearing:

1. **Dispatch only.** Every workflow that binds self-hosted runners
   (`run`, `wsl`, `grab`) is triggered **only** by `workflow_dispatch`.
   GitHub requires **write access** to the repository to dispatch a
   workflow, so only trusted collaborators can start a job.
2. **No unprivileged triggers, ever.** No workflow in this repository
   may bind self-hosted runners to `pull_request`,
   `pull_request_target`, `issues`, `issue_comment`, `fork`, or any
   other event that a user without write access can cause. This holds
   for edits, additions, and "temporary" experiments. Continuous
   integration checks every workflow file for these combinations.
3. **CI is hosted-only.** The CI workflow runs exclusively on
   GitHub-hosted runners. It never checks out or executes code on the
   self-hosted fleet.
4. **Repo-scoped registration.** Runners register to this repository
   only — never to an organization or enterprise — so a configuration
   mistake here cannot expose runners to other repositories.
5. **No secrets in the repository.** No tokens, credentials, keys, or
   registration material is committed, in any file, at any revision.
   Runner registration tokens are short-lived (about an hour), fetched
   at setup time through the API, passed to the setup script once, and
   never written to disk or echoed by it. If a token or credential is
   ever found in this repository's history, treat it as compromised:
   revoke it first, then report.
6. **Jobs run as a normal user, in the open.** Runners execute as
   user-window processes under the operator's own account (not as a
   service, not as administrator), and every job's script arrives as a
   workflow input whose content appears in the run log. There is no
   hidden execution path: if it ran, it is in the log, with the marker
   lines the job printed.
7. **The gatekeeper adds a choke point, not a bypass.** All routine
   dispatch flows through the gatekeeper, which enforces the shared
   API budget and duplicate checks. Convenience clients that dispatch
   directly still require the same write access and the same
   dispatch-only workflows — they bypass the budget bookkeeping, never
   the access control.

## What this model does not claim

- Anyone with write access to this repository can dispatch arbitrary
  code to the runners. Write access *is* the authorization boundary;
  grant it accordingly.
- Jobs run with the operator account's permissions on the runner
  machine. Syncyard does not sandbox job scripts; dispatch only code
  you trust, from people you trust.
- The frozen emergency admin path the operator keeps outside this
  repository is out of scope for this policy and carries no job
  traffic.
