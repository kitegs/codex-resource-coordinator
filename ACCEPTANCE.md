# 0.1.0 acceptance snapshot — 2026-10-21

Classification: **tested integration prototype**, not an OS-enforced lock or a production-ready multi-agent orchestration platform.

## Evidence executed

- Windows native Python 3.13.7, MCP SDK 1.30.0 and psutil 7.2.2 in an isolated virtual environment.
- 26 automated tests passed: four real competing processes, shared/exclusive fairness, atomic multi-resource claims, independent resources, cancellation/owner/idempotency checks, expiry that keeps blocking, invalid/stale tokens, alive/unknown process refusal, foreground launcher success/failure and proof a queued/broken-database command never starts.
- A synthetic client records its identity then exits without releasing. A subsequent client remains blocked until explicit recovery verifies the recorded process has gone.
- Long-build fixture retires only confirmed-gone compiler identities rather than exhausting a cumulative history budget.
- Real MCP stdio handshake, discovery of 9 tools, request/acquire/wait/begin/renew/complete and invalid-token handling. Public status does not expose raw tokens.
- A second, non-UE database-migration reservation scenario passed.
- Prepared installation copy uses the explicitly chosen interpreter. Manifest paths resolve inside the plugin. SessionStart hook only returns a reminder and writes no files.
- Skill frontmatter validation passed in UTF-8 mode. The validator's first attempt failed under the host's GBK default; UTF-8 retry fixed the validation environment, not test assertions or plugin behavior.
- Native Codex CLI accepted the prepared local marketplace and installed `resource-coordinator@resource-coordination-local` version 0.1.0. No client restart, hook-trust bypass, or process interruption was performed.
- Only this independent plugin repository is eligible for upload; virtual environments, runtime databases, local installation copies and reports are ignored. Heuristic secret/private-project scans are a guardrail, not proof against every possible secret.

## Explicitly pending

- A fresh/resumed Codex chat loading the installed skill and invoking its host-provided MCP tools. CLI installation and standalone protocol tests do not prove current chats have reloaded.
- Real two-chat handoff around an actual UE build/editor and explicit dirty-asset/PIE gates. Existing tasks remain unmanaged until their owners adopt the queue.
- Linux, Python 3.11, and GitHub CI matrix results. Workflow presence is not test execution.
- Performance at large queue/history sizes, power loss/disk-full recovery, cross-machine operation, comprehensive detached-child tracking, and OS-level enforcement.
- UI dashboard, automatic team creation/task decomposition/dependency graph, and automatic cross-chat messaging are not implemented.

Hook reminder is not a global blocking policy. A queue reservation never supplies user permission. Do not advertise this version as a full Claude Code Agent Teams replacement or an automatic cure for all parallel-development conflicts.
