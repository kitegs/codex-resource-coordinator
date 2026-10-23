# 0.5.2 public source snapshot

This document retains dated, redacted integration snapshots, including failures
and remaining gates. Past statements about installed versions, absent native
tools or lack of publication describe those dates, not every current client.
For this repository revision's remote checks, inspect the matching commit in
[GitHub Actions](https://github.com/kitegs/codex-resource-coordinator/actions).
Local reports referenced below are deliberately not uploaded. Cross-client
support and remaining adaptation work are listed in [CLIENT_COMPATIBILITY.md](CLIENT_COMPATIBILITY.md).

The initial publication matrix at `b033bb3` exposed a Linux-only test-fixture
omission: a synthetic managed-journal policy test stubbed the Windows scope but
not the new machine fingerprint reader. It failed before reaching the refusal
assertions. Both OS inputs are now explicitly synthetic in that test; the three
manual-completion refusal cases and running-state assertion remain, and the
stored synthetic binding is checked too. Production recovery restrictions were
not weakened and the test was not skipped. CI runs the complete four-cell matrix
without fail-fast cancellation so platform results remain independently visible.

# Historical 0.5.2 verified reboot recovery — 2026-10-23

Classification: **tested local integration prototype**, not an OS lock or automatic reboot monitor.
Only the independent prepared CLI copy was added; installed Codex selection, old
0.5.1 runners, hooks, clients and UE windows were not replaced or restarted.

- 184 pytest cases passed, zero failures/errors/skips, in 57.34 seconds, including
  32 new reboot-policy/CLI/native-probe cases. Evidence:
  `reports/RebootRecovery-0.5.2-20261023/pytest-full.xml`.
- Eight existing Node DOM tests passed; UI was not redesigned. Prepared 0.5.2
  passed real stdio round trips with the unchanged 23 MCP tools and a NEW isolated
  database. Native current-chat MCP adoption is not claimed.
- New `recover-reboot --check-only` checks structured Windows startup events and
  CIM, owner, original timestamps and process identities. Actual recovery needs
  explicit reboot AND same-machine confirmation, plus an audit note. Unknown,
  absent, conflicting, access-denied, same-boot, changed-record and race cases
  keep resources. Transaction rollback preserves both lease and audit integrity.
- Normal new contained jobs bind a hash of Windows MachineGuid. Pre-0.5.2 jobs
  cannot retroactively prove that binding; their recovery additionally relies on
  explicit same-machine attestation plus matching historical OS boot events.
  This is cooperative local recovery, not authentication of a copied database.
- With direct user approval, ONE real pre-existing interrupted flight test ticket
  was verified across the already-occurred Windows reboot and recovered through
  the prepared CLI. A consistent private SQLite backup was made BEFORE migration
  or recovery. The other 113 request rows were unchanged. Result is failed/unknown,
  not test success; no payload restarted or successful dependency unlocked.
- The already-running post-reboot UE demonstration remained untouched. A targeted
  authorized resource-status message was sent to its owner; there was no generated
  pending release notice or broad broadcast. No commit or GitHub publication.

Still pending: deliberate host reboot/power-loss campaigns, missing/rotated event
history recovery (currently refuses), other Windows versions, Linux recovery,
hardware migration and native plugin/MCP reload. Synthetic boot records are not
claimed as real reboot execution. This patch adds a fixed read-only OS probe,
not arbitrary command execution, a force-unlock endpoint or a background service.

The following 0.5.1 snapshot is historical.

# Historical 0.5.1 prepared CLI patch — 2026-10-22

Classification: **tested local integration prototype**. Source and an independent
prepared copy are usable now. The native installed selection remains **0.5.0**;
neither its cache nor the stable marketplace catalog was replaced. The previous
native installer pruned old caches, so this patch deliberately avoids reinstalling
while other chats can still reference them. No Codex/UE restart, MCP disablement,
hook change, real cross-chat message, commit or GitHub push occurred.

## Delivered and verified

- Four CLI commands reuse the existing Store: `acquire` writes a NEW private
  lease receipt, then `begin`, `renew`, and `complete` consume it. Tokens are not
  printed or passed as command arguments. No new queue/schema/dependency exists.
- Final source regression: **152 pytest cases passed**, zero failures, errors
  or skips, in 59.60 seconds, including **29 new manual-CLI cases**.
  Evidence: `reports/ManualCLI-0.5.1-20261022/pytest-full.xml`.
- **50 targeted cases passed** after correcting a test-harness issue:
  `reports/ManualCLI-0.5.1-20261022/targeted-second.xml`. The first run retained
  at `targeted.xml` had 47 passes and setup/teardown errors: pytest put a 65 KiB
  parameter into PYTEST_CURRENT_TEST, exceeding Windows' environment limit.
  Explicit short test IDs fixed the harness; the oversized-input assertion was
  not removed or weakened.
- **8 Node DOM tests passed**: `reports/ManualCLI-0.5.1-20261022/dom.xml`.
- The prepared copy passed actual stdio discovery and round trips for the
  unchanged **23 MCP tools** using a NEW isolated database:
  `reports/ManualCLI-0.5.1-20261022/prepared-protocol.sqlite3`.
  This is protocol regression with synthetic transport, not current-chat MCP
  loading, real message delivery or recipient-consumption proof.
- A real shared-database request passed
  through all four manual actions (private request ID omitted):
  source acquire/begin, then prepared-copy renew/complete. It is completed;
  the old installed 0.5 CLI also sees an empty active queue. Own release outbox
  was checked and empty; no messages were sent. Packaging commands had actually
  ended before manual completion. No real GUI/asset was edited by this test.
- Prepared/source comparison matched all **22 files** excluding the three
  intentionally fixed-interpreter MCP/hook configs. Existing 0.4 and 0.5 caches
  still matched their preserved originals (**21 and 25 files**, respectively).

## Entry point and remaining boundaries

Use the interpreter recorded in your independently prepared copy's `.mcp.json`
with that copy's `scripts/coordinate.py`. Do not copy another user's absolute
installation paths; generate your own copy with `scripts/prepare_install.py`.

The shared database and resource keys stay the same; CLI needs no MCP reload.
See [CLI workflow, section 2a](plugins/resource-coordinator/docs/CLI_FALLBACK.md).
Default manual TTL is 120 seconds, configurable 10..3600; there is no unattended
manual heartbeat. Expiry remains blocking and needs verified reconciliation.
Receipts are not live state; successful completion invalidates their token.
Windows secrecy depends on the chosen parent-directory ACL, not just mode 0600.
The real test receipt used a new directory restricted to user/System/Admins.

Queued/tokenless receipts, wrong database/owner/token, malformed/oversized input,
existing files, missing directories, fsync failure, expired leases, repeated
actions, live/unverifiable recorded processes and competing CLI processes are
covered. Manual `complete` cannot release managed 0.5 jobs even with a valid
token and any of its three outcomes. The command does not save assets, inspect
unregistered GUI work or grant application-control authority. No new force-clear,
background wakeup, platform quota or claim of full GUI integration was added.

---

# Historical 0.5.0 installed integration prototype — 2026-10-22

Classification: **tested local integration prototype**, not a security boundary,
an unattended chat-wakeup daemon or a claim that every existing chat reloaded.
Source remains `b32e902` plus this chat's dirty 0.4.1/0.5 changes; no commit or
GitHub push is claimed. All UE windows and other chats were left running.

## Verified

- Final frozen-source regression: **123 pytest cases passed**, zero failures,
  errors or skips, in 37.34 seconds. Evidence:
  `reports/Supervision-0.5-20261022/pytest-final.xml`.
- **8 Node DOM behavior tests passed**, including the simple current/next/delivery
  overview, dependency blockage, truncated/disconnected data, uncertain sends,
  text-only rendering and the distinction between delivered/read/acquired.
  Evidence: `reports/Supervision-0.5-20261022/dom.xml`.
- Both the immutable prepared copy and the actual installed cache passed real
  stdio discovery of **23 MCP tools**, dependency/status/cursor round trips,
  synthetic handoff transport and cleanup. Isolated evidence databases:
  `reports/Supervision-0.5-20261022/prepared-protocol.sqlite3` and
  `reports/Supervision-0.5-20261022/installed-protocol.sqlite3`.
  Transport was mocked: this does NOT establish real recipient consumption.
- Native `codex plugin add resource-coordinator@resource-coordination-local`
  returned installed version **0.5.0** in the user's plugin-cache directory
  (private absolute installation path omitted).
  The stable local catalog now selects `./versions/0.5.0/plugins/resource-coordinator`.
  No app restart, hook-trust bypass or UE operation occurred. The native installer
  DID automatically remove the old 0.4 cache; post-install checks detected this.
  The full 0.4 cache was restored from its preserved original version directory,
  with the runner matching the recorded pre-install hash. No old/new process was
  stopped, but uninterrupted behavior during the brief missing-cache interval
  is not claimed. Future upgrades must account for installer cache pruning.
- The installed/prepared CLI uses the existing shared database and resource keys.
  Real shared-queue managed checks completed with root exit 0, active group count
  0 and atomic resource release for the panel, prepared protocol, final
  regression and installed protocol checks. Private request IDs are omitted.
  No real cross-chat message was sent.
- Prepared plugin files match source, excluding deliberately fixed-interpreter
  MCP/hook configuration; the installed 0.5 cache matches the accepted prepared
  copy. Before installation and after restoration, the old 0.4 runner matched
  `1B27E957566051CC03E1EB39109363D92BA0DF3D9FAE2E5185561B5AF166CD7C`.

## Behavior delivered

- Chats judge the NEXT operation's actual shared resources themselves. Read-only
  work and isolated worktree edits need no ticket; shared builds/linking, editor
  restart/control, same-asset writes and performance capture do. No entire-chat
  automatic reservation or arbitrary command/chat scanning was added.
- Windows 10+ starts a normal supervisor worker, atomically associates the
  payload using JOB_LIST, retains the enclosing host's controls, and waits for
  the WHOLE contained process group, not only its first parent. No breakaway,
  process termination, detached service, elevation or automatic command retry.
- Journaled operation identity and hashed monitor claims prevent duplicate run
  or takeover of an alive/unverifiable monitor. Recovery only observes existing
  work. Nonzero or unknown results do not unblock success dependencies.
- Release uses the existing durable outbox. The finishing chat checks it and
  an authorized active participant can dispatch once with native host messaging.
  Uncertain sends remain uncertain; no blind retry, reply loop or auto-acquire.
- The normal panel emphasizes who is using resources, the next applicant and
  actual reminder state. Technical details remain expandable. Counts are local
  conflicting-waiter counts, not estimated durations or universal global ranks.

## Failure found and corrected

Initial native fault-injection had 15 passes and 2 failures
(`operations-initial.xml`). It exposed an unsafe assumption: inability to reopen
a Windows Job by name after monitor loss is NOT sufficient process-drain proof.
The false-release path was removed, the client and supervisor lifecycles were
separated, and recovery now requires a still-queryable group or a durable prior
completion transaction. Lost group names/access denial retain the reservation.
The later 40-case targeted suite (`operations-second.xml`) and final full suite
cover these failure cases without weakening the release assertion.

## Explicit remaining gates

- Current-host native coordination MCP tools were still absent after installation;
  the installed CLI is usable now, but fresh/resumed-chat MCP loading and genuine
  inter-chat notice delivery/receiver consumption require separate validation.
- No activity means no independent chat wakeup: pending notices persist until an
  authorized active chat handles them. Actual Codex desktop Stop-button process
  semantics were not claimed from synthetic client/monitor termination tests.
- Lost ALL group handles plus lost completion proof remains manual investigation,
  with no force-clear button. Legacy/manual tickets are not auto-adopted. Old
  clients must not complete/reconcile 0.5 managed requests.
- Real-browser layout acceptance, large-scale queue/performance measurements,
  power loss/disk-full behavior, Linux/Python CI and wheel delivery are not proven.
  Foreground CreateProcess trees only: WMI/services/schedulers/remote brokers are
  not supported external process ownership. This is not an OS-enforced mutex.

Usage and workflow: `plugins/resource-coordinator/docs/SUPERVISION_05.md`.

The following snapshots are historical.

# Historical 0.4.1 CLI fallback acceptance — 2026-10-22

Classification: **tested local integration prototype**, not a background chat
wakeup service or a security boundary. Source base is `b32e902` plus the dirty
0.4.1 CLI/docs/tests changes; no GitHub push is claimed.

## Verified this round

- Windows Python 3.13: all 99 pytest cases passed, zero failed/error/skipped.
  This includes the 21 new CLI cases and the prior queue, migration, real
  multiprocess, runner, panel and real MCP stdio regression suite. The new MCP
  archive endpoint and manifest/package version consistency are exercised too.
- Five Node DOM behavior tests passed. Obsolete notices remain inspectable but
  no longer count as actionable in the NEW panel code. No browser visual
  acceptance or live upgrade of an old panel is claimed.
- A NEW `.local/marketplace-v0.4.1` prepared plugin passed the real stdio protocol
  smoke with 22 tools, dependency/status/cursor handling, mock host transport
  and all synthetic reservations released. Its six critical CLI/core/skill/doc
  files exactly match the tested source. This is NOT current-host tool loading.
- CLI supports chat registration, revision-protected self-reporting (UTF-8 file
  or stdin, including BOM), changes/ack, dependency editing, notification scope,
  listing, private-file claim/ack, definite-failure retry and obsolete archive.
  It calls the same Store/Board/Handoffs as MCP, not a new coordination database.
- The CLI tests cover wrong/stale/peer reports, malformed JSON, UTF-8 pipes,
  real foreground release, competing CLI dispatchers, file overwrite refusal,
  simulated fsync failure, wrong-database/wrong-recipient receipts, stale claims,
  no-longer-waiting deferral, explicit known-failure retry, uncertain-send retry
  refusal and idempotent archive. Token output/argv is avoided via a NEW private
  claim file. Windows ACLs are inherited; a private parent is still required.
- Against the REAL shared database, the source CLI updated only this chat's
  self-report and imported a freshly captured native driver status snapshot.
  The prepared CLI then archived the known never-claimed obsolete notice. That
  archive preserved history, sent no message and did not change the target job.
- Tests used the actual shared load queue. The first attempt waited behind a
  vehicle capture without starting its child. Once released, the 21-case run
  and later complete 99-case/copy-smoke run each exited normally and released
  their own requests. No UE/editor/process was stopped by this task.
- No new dependency, host config edit, Hook trust change, client restart or
  hot overwrite of the installed 0.4.0 cache was performed. New operations can
  select the verified prepared CLI without MCP reloading. Existing wrappers
  and chats may finish on their old paths before a coordinated later upgrade.

Local evidence (ignored, not publication artifacts):
`reports/CLI-Fallback-20261022/pytest.xml`, `dom.xml`, and the isolated
`prepared-protocol.sqlite3`. Usage ships in
`plugins/resource-coordinator/docs/CLI_FALLBACK.md`.

An after-test install-state probe mistakenly passed `codex.exe` to Python and
was rejected before launching Codex; this did not alter plugin state. The probe
was repeated using the real CLI. No assertion was relaxed to obtain test success.

## Still separate acceptance gates

- Current Codex-native MCP tool loading; existing tools are not assumed reloaded.
- Real outbox-driven host message delivery and receiver consumption. Mock
  transport and a separate coordination message do not establish that chain.
- Autonomous wakeup when all chats stop; this version still has no daemon.
- Wheel distribution for 0.4.1, Linux/other Python CI, power-loss/disk-full
  durability beyond the injected failure, large histories and OS-level locking.
- Global adoption by other chats. Only each owner reports its own development
  state. Native snapshots are observations, not feature acceptance or permission.

# Historical 0.4.0 acceptance snapshot — 2026-10-22

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
