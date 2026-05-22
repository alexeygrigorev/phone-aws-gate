FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN uv pip install --system --no-cache "boto3>=1.34" "awscli>=1.32"

COPY loop.py /loop.py
CMD ["python", "/loop.py"]
