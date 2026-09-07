FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
ARG INSTALL_SEMANTIC=false
RUN if [ "$INSTALL_SEMANTIC" = "true" ]; then pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir 'sentence-transformers>=3,<6'; fi
COPY app ./app
COPY alembic ./alembic
COPY scripts ./scripts
COPY tools ./tools
COPY evaluation ./evaluation
COPY alembic.ini ./alembic.ini

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
