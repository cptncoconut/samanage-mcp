FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml README.md ./
COPY samanage_mcp ./samanage_mcp

RUN pip install --no-cache-dir .

ENV HOST=0.0.0.0 \
    PORT=8765

EXPOSE 8765

CMD ["samanage-mcp", "--http"]
