# BlendSwarm Worker

Official Python worker client and setup tools for connecting Windows and Linux
machines to the BlendSwarm render network. The worker runs Blender locally;
Blender itself is installed separately and is not bundled in the downloads.

## Requirements

- Windows 10/11 or a supported Linux distribution.
- Python 3.9 or newer.
- Blender 3.6 or newer, available on `PATH` or in its normal installation path.
- An active internet connection to the BlendSwarm server.
- A worker and its private token created at [blendswarm.com/workers](https://blendswarm.com/workers).

Do not post the worker token in an issue, screenshot, URL, or shell command.

For several computers on the same network, use **My Workers > Add Worker >
Auto-Discovery** to create a short-lived enrollment code. Pass it to the worker
installer on each computer with `-DiscoveryCode CODE` (Windows) or
`--discovery-code CODE` (Linux). The code expires after 15 minutes and can
register up to 10 computers. Share it only with machines you control. The
website cannot scan private LAN traffic; each computer must run the installer
to enroll and appear in the dashboard.

## Windows quick start

1. Download and extract the current Windows bundle from the official
   [BlendSwarm worker setup page](https://blendswarm.com/setup).
2. Install Python 3.9+ and Blender 3.6+. Enable Python's **Add Python to PATH**
   option during installation.
3. Double-click `start-worker.cmd`.
4. Enter the server URL (press Enter for `https://blendswarm.com`) and paste
   your worker token at the hidden prompt.
5. Optionally run the Blender benchmark. Keep the PowerShell window open while
   the worker is online; press Ctrl+C to stop it.

The Windows installer stores the token encrypted for the current Windows
account and does not put it in the worker process command line.

## Linux quick start

1. Download and extract the current Linux bundle from the official
   [BlendSwarm worker setup page](https://blendswarm.com/setup).
2. Install Blender 3.6+, Python 3.9+, `python3-venv`, and `curl`.
3. In the extracted directory, run:

   ```bash
   bash install.sh --server https://blendswarm.com
   ```

   The installer prompts for the worker token without echoing it.
4. Test the machine and Blender installation:

   ```bash
   ~/.blendswarm-worker/run.sh --test
   ```

5. Start the worker:

   ```bash
   ~/.blendswarm-worker/run.sh
   ```

To install and start a systemd **user** service instead:

```bash
bash install.sh --server https://blendswarm.com --service
systemctl --user status blendswarm-worker
```

For a headless machine that must start before an interactive login, enable
systemd lingering for that Linux account:

```bash
sudo loginctl enable-linger "$USER"
```

The Linux installer stores the token in a user-only `0600` environment file.
The service runs as the installing user and does not require root.

## Run from source

```bash
python -m venv .venv
# Linux:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python src/python/worker_client.py --server https://blendswarm.com --token YOUR_WORKER_TOKEN
```

Prefer the installers for normal use; they collect the token interactively.
Useful client options include `--test`, `--blender PATH`, `--threads N`, and
`--require-ram`. Run `python src/python/worker_client.py --help` for the full
list. A zero thread limit lets Blender choose its default.

## Docker

Build from a checkout:

```bash
docker build -t blendswarm-worker .
```

Run with a worker token supplied through the environment (avoid putting real
tokens in shell history or shared compose files):

```bash
docker run --rm \
  -e RENDERSWARM_SERVER=https://blendswarm.com \
  -e RENDERSWARM_TOKEN \
  blendswarm-worker
```

The official Dockerfile includes Blender. NVIDIA GPU rendering additionally
requires a compatible host driver, NVIDIA Container Toolkit, and `--gpus all`.
CPU rendering does not require GPU passthrough.

## Releases and verification

Every push and pull request validates the Python worker and installer syntax.
Tagged releases build the Windows ZIP, Linux TAR.GZ, and full source ZIP, each
with a SHA-256 checksum. Release assets are source bundles, not standalone
executables: Python and Blender remain separate prerequisites.

Verify a downloaded archive on Linux:

```bash
sha256sum -c blendswarm-worker-linux.tar.gz.sha256
```

PowerShell:

```powershell
$expected = (Get-Content .\blendswarm-worker-windows.zip.sha256).Split()[0]
$actual = (Get-FileHash .\blendswarm-worker-windows.zip -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { throw "Checksum mismatch" }
```

## Development

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_release.py --output dist
```

The service supports CPU-only and GPU workers. It receives assigned render
chunks, renders them with the locally installed Blender, and uploads results to
the server. ZIP uploads are validated before extraction; archives must contain
one valid `.blend` scene and cannot include unsafe paths, links, encrypted
entries, or unsupported compression. It is not a mobile/Android/iOS worker.

## License

This repository is distributed under GNU GPL v3. See [LICENSE](LICENSE).
