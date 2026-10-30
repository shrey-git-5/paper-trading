# Paper Trader for Google Cloud Run. Standard-library Python only, so the image is tiny.
FROM python:3.12-slim
WORKDIR /app
COPY backend ./backend
COPY frontend ./frontend
ENV HOST=0.0.0.0 \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1
# Cloud Run sets PORT itself (8080 by default).
CMD ["python3", "backend/server.py"]
