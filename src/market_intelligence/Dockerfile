# Pin the reviewed base image digest so a rebuild cannot silently pull a
# different OS/Python layer from the registry.
FROM python:3.13-slim@sha256:7e3a6aca9d74f93cca21a91d86a8dad8c34749afd5b4a98ee481c9c47b9f5ed4

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10002 market-intelligence \
    && useradd \
       --uid 10002 \
       --gid market-intelligence \
       --create-home market-intelligence

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt

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
