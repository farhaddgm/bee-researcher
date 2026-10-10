# Pin the reviewed base image digest so a rebuild cannot silently pull a
# different OS/Python layer from the registry.
FROM python:3.13-slim@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0

ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="3.40.1"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV MARKET_INTELLIGENCE_BUILD_REVISION=${SOURCE_REVISION}

# Apply Debian security fixes published after the pinned base image (e.g.
# OpenSSL and PCRE2 advisories) so the image scan gate stays green without
# moving the reviewed Python layer.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10002 market-intelligence \
    && useradd \
       --uid 10002 \
       --gid market-intelligence \
       --create-home market-intelligence

WORKDIR /app

COPY requirements.txt .
# pip/ensurepip are build-only; remove their stale vendored bundles from runtime.
RUN pip install --no-cache-dir --requirement requirements.txt \
    && rm -rf /usr/local/lib/python3.13/site-packages/pip \
              /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
              /usr/local/lib/python3.13/ensurepip \
              /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
    && python -c 'import importlib.util; assert importlib.util.find_spec("pip") is None; assert importlib.util.find_spec("ensurepip") is None'

COPY --chown=10002:10002 alembic.ini .
COPY --chown=10002:10002 alembic ./alembic
COPY --chown=10002:10002 app ./app
COPY --chown=10002:10002 tests ./tests
COPY --chown=10002:10002 scripts ./scripts
COPY --chown=10002:10002 golden ./golden
COPY --chown=10002:10002 VERSION ./VERSION
COPY --chown=10002:10002 --chmod=755 start-service.sh ./start-service.sh

USER market-intelligence

EXPOSE 8010

CMD ["./start-service.sh"]
