#!/usr/bin/env python3
"""BlendSwarm worker client.

Connects to the BlendSwarm server, receives Blender render jobs, renders them locally,
uploads the result and reports progress. Usage:

    python worker_client.py --server https://your-domain.com --token <WORKER_TOKEN>
"""
import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import psutil
import requests
import websockets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import GPUtil
except Exception:  # GPU monitoring is optional
    GPUtil = None

VERSION = "2.3.0"
ALLOWED_ENGINES = {"CYCLES", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH"}
FRAME_RE = re.compile(r"Fra:(\d+)")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("worker")

MAGIC = b"RSE1"
MIN_RAM_FREE = 512 * 1024 * 1024
IDLE_CPU_LIMIT_PERCENT = 30.0
IDLE_GPU_LIMIT_PERCENT = 20.0
IDLE_CONFIRMATION_SECONDS = 300


class IdleGate:
    def __init__(self, confirmation_seconds: int = IDLE_CONFIRMATION_SECONDS):
        self.confirmation_seconds = confirmation_seconds
        self.idle_since: Optional[float] = None

    def update(self, cpu_percent: float, gpu_loads: Optional[list], now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        gpu_idle = gpu_loads is None or not gpu_loads or all(load < IDLE_GPU_LIMIT_PERCENT for load in gpu_loads)
        if cpu_percent >= IDLE_CPU_LIMIT_PERCENT or not gpu_idle:
            self.idle_since = None
            return False
        if self.idle_since is None:
            self.idle_since = now
        return now - self.idle_since >= self.confirmation_seconds


def _read_exact(read, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        part = read(n - len(buf))
        if not part:
            break
        buf += part
    return buf


def iter_decrypt(read, key: bytes):
    """Streaming AES-256-GCM decrypt of the server's chunked format (constant memory, detects tampering)."""
    head = _read_exact(read, 8)
    if len(head) != 8 or head[:4] != MAGIC:
        raise RuntimeError("Input is not a valid encrypted BlendSwarm file")
    aes, prefix, counter = AESGCM(key), head[4:], 0
    length = _read_exact(read, 4)
    while length:
        if len(length) != 4:
            raise RuntimeError("Encrypted input is truncated")
        ct = _read_exact(read, int.from_bytes(length, "big"))
        nxt = _read_exact(read, 4)
        yield aes.decrypt(prefix + counter.to_bytes(8, "big"), ct, b"\x00" if nxt else b"\x01")
        counter += 1
        length = nxt


def ram_root() -> Optional[Path]:
    """A RAM-backed directory (tmpfs) so decrypted scene files never touch the disk."""
    if sys.platform.startswith("linux"):
        for cand in ("/dev/shm", "/run/shm"):
            if os.path.isdir(cand) and os.access(cand, os.W_OK):
                return Path(cand)
    return None


def normalize_server(url: str) -> str:
    url = url.strip().rstrip("/")
    for suffix in ("/api/workers", "/api", "/ws"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def _worker_token_path(server: str) -> Path:
    if os.name == "nt":
        root = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "BlendSwarm"
    else:
        root = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config") / "blendswarm"
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(normalize_server(server).encode("utf-8")).hexdigest()[:16]
    return root / f"worker-{digest}.json"


def _load_worker_token(server: str) -> Optional[str]:
    path = _worker_token_path(server)
    if not path.exists():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read saved worker credentials at {path}: {exc}") from exc
    if config.get("server") != normalize_server(server) or not config.get("token"):
        raise RuntimeError(f"Saved worker credentials at {path} are invalid; remove that file and pair again.")
    return config["token"]


def _save_worker_token(server: str, token: str) -> None:
    path = _worker_token_path(server)
    path.write_text(json.dumps({"server": normalize_server(server), "token": token}), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def enroll_worker(server: str, code: str) -> str:
    hardware = {
        "code": code,
        "name": socket.gethostname() or "Discovered worker",
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "memory_gb": max(1, round(psutil.virtual_memory().total / 2**30)),
        "storage_gb": max(1, round(psutil.disk_usage(tempfile.gettempdir()).free / 2**30)),
        "gpu_names": [],
        "os": f"{platform.system()} {platform.release()}",
    }
    if GPUtil:
        try:
            hardware["gpu_names"] = [gpu.name for gpu in GPUtil.getGPUs()]
        except Exception as exc:
            logger.warning("Could not detect GPUs during auto-enrollment: %s", exc)
    try:
        response = requests.post(
            f"{normalize_server(server)}/api/workers/discovery/enroll",
            json=hardware,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach the BlendSwarm server to enroll this worker: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Worker enrollment failed: {detail}")
    result = response.json()
    token = result.get("worker_token")
    if not token:
        raise RuntimeError("Worker enrollment response did not include a worker token.")
    _save_worker_token(server, token)
    print(f"Registered worker '{result.get('name', hardware['name'])}' (ID {result.get('worker_id')}).")
    print(f"Saved its credential securely for future starts: {_worker_token_path(server)}")
    return token


def safe_extract(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if dest != target and dest not in target.parents:
                raise RuntimeError(f"Unsafe path in archive: {member.filename}")
        zf.extractall(dest)


class Worker:
    def __init__(
        self, server: str, token: str, blender: str, workdir: Path,
        max_job_seconds: int, threads: int = 0, idle_only: bool = True,
    ):
        self.http_base = normalize_server(server)
        self.ws_url = self.http_base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"
        self.token = token
        self.blender = blender
        self.workdir = workdir
        self.threads = threads
        self.require_ram = False
        self.current_chunk: Optional[int] = None
        self.max_job_seconds = max_job_seconds
        self.ws = None
        self.current_job: Optional[int] = None
        self.proc: Optional[subprocess.Popen] = None
        self.cancelled = False
        self.heartbeat_interval = 30
        self.idle_only = idle_only
        self.idle_gate = IdleGate()
        self.available_for_jobs = not idle_only

    def gpu_loads(self) -> Optional[list]:
        if not GPUtil:
            return None
        try:
            devices = GPUtil.getGPUs()
            return [float(gpu.load) * 100 for gpu in devices]
        except Exception:
            return None

    # ---------- helpers ----------
    def headers(self) -> Dict[str, str]:
        return {"X-Worker-Token": self.token}

    async def send(self, payload: Dict[str, Any]) -> None:
        if self.ws is not None:
            await self.ws.send(json.dumps(payload))

    def metrics(self) -> Dict[str, Any]:
        m: Dict[str, Any] = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "active_jobs": 1 if self.current_job else 0,
        }
        if GPUtil:
            try:
                m["gpus"] = [{"id": g.id, "load": g.load, "memory_used": g.memoryUsed, "temperature": g.temperature}
                             for g in GPUtil.getGPUs()]
            except Exception:
                pass
        return m

    # ---------- connection ----------
    async def run(self) -> None:
        delay = 5
        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20, max_size=None) as ws:
                    self.ws = ws
                    metrics = await asyncio.to_thread(self.metrics)
                    if self.idle_only:
                        self.available_for_jobs = self.idle_gate.update(
                            metrics["cpu_percent"], self.gpu_loads()
                        )
                    await ws.send(json.dumps({
                        "type": "register", "client_type": "worker", "worker_token": self.token,
                        "version": VERSION, "host": socket.gethostname(),
                        "available": self.available_for_jobs,
                    }))
                    first = json.loads(await ws.recv())
                    if first.get("type") != "connection_established":
                        raise RuntimeError(f"registration rejected: {first}")
                    logger.info("Connected to %s", self.ws_url)
                    delay = 5
                    hb = asyncio.create_task(self.heartbeat_loop())
                    try:
                        await self.listen()
                    finally:
                        hb.cancel()
            except websockets.exceptions.InvalidStatus as e:
                logger.error("Server refused connection: %s", e)
            except Exception as e:
                logger.warning("Connection lost: %s", e)
            finally:
                self.ws = None
            logger.info("Reconnecting in %ss...", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def heartbeat_loop(self) -> None:
        while True:
            metrics = await asyncio.to_thread(self.metrics)
            if self.idle_only:
                was_available = self.available_for_jobs
                self.available_for_jobs = self.idle_gate.update(metrics["cpu_percent"], self.gpu_loads())
                if was_available != self.available_for_jobs:
                    state = "available for jobs" if self.available_for_jobs else "paused while the computer is in use"
                    logger.info("Worker scheduling state changed: %s", state)
            await self.send({
                "type": "heartbeat",
                "metrics": metrics,
                "available": self.available_for_jobs,
            })
            await asyncio.sleep(10 if self.idle_only else self.heartbeat_interval)

    async def listen(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            kind = msg.get("type")
            if kind == "new_job":
                if self.current_job is not None:
                    logger.warning("Ignoring job while busy")
                    continue
                self.current_job = int(msg["job_data"]["job_id"])
                self.current_chunk = msg["job_data"].get("chunk_id")
                asyncio.create_task(self.process_job(msg["job_data"]))
            elif kind == "cancel_job" and self.current_job == msg.get("job_id") and \
                    msg.get("chunk_id") in (None, self.current_chunk):
                logger.info("Cancelling job %s", self.current_job)
                self.cancelled = True
                if self.proc and self.proc.poll() is None:
                    self.proc.terminate()

    # ---------- job processing ----------
    async def process_job(self, job: Dict[str, Any]) -> None:
        job_id = int(job["job_id"])
        job_dir: Optional[Path] = None
        self.cancelled = False
        started = time.time()
        try:
            await self.send({"type": "job_started", "job_id": job_id, "chunk_id": self.current_chunk})
            job_dir, blend = await asyncio.to_thread(self.download_input, job)
            out_dir = job_dir / "out"
            out_dir.mkdir()
            await self.render(job, blend, out_dir)
            if self.cancelled:
                return
            archive = await asyncio.to_thread(self.pack_output, job_dir, out_dir)
            await asyncio.to_thread(self.upload_output, job, archive)
            await self.send({"type": "job_completed", "job_id": job_id, "chunk_id": self.current_chunk,
                             "result": {"render_time": time.time() - started}})
            logger.info("Job %s frames %s-%s completed in %.0fs", job_id, job["frame_start"], job["frame_end"],
                        time.time() - started)
        except Exception as e:
            logger.exception("Job %s failed", job_id)
            if not self.cancelled:
                try:
                    await self.send({"type": "job_failed", "job_id": job_id, "chunk_id": self.current_chunk,
                                     "error": str(e)[:500]})
                except Exception:
                    pass
        finally:
            self.current_job = None
            self.current_chunk = None
            self.proc = None
            # scene, textures and rendered frames all lived in this directory; remove it in every outcome
            if job_dir is not None:
                shutil.rmtree(job_dir, ignore_errors=True)

    def make_job_dir(self, job_id: int, need_bytes: int) -> Path:
        ram = ram_root()
        if ram is not None:
            try:
                free = shutil.disk_usage(ram).free
            except OSError:
                free = 0
            if free >= max(need_bytes * 3, MIN_RAM_FREE):
                return Path(tempfile.mkdtemp(prefix=f"rs_job_{job_id}_", dir=ram))
            reason = f"RAM disk too small ({free // 2**20} MB free, need ~{need_bytes * 3 // 2**20} MB)"
        else:
            reason = "no RAM disk available on this OS"
        if self.require_ram:
            raise RuntimeError(f"--require-ram set but {reason}")
        logger.warning("Decrypting on disk instead of RAM: %s", reason)
        return Path(tempfile.mkdtemp(prefix=f"rs_job_{job_id}_", dir=self.workdir))

    def download_input(self, job: Dict[str, Any]):
        encrypted = bool(job.get("encrypted") and job.get("job_key"))
        params = {"chunk_id": job.get("chunk_id")}
        if encrypted:
            params["enc"] = 1
        url = self.http_base + job["download_url"]
        job_dir: Optional[Path] = None
        try:
            with requests.get(url, headers=self.headers(), params=params, stream=True, timeout=(10, 120)) as r:
                r.raise_for_status()
                size = int(r.headers.get("Content-Length") or 0)
                job_dir = self.make_job_dir(int(job["job_id"]), size)
                name = Path(job.get("file_path") or "input.blend").suffix.lower()
                if name == ".enc":
                    name = Path(Path(job["file_path"]).stem).suffix.lower()
                src = job_dir / f"input{name or '.blend'}"
                with open(src, "wb") as f:
                    if encrypted:
                        key = base64.b64decode(job["job_key"])
                        for plain in iter_decrypt(lambda n: r.raw.read(n, decode_content=True), key):
                            f.write(plain)
                    else:
                        for chunk in r.iter_content(1024 * 1024):
                            f.write(chunk)
            if src.suffix == ".zip":
                scene_dir = job_dir / "scene"
                safe_extract(src, scene_dir)
                src.unlink(missing_ok=True)
                blends = sorted(scene_dir.rglob("*.blend"), key=lambda p: len(p.parts))
                if not blends:
                    raise RuntimeError("No .blend file found in the uploaded archive")
                return job_dir, blends[0]
            if src.suffix != ".blend":
                raise RuntimeError(f"Unsupported input type {src.suffix}; upload a .blend or a .zip containing one")
            return job_dir, src
        except BaseException:
            if job_dir is not None:
                shutil.rmtree(job_dir, ignore_errors=True)
            raise

    async def render(self, job: Dict[str, Any], blend: Path, out_dir: Path) -> None:
        start, end = int(job["frame_start"]), int(job["frame_end"])
        total = max(end - start + 1, 1)
        settings = job.get("settings") or {}
        # --disable-autoexec: never run scripts embedded in a customer's .blend file
        cmd = [self.blender, "-b", str(blend), "--disable-autoexec", "-o", str(out_dir / "frame_#####")]
        if self.threads > 0:
            cmd += ["-t", str(self.threads)]
        engine = str(settings.get("engine", "")).upper()
        if engine in ALLOWED_ENGINES:
            cmd += ["-E", engine]
        if settings.get("format") in {"PNG", "JPEG", "OPEN_EXR", "TIFF"}:
            cmd += ["-F", settings["format"]]
        cmd += ["-s", str(start), "-e", str(end), "-a"]
        if job.get("requires_gpu"):
            cmd += ["--", "--cycles-device", "OPTIX,CUDA,HIP,METAL"]
        logger.info("Running: %s", " ".join(cmd))

        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        loop = asyncio.get_running_loop()
        deadline = time.time() + self.max_job_seconds
        last_sent, tail = 0.0, []
        while True:
            line = await loop.run_in_executor(None, self.proc.stdout.readline)
            if not line:
                break
            tail = (tail + [line.rstrip()])[-15:]
            m = FRAME_RE.search(line)
            if m and time.time() - last_sent > 3:
                last_sent = time.time()
                done = max(int(m.group(1)) - start, 0)
                await self.send({"type": "job_progress", "job_id": job["job_id"], "chunk_id": job.get("chunk_id"),
                                 "progress": min(done / total * 100, 99)})
            if time.time() > deadline:
                self.proc.kill()
                raise RuntimeError("Render exceeded the maximum allowed time")
        code = await loop.run_in_executor(None, self.proc.wait)
        if self.cancelled:
            return
        if code != 0:
            raise RuntimeError("Blender exited with code %s: %s" % (code, " | ".join(tail[-5:])))
        if not any(out_dir.iterdir()):
            raise RuntimeError("Blender produced no output")

    def pack_output(self, job_dir: Path, out_dir: Path) -> Path:
        base = job_dir / "result"
        return Path(shutil.make_archive(str(base), "zip", out_dir))

    def upload_output(self, job: Dict[str, Any], archive: Path) -> None:
        with open(archive, "rb") as f:
            r = requests.post(f"{self.http_base}/api/jobs/{job['job_id']}/output",
                              params={"chunk_id": job.get("chunk_id")}, headers=self.headers(),
                              files={"file": (archive.name, f, "application/zip")}, timeout=(10, 600))
        r.raise_for_status()


# ---------- performance test ----------
def _hash_burst(seconds: float) -> int:
    import hashlib
    end, n, data = time.time() + seconds, 0, b"renderswarm" * 64
    while time.time() < end:
        for _ in range(2000):
            data = hashlib.sha256(data).digest() * 2
        n += 2000
    return n


TEST_SCENE = """
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_monkey_add()
m = bpy.context.object.modifiers.new('s', 'SUBSURF'); m.levels = m.render_levels = 3
bpy.ops.object.light_add(type='SUN', location=(4, 4, 6))
bpy.ops.object.camera_add(location=(0, -6, 2), rotation=(1.2, 0, 0))
sc = bpy.context.scene
sc.camera = bpy.context.object
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = 128
sc.render.resolution_x = sc.render.resolution_y = 512
sc.render.filepath = r'%s'
bpy.ops.render.render(write_still=True)
"""


def run_test(server: str, token: str, blender: str, workdir: Path) -> None:
    import platform
    base = normalize_server(server)
    print(f"BlendSwarm worker test v{VERSION}\n")
    result: Dict[str, Any] = {"token": token}

    print("1/5 Connecting to the pool server ...")
    try:
        t0 = time.time()
        r = requests.post(f"{base}/api/workers/auth", json={"token": token}, timeout=15)
        result["latency_ms"] = round((time.time() - t0) * 1000, 1)
        if r.status_code == 401:
            sys.exit("   FAILED: the worker token is invalid. Copy it again from My Workers.")
        r.raise_for_status()
        print(f"   OK - worker '{r.json().get('name')}' authenticated, latency {result['latency_ms']} ms")
        t0 = time.time()
        size = len(requests.get(f"{base}/downloads/worker_client.py", timeout=30).content)
        dt = max(time.time() - t0, 0.001)
        result["download_mb_s"] = round((size / 1e6) / dt, 2)
    except requests.RequestException as e:
        sys.exit(f"   FAILED: cannot reach {base} ({e})")

    print("2/5 CPU benchmark (5 s on all cores) ...")
    cores = psutil.cpu_count(logical=True) or 1
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor(max_workers=cores) as ex:
        total = sum(ex.map(_hash_burst, [5.0] * cores))
    result["cpu_score"] = round(total / 5.0 / 1e6 * 1.0, 2)
    print(f"   {result['cpu_score']} (higher is better, {cores} threads)")

    print("3/5 Disk write test ...")
    workdir.mkdir(parents=True, exist_ok=True)
    f = workdir / "rs_disk_test.bin"
    chunk, t0 = os.urandom(1024 * 1024), time.time()
    with open(f, "wb") as fh:
        for _ in range(256):
            fh.write(chunk)
        fh.flush()
        os.fsync(fh.fileno())
    result["disk_mb_s"] = round(256 / max(time.time() - t0, 0.001), 1)
    f.unlink(missing_ok=True)
    print(f"   {result['disk_mb_s']} MB/s")

    print("4/5 Blender render test ...")
    gpus = []
    if GPUtil:
        try:
            gpus = [g.name for g in GPUtil.getGPUs()]
        except Exception:
            pass
    try:
        out = workdir / "rs_test.png"
        script = workdir / "rs_test.py"
        script.write_text(TEST_SCENE % str(out).replace("\\", "/"))
        ver = subprocess.run([blender, "--version"], capture_output=True, text=True, timeout=60).stdout.split("\n")[0]
        result["blender_version"] = ver.strip()
        t0 = time.time()
        p = subprocess.run([blender, "-b", "-noaudio", "--python", str(script)], capture_output=True, text=True, timeout=900)
        if p.returncode == 0 and out.exists():
            result["render_seconds"] = round(time.time() - t0, 2)
            print(f"   {result['blender_version']} rendered the test scene in {result['render_seconds']} s")
        else:
            print("   Blender failed to render the test scene (jobs would fail on this machine)")
        out.unlink(missing_ok=True)
        script.unlink(missing_ok=True)
    except Exception as e:
        print(f"   Blender not usable: {e}")

    result["hardware"] = {
        "os": f"{platform.system()} {platform.release()}", "cpu": platform.processor() or platform.machine(),
        "cores": cores, "ram_gb": round(psutil.virtual_memory().total / 2**30, 1), "gpus": gpus,
    }
    print("5/5 Uploading the result ...")
    r = requests.post(f"{base}/api/workers/benchmark", json=result, timeout=20)
    r.raise_for_status()
    print(f"\nDone. Overall score: {r.json()['score']}/100. History: {base}/workers")


def main() -> None:
    p = argparse.ArgumentParser(description="BlendSwarm worker client")
    p.add_argument("--server", default=os.getenv("RENDERSWARM_SERVER", os.getenv("RENDERPOOL_SERVER")), help="e.g. https://your-domain.com")
    p.add_argument("--token", default=os.getenv("RENDERSWARM_TOKEN", os.getenv("RENDERPOOL_TOKEN")), help="Worker token from the dashboard")
    p.add_argument("--discovery-code", help="auto-register this computer using a short-lived code from the dashboard")
    p.add_argument("--enroll-only", action="store_true", help="register this computer and exit without starting its worker")
    p.add_argument("--blender", default=os.getenv("BLENDER_PATH") or shutil.which("blender") or "blender")
    p.add_argument("--workdir", default=os.getenv("RENDERSWARM_WORKDIR") or os.getenv("RENDERPOOL_WORKDIR") or tempfile.gettempdir())
    p.add_argument("--require-ram", action="store_true",
                   help="refuse jobs when the decrypted scene cannot be kept on a RAM disk (/dev/shm)")
    p.add_argument("--max-job-hours", type=float, default=12.0)
    p.add_argument("--always-on", action="store_true",
                   help="accept jobs immediately without waiting for the machine to be idle for five minutes")
    p.add_argument("--threads", type=int, default=0,
                   help="maximum Blender render threads (0 lets Blender decide)")
    p.add_argument("--test", action="store_true", help="run a performance test, upload the result and exit")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    a = p.parse_args()
    if not a.server:
        p.error("--server is required")
    if a.token and a.discovery_code:
        p.error("use either --token or --discovery-code, not both")
    if a.threads < 0:
        p.error("--threads cannot be negative")
    logger.setLevel(a.log_level)
    if not a.token:
        try:
            a.token = enroll_worker(a.server, a.discovery_code) if a.discovery_code else _load_worker_token(a.server)
        except RuntimeError as exc:
            p.error(str(exc))
        if not a.token:
            p.error("provide --token or --discovery-code, or pair this computer from the dashboard")
    if a.enroll_only:
        if not a.discovery_code:
            p.error("--enroll-only requires --discovery-code")
        return
    if shutil.which(a.blender) is None and not Path(a.blender).exists():
        p.error(f"Blender not found at '{a.blender}'. Install Blender or pass --blender /path/to/blender")
    workdir = Path(a.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if a.test:
        run_test(a.server, a.token, a.blender, workdir)
        return

    worker = Worker(
        a.server, a.token, a.blender, workdir, int(a.max_job_hours * 3600),
        a.threads, idle_only=not a.always_on,
    )
    worker.require_ram = a.require_ram
    try:
        asyncio.run(worker.run())
    except KeyboardInterrupt:
        print("\nWorker stopped")


if __name__ == "__main__":
    main()
