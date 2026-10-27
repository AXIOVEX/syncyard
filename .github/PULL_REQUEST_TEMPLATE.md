## Summary

<!-- What changes, in plain language. -->

## Why

<!-- The problem this fixes or the capability this adds. Link the issue if there is one. -->

## Checklist

- [ ] `CHANGELOG.md` has an entry under the new version (or under Unreleased, if the maintainer will cut the version at merge).
- [ ] `VERSION` is bumped per semantic versioning (breaking = major, feature = minor, fix = patch).
- [ ] No tokens, credentials, or registration material anywhere in the change.
- [ ] Shell/Python/PowerShell changes pass CI locally or by inspection (CI will verify).

## Security checklist (required — see SECURITY.md)

- [ ] No workflow binds self-hosted runners to `pull_request`, `pull_request_target`, `issues`, or any other trigger a user without write access can cause. Runner workflows remain `workflow_dispatch` only.
- [ ] CI still runs on GitHub-hosted runners only.
- [ ] No runner registration scope widened (repository only, never organization).
- [ ] If this changes the dispatch or gatekeeper behavior, the marker-verdict rule and the API discipline in `docs/STANDARD.md` still hold.
