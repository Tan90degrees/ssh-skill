"""Optional AsyncSSH backend for high-throughput, single-file uploads."""
import os
import posixpath
import time
from contextlib import AsyncExitStack
from pathlib import Path

from sftp_transfer import TransferProgress, TransferResult


async def upload_asyncssh(params, jump_hosts, local_path, remote_path, callback=None):
    """Use bounded, server-negotiated SFTP writes and strict known-host checking.

    This backend intentionally never retries via another backend on errors.
    """
    try:
        import asyncssh
    except ImportError as exc:
        raise RuntimeError("AsyncSSH backend requires: python -m pip install asyncssh") from exc

    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if not known_hosts.is_file():
        raise RuntimeError("AsyncSSH requires trusted host keys in ~/.ssh/known_hosts; verify and enroll them first")

    async def connect(stack, host, options, tunnel=None):
        kwargs = {
            "port": options.get("port", 22),
            "known_hosts": str(known_hosts),
            "config": None,
            "connect_timeout": 30,
            "keepalive_interval": 15,
            "keepalive_count_max": 4,
        }
        if options.get("user"):
            kwargs["username"] = options["user"]
        if options.get("password"):
            kwargs.update(password=options["password"], client_keys=None,
                          agent_path=None, preferred_auth=["password", "keyboard-interactive"])
        elif options.get("key_file"):
            kwargs["client_keys"] = [os.path.expanduser(options["key_file"])]
        if tunnel is not None:
            kwargs["tunnel"] = tunnel
        return await stack.enter_async_context(asyncssh.connect(host, **kwargs))

    total = os.path.getsize(local_path)
    progress = TransferProgress(local_path, total, 0, time.time())

    def on_progress(src, dst, copied, size):
        progress.transferred_bytes = copied
        if callback and copied < size:
            callback(progress)

    async with AsyncExitStack() as stack:
        tunnel = None
        for hop in jump_hosts:
            tunnel = await connect(stack, hop["host"], hop, tunnel)
        conn = await connect(stack, params["hostname"], params, tunnel)
        sftp = await stack.enter_async_context(conn.start_sftp_client())
        if await sftp.isdir(remote_path):
            remote_path = posixpath.join(remote_path, os.path.basename(local_path))
        parent = posixpath.dirname(remote_path)
        if parent:
            await sftp.makedirs(parent, exist_ok=True)
        await sftp.put(local_path, remote_path, follow_symlinks=True,
                       block_size=-1, max_requests=64, progress_handler=on_progress)
        attrs = await sftp.stat(remote_path)
        if attrs.size != total:
            raise IOError("Remote size does not match local file size")
        progress.transferred_bytes = total
        if callback:
            callback(progress)
    return TransferResult(success=True, files_transferred=1, bytes_transferred=total,
                          details=[{"file": os.path.basename(local_path), "status": "uploaded",
                                    "size": total, "speed": progress.speed_human}])
