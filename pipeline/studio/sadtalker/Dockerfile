# SadTalker on PyTorch 1.12 + CUDA 11.3: the newest stack it supports, and it still has GTX 1050 (Pascal) kernels.
FROM python:3.8-slim-bullseye
RUN apt-get update && apt-get install -y --no-install-recommends git wget ffmpeg libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/OpenTalker/SadTalker.git /app
WORKDIR /app
RUN pip install --no-cache-dir torch==1.12.1+cu113 torchvision==0.13.1+cu113 torchaudio==0.12.1 \
        --extra-index-url https://download.pytorch.org/whl/cu113 \
    && pip install --no-cache-dir -r requirements.txt
RUN bash scripts/download_models.sh
COPY server.py /app/server.py
CMD ["python", "server.py"]
