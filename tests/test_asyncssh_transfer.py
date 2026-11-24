import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import *  # noqa: F401,F403
from asyncssh_transfer import upload_asyncssh


@unittest.skipUnless(importlib.util.find_spec("asyncssh"), "optional asyncssh dependency")
class AsyncSSHTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_password_upload_and_host_key_rejection(self):
        import asyncssh

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True

            def password_auth_supported(self):
                return True

            def validate_password(self, username, password):
                return username == "test" and password == "test-only-password"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            (home / ".ssh").mkdir(parents=True)
            destination = root / "remote"
            destination.mkdir()
            source = root / "input.bin"
            source.write_bytes(b"payload" * 100000)
            key = asyncssh.generate_private_key("ssh-ed25519")
            server = await asyncssh.create_server(
                Server, "127.0.0.1", 0, server_host_keys=[key],
                sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(destination)),
            )
            try:
                port = server.get_port()
                known_hosts = home / ".ssh" / "known_hosts"
                def write_key(public_key):
                    known_hosts.write_bytes(f"[127.0.0.1]:{port} ".encode() + public_key.export_public_key())
                write_key(key)
                params = {"hostname": "127.0.0.1", "port": port, "user": "test", "password": "test-only-password"}
                events = []
                with patch("asyncssh_transfer.Path.home", return_value=home):
                    result = await upload_asyncssh(params, [], str(source), "/sub dir/output.bin",
                                                   lambda progress: events.append(progress.transferred_bytes))
                    self.assertTrue(result.success)
                    self.assertEqual(source.read_bytes(), (destination / "sub dir" / "output.bin").read_bytes())
                    self.assertEqual(source.stat().st_size, events[-1])
                    write_key(asyncssh.generate_private_key("ssh-ed25519"))
                    with self.assertRaises(asyncssh.HostKeyNotVerifiable):
                        await upload_asyncssh(params, [], str(source), "/other.bin")
                    self.assertFalse((destination / "other.bin").exists())
            finally:
                server.close()
                await server.wait_closed()


if __name__ == "__main__":
    unittest.main()
