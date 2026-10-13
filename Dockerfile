FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY models/ ./models/
# Default data so a plain `docker run` works; compose mounts ./data over it
COPY data/ ./data/
ENV DATA_DIR=/srv/data
EXPOSE 8000
# One worker: the catalogue lives in RAM and requests are cheap
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
