BlendSwarm worker bundle
========================

This bundle contains the BlendSwarm worker client and its installer, not Blender.
It runs Blender Cycles/Eevee jobs on Windows or Linux PCs; Android/iOS are not
supported. Install Blender 3.6+ and Python 3.9+ before setup:
  Blender: https://www.blender.org/download/
  Python:  https://www.python.org/downloads/

1. Sign in at https://blendswarm.com, open My Workers > Add Worker and create
   a worker. Copy its token; treat it like a password.
2. Install Blender and Python:
   - Windows: install both; for Python, enable "Add python.exe to PATH".
   - Linux: install Blender 3.6+, Python 3.9+, python3-venv and curl.
3. Extract the ZIP (Windows) or TAR.GZ (Linux).
4. Windows (recommended):
   - Open the extracted folder and double-click start-worker.cmd.
   - Press Enter to accept https://blendswarm.com.
   - Paste the worker token at the hidden prompt; the characters do not appear.
   - Accept the optional benchmark. Keep the PowerShell window open while it runs.
   - Press Ctrl+C to stop the worker. Errors remain visible in the window.
   Alternative (PowerShell, from the extracted folder):
   Set-ExecutionPolicy -Scope Process Bypass
   .\install.ps1 -Server https://blendswarm.com
   The installer asks for the token without displaying it.
   The token is saved encrypted for your Windows account and is not passed in
   the worker process command line.
   Test: & "$env:USERPROFILE\.blendswarm-worker\run-worker.ps1" --test
   Run:  & "$env:USERPROFILE\.blendswarm-worker\run-worker.ps1"
5. Linux (terminal, in the extracted folder):
   bash install.sh --server https://blendswarm.com --service
   The installer asks for the token without displaying it.
   It is stored in ~/.blendswarm-worker/worker.env, readable only by your user,
   and is not passed in the worker process command line.
   Test: ~/.blendswarm-worker/run.sh --test
   Without --service, start manually: ~/.blendswarm-worker/run.sh
   With --service, systemd starts/restarts the worker in your user session.
   On a headless server, enable systemd lingering for your account if the worker
   must start before an interactive login: sudo loginctl enable-linger USERNAME.

Auto-discovery / enrollment
--------------------------

In My Workers > Add Worker > Auto-Discovery, create a temporary code. On each
Windows/Linux computer on your network, extract this bundle and run:

Windows PowerShell:
  .\install.ps1 -Server https://blendswarm.com -DiscoveryCode YOUR_CODE
  & "$env:USERPROFILE\.blendswarm-worker\run-worker.ps1"

Linux:
  bash install.sh --server https://blendswarm.com --discovery-code YOUR_CODE
  ~/.blendswarm-worker/run.sh

The code expires after 15 minutes and can enroll at most 10 computers. Share it
only with computers you control. Each computer reports its hostname, operating
system, CPU, memory, and detected GPUs; the installer stores its individual
worker credential locally. This is an enrollment handshake, not a browser-based
LAN port scan. Each computer must run the worker installer to be detected.

The platform-specific downloads are blendswarm-worker-windows.zip and
blendswarm-worker-linux.tar.gz. Their installers use the files in the bundle;
they do not bundle Blender or Python. Do not paste worker tokens into public
chat, screenshots, URLs or shell command history.

For NVIDIA GPU support in Docker, install NVIDIA Container Toolkit and use
--gpus all. GPU rendering requires a compatible driver and Blender setup.
On Windows, use start-worker.cmd rather than double-clicking install.ps1.
See https://blendswarm.com/setup for the current guide.
