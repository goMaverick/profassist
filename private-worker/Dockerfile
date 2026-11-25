ARG PROFASSIST_WORKER_BASE_IMAGE=student-dropout:local
FROM ${PROFASSIST_WORKER_BASE_IMAGE}

ENV PYTHONPATH=/app/src \
    PROFASSIST_WORKER_STORE=/var/lib/profassist-worker \
    PORT=8081 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER root
RUN useradd --uid 10002 --create-home --shell /usr/sbin/nologin worker && \
    mkdir -p /opt/profassist-worker /var/lib/profassist-worker && \
    chown -R worker:worker /opt/profassist-worker /var/lib/profassist-worker

COPY --chown=worker:worker private-worker/server.py /opt/profassist-worker/server.py
USER worker
EXPOSE 8081
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health')" || exit 1
CMD ["python", "/opt/profassist-worker/server.py"]
