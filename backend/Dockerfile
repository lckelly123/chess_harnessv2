FROM python:3.13-slim AS stockfish

# Official generic x86-64 release, including its license and corresponding source.
ADD --checksum=sha256:5c6f38b02a4da5f3ffe763f27da6c3e743eebefd92b50cb3661623b96696adff \
    https://github.com/official-stockfish/Stockfish/releases/download/sf_18/stockfish-ubuntu-x86-64.tar /tmp/stockfish.tar
RUN mkdir -p /opt && tar -xf /tmp/stockfish.tar -C /opt

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    STOCKFISH_PATH=/opt/stockfish/stockfish-ubuntu-x86-64

COPY --from=stockfish /opt/stockfish /opt/stockfish

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY chess_core ./chess_core
COPY harness ./harness
COPY positional_testing ./positional_testing

FROM base AS test
COPY pyproject.toml .
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
CMD ["pytest", "-q"]

FROM base AS development
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS production
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
