#!/usr/bin/env python3
"""Build platform-specific source bundles and SHA-256 sidecar files."""

import argparse
import hashlib
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = {
    "worker_client.py": ROOT / "src/python/worker_client.py",
    "requirements.txt": ROOT / "requirements.txt",
    "install.sh": ROOT / "install.sh",
    "install.ps1": ROOT / "install.ps1",
    "start-worker.cmd": ROOT / "start-worker.cmd",
    "start-worker.ps1": ROOT / "start-worker.ps1",
    "Dockerfile": ROOT / "Dockerfile",
    "README.txt": ROOT / "README-worker.txt",
}


def _write_zip(destination: Path, names: tuple[str, ...]) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in names:
            archive.write(SOURCE_FILES[name], arcname=f"blendswarm-worker/{name}")


def build(output_dir: Path) -> list[Path]:
    missing = [str(path) for path in SOURCE_FILES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing worker release files: " + ", ".join(missing))
    output_dir.mkdir(parents=True, exist_ok=True)

    windows_name = (
        "worker_client.py", "requirements.txt", "install.ps1",
        "start-worker.cmd", "start-worker.ps1", "README.txt",
    )
    linux_name = ("worker_client.py", "requirements.txt", "install.sh", "README.txt")
    all_names = tuple(SOURCE_FILES)
    artifacts = [
        output_dir / "blendswarm-worker-windows.zip",
        output_dir / "blendswarm-worker-linux.tar.gz",
        output_dir / "blendswarm-worker-source.zip",
    ]
    _write_zip(artifacts[0], windows_name)

    with tarfile.open(artifacts[1], "w:gz", compresslevel=9) as archive:
        for name in linux_name:
            archive.add(SOURCE_FILES[name], arcname=f"blendswarm-worker/{name}")

    with zipfile.ZipFile(artifacts[2], "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in SOURCE_FILES.items():
            archive.write(path, arcname=f"blendswarm-setup/{name}")
        for path in (
            ROOT / "README.md",
            ROOT / "LICENSE",
            ROOT / "scripts/build_release.py",
            ROOT / ".github/workflows/worker.yml",
        ):
            archive.write(path, arcname=f"blendswarm-setup/{path.relative_to(ROOT)}")
        for path in sorted((ROOT / "tests").rglob("*.py")):
            archive.write(path, arcname=f"blendswarm-setup/{path.relative_to(ROOT)}")
        for path in sorted((ROOT / "src").rglob("*.py")):
            archive.write(path, arcname=f"blendswarm-setup/{path.relative_to(ROOT)}")

    for artifact in artifacts:
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        checksum = artifact.with_suffix(artifact.suffix + ".sha256")
        checksum.write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for artifact in build(args.output.resolve()):
        print(f"{artifact.name}: {artifact.stat().st_size} bytes")


if __name__ == "__main__":
    main()
