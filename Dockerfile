FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential g++ libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces chạy container với user 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH INSIGHTFACE_HOME=/home/user/.insightface
WORKDIR /home/user/app

COPY --chown=user requirements-server.txt .
RUN pip install --no-cache-dir cython "numpy<2" && pip install --no-cache-dir -r requirements-server.txt

# Tải sẵn model lúc build để khởi động nhanh hơn
RUN python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_l', root='/home/user/.insightface', providers=['CPUExecutionProvider'], allowed_modules=['detection','recognition','landmark_3d_68'])"

COPY --chown=user . .

EXPOSE 7860
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860"]
