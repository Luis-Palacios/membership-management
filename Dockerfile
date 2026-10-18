# syntax=docker/dockerfile:1

# Same base image in both stages: the builder creates /app/.venv against this exact Python, and the
# runtime stage copies it as-is (the venv's scripts point at /app/.venv/bin/python by absolute path).
# Pinned exactly, including the Debian release, because the ODBC driver repo below is Debian 13 only.
ARG PYTHON_IMAGE=python:3.14.7-slim-trixie

# ---------- builder: resolve and install everything into /app/.venv ----------
FROM ${PYTHON_IMAGE} AS builder

# Pinned uv (never :latest), copied from its official image. It exists only in this stage.
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

# UV_COMPILE_BYTECODE: write .pyc files now instead of on every cold start of a task.
# UV_LINK_MODE=copy: the cache mount is another filesystem, so uv can't hardlink from it.
# UV_PYTHON_DOWNLOADS=0: always use the image's Python, never download a different one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Dependencies only. The lock and both pyproject files are bind-mounted (not copied), so this layer
# is reused until one of them changes: editing src/ doesn't reinstall everything. --locked fails the
# build if uv.lock is out of date. --no-install-workspace skips our own packages (no source yet).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=src/membership_management/api/pyproject.toml,target=src/membership_management/api/pyproject.toml \
    uv sync --locked --no-dev --all-packages --no-install-workspace

# Now our own code. --no-editable installs it into site-packages like any other package, so the
# runtime stage needs only /app/.venv: no source tree, no pyproject.toml, no uv.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --all-packages --no-editable

# ---------- runtime: Python + ODBC driver + the venv, nothing else ----------
FROM ${PYTHON_IMAGE} AS runtime

# Microsoft ODBC Driver 18 (pulls in unixODBC's libodbc, which pyodbc links against), from
# Microsoft's apt repo. All in one RUN so curl and the apt lists never reach a layer: removing them
# in a later RUN would only hide them, not shrink the image. ACCEPT_EULA=Y accepts the driver's
# license, which apt requires. Pinned like the base image; bump it on purpose.
# libgssapi-krb5-2 is listed explicitly: the driver links against it but its package doesn't
# declare it, so it would only arrive through curl and be auto-removed with it (ldd: "not found").
ARG MSODBCSQL_VERSION=18.7.1.1-1
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libgssapi-krb5-2 \
    && curl -fsSL -o /tmp/packages-microsoft-prod.deb \
        https://packages.microsoft.com/config/debian/13/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18=${MSODBCSQL_VERSION} \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Amazon RDS CA bundle. The prod MEMBERS_DATABASE_URL (the app as members_app, the migrate task as
# members_owner) ends in ?sslmode=verify-full&sslrootcert=/etc/ssl/rds/global-bundle.pem, and the
# system CA store doesn't include the RDS CA, so without this file every connection fails. libpq
# (psycopg) reads it when it connects; URLs without sslrootcert (local dev, compose, the seed, which
# never runs in prod) never touch it, nor does the Azure SQL connection (ODBC 18 checks Azure's
# public CA against the system store). Same path in auth-server's image.
# Owned by root (ADD ignores USER) and 0644: appuser can read it but not change it. A remote ADD
# defaults to 0600, which appuser couldn't read. The directory is made first because ADD would
# create it with the same --chmod (0644, no x), and appuser couldn't enter it.
# --checksum needs dockerfile syntax 1.6+ (the directive above follows the latest 1.x). When AWS
# updates the bundle, an uncached build fails on the checksum. Check the change is AWS's, then:
#   curl -fsS https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem | shasum -a 256
# and paste the new hash here (and in auth-server's Dockerfile).
RUN mkdir -p /etc/ssl/rds
ADD --checksum=sha256:90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b --chmod=644 \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /etc/ssl/rds/global-bundle.pem

# Non-root user for the process. Everything below stays root-owned, so the app can't modify its
# own installed code.
ARG UID=10001
RUN useradd --uid ${UID} --no-create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /app/.venv /app/.venv

# The venv's bin/ first on PATH, so `python` is the venv's. PYTHONUNBUFFERED: logs reach CloudWatch
# right away instead of sitting in a buffer (and getting lost if the process dies).
# PYTHONDONTWRITEBYTECODE: bytecode was compiled at build time, and the venv isn't writable anyway.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
USER appuser
EXPOSE 8000

# Exec form: python is PID 1 and receives SIGTERM directly, so uvicorn's graceful shutdown runs
# (GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS). A shell form or `uv run` would put a process in between.
# ENVIRONMENT and every other setting come from the task definition at run time; none is baked in.
CMD ["python", "-m", "membership_management.api.run"]
