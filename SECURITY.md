# Security and privacy boundaries

This is cooperative scheduling for trusted local participants, not authentication,
an OS sandbox, or a guarantee that all commands and applications are intercepted.
The database belongs to the local OS user. Owner strings and lease tokens do not
isolate mutually untrusted users with access to its files.

- Use only a local disk for SQLite. All participants must share one database.
- Do not grant the MCP server arbitrary command execution or broad tool approval.
- Do not infer user authorization from a queue grant, expiry, or another chat.
- Never upload runtime databases, process metadata, private prompts, tokens, or
  generated local installation files. This repository ignores these outputs.
- The foreground wrapper never kills work on timeout. Suspect reservations need
  explicit review; failing closed can require manual recovery.
- Foreground children are observed, not comprehensively sandboxed. Detached or
  very short-lived children can escape observation. Do not use daemonizing commands.
- The SessionStart hook is a reminder only. No global blocking hook is installed.
- Release notices are an outbox, not a background messaging service. Only an
  enabled, human-authorized participating host agent sends using its native tool.
  Local opt-in/reference strings are not authentication or independent consent.
- Atomic claims reduce duplicate concurrent sends, not exactly-once delivery.
  Timeout/crash after claim is uncertain and must not trigger automatic resend,
  cross-channel fallback, or forced continuation. Definitive non-delivery can be
  explicitly requeued after verification; unknown sends cannot. A matching host
  receipt means accepted delivery, never proof of reading or resource ownership.
- Notice claim tokens are stored only as hashes and redacted from board/panel
  output. Message templates use generated request/notice identifiers, not peer
  prompts, purposes, source code or executable instructions from shared reports.
- Normal execution-tool approvals and sandbox restrictions remain applicable.
- The optional read-only panel binds only to IPv4 loopback. Its state API requires
  an ephemeral token supplied in a request header, validates Host/Origin, disables
  caching, and serves only three fixed assets. There are no state mutation routes.
  Do not publish its full URL or proxy it to the Internet. It is not multi-user auth.
- Panel refresh reads the coordination database, not Codex transcripts. It does not
  create/migrate databases or assume that imported peer status is fresh or accepted.
- Do not publish security issues containing real credentials or private logs.

For a proposed report, provide a minimal synthetic reproduction without private
paths or data. A private reporting channel has not been established for this
initial private prototype; do not assume public issues are confidential.
