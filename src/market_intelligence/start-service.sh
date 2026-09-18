#!/bin/sh
set -eu

alembic upgrade head
# Health/readiness probes run every few seconds.  Uvicorn access logging for
# those probes can drown out the operational signal, so application logs are
# reserved for startup, pipeline and actionable error events.
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --no-access-log
