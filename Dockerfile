FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv blender ca-certificates \
      libgl1 libxi6 libxrender1 libxfixes3 libxkbcommon0 libsm6 \
    && rm -rf /var/lib/apt/lists/*
RUN blender --version | grep -Eq '^Blender (3\.([6-9]|[1-9][0-9])|[4-9]\.)' \
    && python3 -m venv /opt/worker-venv
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY src/python/worker_client.py /app/worker_client.py
RUN /opt/worker-venv/bin/python -m pip install --no-cache-dir -r /app/requirements.txt
ENV BLENDER_PATH=/usr/bin/blender RENDERSWARM_WORKDIR=/work
ENTRYPOINT ["/opt/worker-venv/bin/python", "/app/worker_client.py"]
