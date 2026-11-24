# Unified CLI Commands

Use `<PYTHON>` and path syntax from the relevant platform guide. All examples
use fictional aliases and the unified v4 entrypoint.

## Diagnostics And Alias Discovery

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" doctor --json
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config list-servers
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config find example
```

`doctor` is local-only. Use `--project-root <path>` when project-local Codex,
Claude Code, or shared agent skill copies must be included in discovery.

## Execute

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" exec example-host "uname -a"
```

Options: `--timeout <seconds>`, `--no-daemon`.

Keep the remote command as one argument. The CLI passes it to SSH without a
local shell wrapper. A failed response with `error.code=outcome_unknown` must
not be replayed automatically. OpenSSH or Paramiko timeouts after dispatch use
this code with `retryable=false`.

## Upload And Download

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" upload example-host <local-path> /tmp/file
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" download example-host /var/log/app.log <local-path>
```

Options: `--resume`, `--recursive`, `--progress`, `--no-progress`.

Local paths follow the local OS. Remote paths remain POSIX paths on every OS.
With `--recursive`, result details retain at most 100 head/tail file samples;
the aggregate count still reports every processed file.

## Server-To-Server Transfer

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" transfer source-host /data/file destination-host /backup/file
```

Options: `--mode auto|direct|stream|hybrid`, `--use-rsync`,
`--allow-agent-forwarding`, `--size-threshold <MB>`, `--timeout <seconds>`,
`--progress`, `--no-progress`.

Agent forwarding is off by default. Direct transfer can instead use credentials
already configured on the source server.

## Cluster

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" cluster "uptime" --environment staging
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" cluster "uptime" --hosts example-host,example-worker --apply
```

Filters: `--hosts`, `--environment`, `--tags`. Execution options:
`--parallel`, `--timeout`, `--health-check`, `--max-workers`, `--apply`, and
`--confirm-production`.

The first call previews targets. Production targets require both `--apply` and
`--confirm-production`. A per-host timeout after dispatch is `outcome_unknown`
and non-retryable; report completed hosts separately and do not replay them.

## Result And Progress Streams

- stdout contains one JSON result capped at 256 KiB.
- `--progress` emits bounded, real-time, ASCII-safe JSONL events on stderr.
- Consume stdout and stderr separately. A closed progress consumer does not
  change the operation result.

## Configuration

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config list-servers
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config find example
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config create --alias example-host --host 192.0.2.10 --user deploy --key <key-path>
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config update example-host --description "Example host"
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config delete example-host
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config delete example-host --apply
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" config export --output <local-path>
```

Creation and update reject new plaintext password fields. Delete previews by
default and creates a backup when applied.

## Tunnel

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" tunnel start example-host --remote-port 5432
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" tunnel list
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" tunnel status <tunnel-id>
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" tunnel stop <tunnel-id>
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" tunnel stop-all example-host
```

`start` also accepts `--local-port` and `--remote-host`.

## Daemon

```text
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" daemon status example-host
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" daemon start example-host
<PYTHON> "<SSH_SKILL_ROOT>/scripts/ssh_skill.py" daemon stop example-host
```

Normal command execution manages daemon reuse automatically. Manual daemon
commands are diagnostic and lifecycle controls, not required before each exec.

## Compatibility Entrypoints

Published legacy filenames remain available. Their default path delegates to
the v4 result contract. Use `--legacy-json` only for a known v3 consumer; it
does not restore unsafe host-key, retry, output, or cluster behavior.

### Upload throughput

For ordinary key-authenticated files, use the default upload command (or
`--no-progress`). Native OpenSSH is used regardless of file size. For files
at least 8 MiB, supported SCP clients use 128 in-flight SFTP requests and a
64 KiB requested buffer; older clients retain their defaults. The remote
parent directory must already exist for native SCP. Use the SFTP path
(`--progress`, `--resume`, or `--recursive` as appropriate) when parent
creation or detailed transfer progress is needed. Password authentication
and paths with shell-sensitive characters use SFTP as well.

For an apples-to-apples benchmark, compare the same large file on the same
host and destination filesystem using default upload, `--progress` (SFTP),
and WinSCP in SFTP mode. Record elapsed time and verify the remote checksum.
Use distinct destination filenames and avoid concurrent transfers. A resumed
file must have a matching prefix; matching sizes alone do not prove content
identity. Do not resume unrelated files.

Directory uploads use four reusable SFTP channels on one SSH connection by
default. Set `--parallel 1` for servers with strict session limits, or choose
up to 8. The parallel directory progress stream reports aggregate bytes.

Use `--backend paramiko` to force the compatible Python SFTP path. An optional
single-file high-throughput backend is available with `--backend asyncssh`;
install it with `python -m pip install asyncssh`. It uses the server-negotiated
block size, at most 64 outstanding requests, and structured progress. Verify
and enroll the target and jump host keys in the standard known_hosts file
before use. The backend rejects unknown or changed keys and never falls back
automatically after a connection or transfer error. Resume and recursive
uploads still use Paramiko. Default auto selection remains unchanged pending
performance and integration validation.
