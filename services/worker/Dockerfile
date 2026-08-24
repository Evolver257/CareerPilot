FROM python:3.13-slim

WORKDIR /worker
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY worker ./worker

CMD ["python", "-m", "worker.main"]
