# Current 0.4.0 acceptance snapshot — 2026-10-22

Classification: **tested local integration prototype** with host-agent-dispatched
release handoffs. Not a background autonomous chat wakeup service.

## Current evidence

- Windows Python 3.13.7: 78 pytest cases passed. The prior queue/dependency,
  real multiprocess, stdio, read-only panel and migration tests still pass.
  New tests cover durable notices on actual release, atomic concurrent claims,
  FIFO/multi-resource eligibility, disabled/cross-project scope, process-release
  refusal, crash recovery, late matching receipts, explicit known-failure retry,
  uncertain-send retry refusal, token redaction and transaction rollback.
- Four Node DOM-level tests passed, including recipient/project filtering,
  uncertainty warnings and accepted-delivery versus verified-reading labels.
  These are behavior tests, not rendered browser/layout acceptance.
- The native CLI installed 0.4.0. Its actual cache passed real MCP stdio smoke:
  21 tools, successful-only prerequisites, release → durable notice → claim →
  simulated host receipt → acknowledgment → recipient reacquisition, with all
  synthetic reservations released. No real chat was messaged by these tests.
- A 0.4.0 wheel was built and installed into a new isolated target. The handoff
  module and all three panel assets are present. UTF-8 skill validation passed.
- No activity was detected in coordinator MCP services immediately before the
  upgrade. Codex and UE were not restarted. The installer pruned old cache
  versions; prepared 0.1/0.2/0.3 installation sources are retained for recovery.
- Notification scope was prepared only for the three already registered project
  participants. No real requests were fabricated, no notifications sent, and
  peer observations were not changed into claims of active adoption.
- The first new failure-injection test used `executescript` inside an explicit
  transaction, which committed the test transaction prematurely. It was fixed
  to use a single `execute`; the rollback safety assertion was preserved and
  passed. This was a test-fixture failure, not a relaxed release condition.

## Still pending / intentionally absent

- Real host-native message delivery and consumption by another chat; mocked
  receipts and CLI installation do not establish this. Existing chats must
  load 0.4 and adopt its workflow at a stable point. This running chat does not
  yet expose the new plugin MCP tools through its host tool list.
- User visual/layout acceptance and actual UE build/editor handoff under dirty
  asset/PIE gates. No combat, editor restart or process takeover was tested.
- No daemon watches release events and independently sends/wakes chats. The
  finishing, authorized host agent must dispatch the outbox; if all agents stop,
  notifications remain pending. Official `codex queue` exists but is not wired
  into this version. Accepted delivery does not mean read/started/acquired.
- Large-queue measurements, power loss/disk-full behavior, Linux/other Python
  versions and this commit's GitHub CI result remain separate validation work.
- OS-enforced locks, multi-user authentication, comprehensive detached-process
  tracking, forced continuation and cross-machine coordination remain out of scope.

The following snapshots are historical, not the current capability list.

# Historical 0.3.0 acceptance snapshot — 2026-10-21

Classification: **tested local integration prototype**. Read-only panel is implemented;
native Codex tool adoption and visual acceptance remain separate checks.

## Current evidence

- Windows Python 3.13.7: 52 pytest cases passed, including the original queue,
  real multiprocess contention and stdio scenarios, v1 database preservation,
  successful-only dependencies, cycle rejection, stale native snapshots,
  self-report revisions, observer cursors and cross-project resource blockers.
- Three Node DOM-level tests passed for peer text/selection/project filters,
  disconnect/reconnect and missing-database/credential states. These are not
  browser screenshot or layout tests.
- Real loopback HTTP tests verified API authentication, Host/Origin rejection,
  no write routes, no arbitrary file serving, fixed assets and restrictive CSP.
  The panel uses a query-only SQLite connection; missing/old databases are not
  created or migrated by the panel. Reading never releases reservations.
- Actual installed 0.3.0 cache passed a separate stdio smoke test: 16 tools,
  dependent request waiting/unblocking, self-report/snapshot import, cursor
  acknowledgment and all synthetic reservations released.
- The native Codex CLI reports 0.3.0 installed. Existing chats have NOT been proven
  reloaded. The CLI removed older version caches during upgrade; original 0.1
  installation source was retained and its 21 non-bytecode files matched the
  pre-upgrade cache SHA-256 values. The 0.2 source copy is retained too.
- Prepared plugin copies include panel assets and exclude packaging metadata.
  A wheel was built and installed into a separate target: all three panel assets
  were present in that independent installation as well.
- UTF-8 skill validation passed. Initial 0.2 frontmatter had an unquoted colon;
  this was corrected before installation. An offline wheel attempt lacked the
  build backend; normal isolation installed the already-declared backend and
  succeeded. Neither failure was hidden by relaxing assertions.
- The live local page and health endpoint returned HTTP 200. An open request for
  the calling chat's browser panel returned `queued`, not a visual inspection.
  Peer native states were imported as observations; no peer feature was marked
  complete and no peer process was adopted or terminated.

## Still pending

- User visual/layout acceptance in a real browser; no screenshot-based acceptance
  is claimed. The local page is not a native Codex plugin-sidebar extension.
- Fresh/resumed chats loading the skill and invoking host-provided MCP tools;
  genuine multi-chat UE build/editor handoff with dirty-asset and PIE gates.
- Background native event subscription, automatic chat messaging and task/team
  creation. Panel polling reads SQLite only, not the live Codex host.
- Large-queue/history load measurements, power loss/disk-full behavior, Linux and
  other Python versions, and GitHub CI results for the current commit.
- OS-enforced locking, comprehensive detached-child tracking, multi-user security
  and cross-machine coordination are intentionally outside this prototype.

The following 0.1 snapshot is historical, not the current capability list.

# Historical 0.1.0 acceptance snapshot — 2026-10-21

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
