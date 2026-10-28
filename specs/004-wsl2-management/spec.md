# Feature Specification: WSL2 Management — Cleanup and Compact

**Feature Branch**: `004-wsl2-management`

**Created**: 2026-10-27

**Status**: **Specified; first cleanup run pending.** The cleanup
job is written and reviewed; its first submission waits on the WSL
subsystem's recovery from a launch failure found the same day
(a cleanup that cannot launch proves nothing).

**Direction (operator, 2026-10-27)**: "also add WSL2 management so
we can tell it to cleanup and compact the image. cleanup means
standard cleanups like clearing apt cache and other things. the
agent itself (you) may choose to do more cleanups before the image
compact."

## The gap

The desktop's WSL disk measured 1,007 GB with 23 GB free (98% used)
on 2026-10-27. The two big consumers — Docker images (~394 GB) and
volumes (~556 GB) — belong to programs and are claimed item by item
under the cleanup gate; but the operating system's own caches grow
unattended, and a virtual disk never shrinks on its own: freed space
inside the distro is not returned to the host until the image is
compacted.

## Functional requirements

- **FR-001 — Cleanup job.** A gatekeeper-submitted WSL job performs
  the standard OS cleanups: apt package cache cleared and package
  lists refreshed, the systemd journal vacuumed to 200 MB, `/tmp`
  and `/var/tmp` entries older than 7 days removed, and user cache
  entries older than 30 days removed. It ends with a filesystem
  trim. Every target reports byte sizes before and after as marker
  lines, with disk usage before and after the whole job.
- **FR-002 — Privilege honesty.** Privileged steps run through
  non-interactive sudo where the operator's account has it. Where
  it does not, the job degrades to the user-level targets and its
  markers say so — a partial cleanup reported as partial.
- **FR-003 — Hard scope-outs.** The cleanup job never touches:
  project trees or any path on a program's preserve list; Docker
  data (reported for size only — pruning is a separate claimed
  decision, and at least one pinned image in it is not deletable);
  package removal (`apt autoremove` may be proposed only as a
  dry-run report first).
- **FR-004 — Agent discretion, bounded.** Within the OS-cache class
  the operating agent may add cleanup targets of the same kind
  before a compact, under the operator's standing grant. Anything
  outside that class goes through the cleanup gate with claim
  lists, not this job.
- **FR-005 — Compact procedure.** Compacting is: cleanup job, trim,
  full WSL shutdown, host-side virtual-disk optimization, then
  verification by in-distro disk usage and the host-side image file
  sizes. It is scheduled with the operator in advance — the
  shutdown stops the distro for every program — and announced to
  the program chats before it happens.

## Claims discipline

Space recovered is claimed from the job's own before/after markers
and, for a compact, from the host-side image sizes — never from the
cleanup merely having run. (Precedent on this machine: an owner-run
compact on 2026-10-12 returned ~185 GB across two images, verified
by file sizes.)

## Out of scope

- Docker pruning (its own claimed decision, per FR-003).
- Deleting any project's files (the cleanup gate's claim lists own
  that; this spec never overrides a preserve list).
