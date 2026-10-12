FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core git \
    && rm -rf /var/lib/apt/lists/*
# cu126 wheels still ship kernels for Pascal (GTX 1050, sm_61); newer CUDA builds dropped it.
RUN pip install --no-cache-dir torch==2.7.1 --index-url https://download.pytorch.org/whl/cu126
COPY requirements-studio.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-studio.txt
WORKDIR /app/pipeline
