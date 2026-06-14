# Single image for all BESS subcommands (simulate / generate-prices / optimise / run).
# Python 3.12-slim has broad wheel coverage for numpy/pyarrow/pulp/s3fs.
FROM python:3.12-slim

# Faster, quieter Python in containers.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY main.py config.yaml ./
COPY src ./src

# The entrypoint is the CLI group; the subcommand + flags are passed as args, e.g.
#   docker run <image> run --root s3://bucket --time-scale 1
#   docker run <image> optimise --root s3://bucket
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
