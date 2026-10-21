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
- Normal execution-tool approvals and sandbox restrictions remain applicable.
- Do not publish security issues containing real credentials or private logs.

For a proposed report, provide a minimal synthetic reproduction without private
paths or data. A private reporting channel has not been established for this
initial private prototype; do not assume public issues are confidential.
