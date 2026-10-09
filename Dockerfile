FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip blender ca-certificates \
      libgl1 libxi6 libxrender1 libxfixes3 libxkbcommon0 libsm6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt /app/requirements.txt
COPY src/python/worker_client.py /app/worker_client.py
RUN pip3 install --no-cache-dir -r /app/requirements.txt
ENV BLENDER_PATH=/usr/bin/blender RENDERSWARM_WORKDIR=/work
ENTRYPOINT ["python3", "/app/worker_client.py"]
