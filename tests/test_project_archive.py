import tempfile
import unittest
import zipfile
from pathlib import Path

from src.python.worker_client import inspect_project_zip, safe_extract


class ProjectArchiveTests(unittest.TestCase):
    def make_archive(self, path: Path, entries):
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return path

    def test_extracts_valid_project_with_single_blend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_archive(root / "scene.zip", [
                ("project/scene.blend", b"BLENDER-v300scene"),
                ("project/textures/albedo.png", b"texture"),
            ])
            size, scene_name = inspect_project_zip(archive)
            scene = safe_extract(archive, root / "unpacked")
            self.assertEqual(scene_name, "project/scene.blend")
            self.assertEqual(size, len(b"BLENDER-v300scene") + len(b"texture"))
            self.assertEqual(scene.read_bytes(), b"BLENDER-v300scene")

    def test_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_archive(root / "unsafe.zip", [
                ("../escape.txt", b"no"),
                ("scene.blend", b"BLENDER-v300scene"),
            ])
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                inspect_project_zip(archive)

    def test_requires_exactly_one_valid_blend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = self.make_archive(root / "multiple.zip", [
                ("one.blend", b"BLENDER-v300scene"),
                ("two.blend", b"BLENDER-v300scene"),
            ])
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                inspect_project_zip(archive)

    def test_rejects_symlink_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "link.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("scene.blend", b"BLENDER-v300scene")
                link = zipfile.ZipInfo("project-link")
                link.create_system = 3
                link.external_attr = (0o120777 << 16)
                output.writestr(link, "scene.blend")
            with self.assertRaisesRegex(RuntimeError, "Links and special"):
                inspect_project_zip(archive)


if __name__ == "__main__":
    unittest.main()
