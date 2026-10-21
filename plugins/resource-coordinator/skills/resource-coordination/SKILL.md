---
name: resource-coordination
description: Coordinate parallel local coding chats that share build outputs, a running editor, writable assets, or a performance-test machine. Use for reserving these resources, waiting, handoff, and conservative recovery; not for ordinary isolated source edits or NPC/gameplay queues.
---

# Shared operation coordination

This is a cooperative scheduler, not user authorization, an OS lock, or a replacement for Git worktrees.

1. Inspect `queue_status`. Resolve the actual integration/output directory, not just the chat's worktree. All participants must use the same database and matching resource keys. Existing running editors/builds may be unregistered: inspect and explicitly coordinate their owners before claiming a free window. Empty queue does not mean idle machine.
2. Use `plan_ue_resources` for the supported UE profiles, or agree exact `{key, mode}` objects for another workflow. Same writable asset: exclusive key. Normal workloads share `machine:load`; performance capture reserves it exclusively. Ordinary isolated source changes need no reservation, but integration into shared source does.
3. `request_resources` with the stable chat/session ID, a short non-sensitive purpose and optional idempotency key. Earlier conflicting requests have priority. If blocked, report the owner/reason and do independent work; do not busy-poll, repeatedly create tickets, message another chat without user authorization, or close its processes.
4. For a foreground command, leave the ticket waiting and use the packaged `scripts/coordinate.py run --request ID --owner OWNER -- executable args` through the ordinary execution tool with its existing approvals/sandbox. The wrapper acquires and renews the lease, tracks observed process identities, and releases after exit. Exit 3 means queued and command NOT started. For manual asset/editor operations use acquire → begin → renew → complete. Keep the lease token out of persistent logs, repository files and public reports.
5. Reservation does not permit restarting UE, discarding unsaved assets, stopping PIE or killing processes. Recheck these gates immediately before the authorized operation. `compile-only` reserves shared runtime access, but is NOT evidence that an arbitrary build flag avoids DLL changes: verify the real build behavior separately.
6. Complete only after actual work/children end and save evidence identifying commit, extra changes and output. Cancelling a waiting ticket does not stop running work. An expired lease remains blocking. Reconcile only after explicitly confirming work stopped and checking recorded processes; never infer consent from silence or expiry.

The MCP server never executes arbitrary commands. The wrapper supports foreground, non-daemonizing work only and cannot guarantee discovery of every detached child. It does not impose CPU/memory limits: compose with the project's existing resource limiter. Hook is a SessionStart reminder, not a complete blocking policy. Calls outside the wrapper and unregistered applications are not controlled. Installation/reload must not interrupt active chats or editors.
