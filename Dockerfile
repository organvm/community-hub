FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

# Pin koinonia-db to a specific commit to prevent breaking changes
ARG KOINONIA_DB_REF=8414b2e
RUN pip install --no-cache-dir \
    "koinonia-db @ git+https://github.com/organvm-vi-koinonia/koinonia-db.git@${KOINONIA_DB_REF}" \
    .

# Clone koinonia-db at the same pinned ref for Alembic migrations
RUN git clone https://github.com/organvm-vi-koinonia/koinonia-db.git /app/koinonia-db-migrations && \
    cd /app/koinonia-db-migrations && git checkout ${KOINONIA_DB_REF}

EXPOSE 8000

ENTRYPOINT ["bash", "/app/scripts/entrypoint.sh"]
