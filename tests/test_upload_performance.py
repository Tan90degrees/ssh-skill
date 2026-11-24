import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.support import *  # noqa: F401,F403
from ssh_upload import use_native_upload
from native_ssh_client import NativeSSHClient, _scp_tuning_args
from sftp_transfer import SFTPTransfer
from config_v3 import SSHConfigLoaderV3


class UploadPerformanceTests(unittest.TestCase):
    def test_backend_selection_ignores_size(self):
        params = {"key_file": "key", "password": None}
        self.assertTrue(use_native_upload(params))
        self.assertTrue(use_native_upload(params, progress=False))
        for options in ({"resume": True}, {"recursive": True}, {"progress": True}):
            self.assertFalse(use_native_upload(params, **options))
        self.assertFalse(use_native_upload({"key_file": "key", "password": "test"}))

    def test_scp_tuning_is_capability_gated(self):
        for usage, expected in (
            ("usage: scp [-X sftp_option] source target", ["-X", "nrequests=128", "-X", "buffer=65536"]),
            ("usage: scp [-P port] source target", []),
        ):
            with patch("native_ssh_client.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", usage)):
                self.assertEqual(expected, _scp_tuning_args())

    def test_large_native_upload_no_size_based_deadline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "large.bin"
            with local.open("wb") as stream:
                stream.truncate(81 * 1024 * 1024)
            client = NativeSSHClient("example.invalid", "test", key_file="key")
            with patch("native_ssh_client._scp_tuning_args", return_value=["-X", "nrequests=128"]), patch(
                "native_ssh_client.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run:
                result = client.upload(str(local), "/tmp/large.bin")
            self.assertTrue(result.success)
            self.assertIn("nrequests=128", run.call_args.args[0])
            self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_resume_enables_pipeline_and_checks_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir) / "file.bin"
            local.write_bytes(b"abcdefgh")
            sftp = MagicMock()
            remote = sftp.open.return_value.__enter__.return_value
            attrs = MagicMock()
            attrs.st_mode = 0o100644
            attrs.st_size = 4
            final = MagicMock()
            final.st_size = 8
            sftp.stat.side_effect = [attrs, attrs, attrs, final]
            result = SFTPTransfer(sftp).upload_file(str(local), "/tmp/file.bin", resume=True)
            self.assertTrue(result.success, result.errors)
            remote.set_pipelined.assert_called_once_with(True)
            remote.write.assert_called_once_with(b"efgh")

    def test_jump_resolves_per_hop_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = Path(temp_dir) / "config"
            config.write_text("Host jump\n  HostName bastion.example.invalid\n  User jumpuser\n  Port 2222\n  IdentityFile ~/.ssh/test-key\n", encoding="utf-8")
            loader = SSHConfigLoaderV3(str(config))
            hops = loader.resolve_jump_hosts("jump,other@second.example.invalid:2200")
            self.assertEqual("bastion.example.invalid", hops[0]["host"])
            self.assertEqual("jumpuser", hops[0]["user"])
            self.assertEqual(2222, hops[0]["port"])
            self.assertIsNone(hops[0]["password"])
            self.assertEqual("other", hops[1]["user"])
            self.assertEqual(2200, hops[1]["port"])


if __name__ == "__main__":
    unittest.main()
