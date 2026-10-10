#!/usr/bin/env bash
# BlendSwarm worker installer for Linux (Ubuntu/Debian/Fedora).
# Use from a downloaded bundle or online:
#   bash install.sh --server https://blendswarm.com [--service]
set -euo pipefail
umask 077

SERVER=""
TOKEN=""
DISCOVERY_CODE=""
SERVICE=0
DIR="$HOME/.blendswarm-worker"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --server) [ "$#" -ge 2 ] || { echo "Missing value for --server" >&2; exit 2; }; SERVER="${2%/}"; shift 2 ;;
    --token) [ "$#" -ge 2 ] || { echo "Missing value for --token" >&2; exit 2; }; TOKEN="$2"; shift 2 ;;
    --discovery-code) [ "$#" -ge 2 ] || { echo "Missing value for --discovery-code" >&2; exit 2; }; DISCOVERY_CODE="$2"; shift 2 ;;
    --service) SERVICE=1; shift ;;
    --dir) [ "$#" -ge 2 ] || { echo "Missing value for --dir" >&2; exit 2; }; DIR="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: bash install.sh --server URL [--token TOKEN | --discovery-code CODE] [--service] [--dir PATH]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$SERVER" ] || { echo "--server is required." >&2; exit 2; }
if [ -n "$TOKEN" ] && [ -n "$DISCOVERY_CODE" ]; then
  echo "Use either --token or --discovery-code, not both." >&2
  exit 2
fi
if [ -z "$TOKEN" ] && [ -z "$DISCOVERY_CODE" ]; then
  [ -t 0 ] || { echo "A worker token is required; rerun interactively or pass --token." >&2; exit 2; }
  read -r -s -p "Worker token (input hidden): " TOKEN
  printf '\n'
fi
[ -n "$TOKEN" ] || { echo "Worker token cannot be empty." >&2; exit 2; }

command -v curl >/dev/null || { echo "curl is required. Install curl and run this installer again." >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3.9+ is required. Install Python 3 and run this installer again." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Python 3.9 or newer is required." >&2
  exit 1
}
BLENDER="$(command -v blender || true)"
[ -n "$BLENDER" ] || {
  echo "Blender was not found in PATH. Install Blender 3.6+ from https://www.blender.org/download/"
  echo "Then reopen the terminal and run this installer again."
  exit 1
}

mkdir -p "$DIR"
chmod 700 "$DIR"
if [ -f "$SCRIPT_DIR/worker_client.py" ] && [ -f "$SCRIPT_DIR/requirements.txt" ]; then
  cp "$SCRIPT_DIR/worker_client.py" "$DIR/worker_client.py"
  cp "$SCRIPT_DIR/requirements.txt" "$DIR/requirements.txt"
else
  curl -fsSL "$SERVER/downloads/worker_client.py" -o "$DIR/worker_client.py"
  curl -fsSL "$SERVER/downloads/requirements.txt" -o "$DIR/requirements.txt"
fi

python3 -m venv "$DIR/venv" || {
  echo "Could not create a Python virtual environment. On Ubuntu/Debian run: sudo apt install python3-venv"
  exit 1
}
"$DIR/venv/bin/python" -m pip install --disable-pip-version-check -q --upgrade pip
"$DIR/venv/bin/python" -m pip install --disable-pip-version-check -q -r "$DIR/requirements.txt"

if [ -n "$DISCOVERY_CODE" ]; then
  "$DIR/venv/bin/python" "$DIR/worker_client.py" --server "$SERVER" --discovery-code "$DISCOVERY_CODE" --enroll-only
  TOKEN=""
fi
printf 'export RENDERSWARM_SERVER=%q\nexport RENDERSWARM_TOKEN=%q\nexport BLENDER_PATH=%q\n' \
  "$SERVER" "$TOKEN" "$BLENDER" > "$DIR/worker.env"
chmod 600 "$DIR/worker.env"
cat > "$DIR/run.sh" <<EOS
#!/usr/bin/env bash
set -euo pipefail
source "$DIR/worker.env"
exec "$DIR/venv/bin/python" "$DIR/worker_client.py" --blender "$BLENDER" "\$@"
EOS
chmod 700 "$DIR/run.sh"

if [ "$SERVICE" -eq 1 ]; then
  command -v systemctl >/dev/null && systemctl --user --version >/dev/null 2>&1 || {
    echo "The --service option requires systemd with a user service manager. Run '$DIR/run.sh' manually instead." >&2
    exit 1
  }
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/blendswarm-worker.service" <<EOS
[Unit]
Description=BlendSwarm worker
After=network-online.target

[Service]
ExecStart=$DIR/run.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOS
  systemctl --user daemon-reload
  systemctl --user enable --now blendswarm-worker.service
  echo "Service started. Check with: systemctl --user status blendswarm-worker"
fi

echo
echo "BlendSwarm worker installed to $DIR"
echo "Benchmark: $DIR/run.sh --test"
echo "Start:     $DIR/run.sh"
