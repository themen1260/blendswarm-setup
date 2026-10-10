import hashlib
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_release import build


class BuildReleaseTests(unittest.TestCase):
    def test_platform_bundles_include_their_installers_and_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            artifacts = build(Path(temp))
            windows, linux, source = artifacts

            with zipfile.ZipFile(windows) as archive:
                windows_files = set(archive.namelist())
            self.assertIn("blendswarm-worker/install.ps1", windows_files)
            self.assertIn("blendswarm-worker/start-worker.cmd", windows_files)
            self.assertIn("blendswarm-worker/worker_client.py", windows_files)
            with zipfile.ZipFile(windows) as archive:
                self.assertIn(
                    b"-DiscoveryCode",
                    archive.read("blendswarm-worker/install.ps1"),
                )
                self.assertIn(
                    b"--enroll-only",
                    archive.read("blendswarm-worker/worker_client.py"),
                )
                self.assertIn(
                    b"New-ScheduledTaskTrigger -AtLogOn",
                    archive.read("blendswarm-worker/install.ps1"),
                )
                self.assertIn(
                    b"Start the worker automatically",
                    archive.read("blendswarm-worker/start-worker.ps1"),
                )

            with tarfile.open(linux, "r:gz") as archive:
                linux_files = set(archive.getnames())
            self.assertIn("blendswarm-worker/install.sh", linux_files)
            self.assertIn("blendswarm-worker/worker_client.py", linux_files)
            with tarfile.open(linux, "r:gz") as archive:
                self.assertIn(b"--discovery-code", archive.extractfile("blendswarm-worker/install.sh").read())

            with zipfile.ZipFile(source) as archive:
                source_files = set(archive.namelist())
            self.assertIn("blendswarm-setup/src/python/worker_client.py", source_files)
            self.assertIn("blendswarm-setup/tests/test_project_archive.py", source_files)
            self.assertIn("blendswarm-setup/tests/test_idle_gate.py", source_files)
            for artifact in artifacts:
                checksum_file = artifact.with_suffix(artifact.suffix + ".sha256")
                expected, filename = checksum_file.read_text(encoding="ascii").split()
                self.assertEqual(filename, artifact.name)
                self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
