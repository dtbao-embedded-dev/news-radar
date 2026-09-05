# The crawl service. Fetch -> filter -> rank -> store -> render -> notify, on an
# internal loop. It opens no port: it talks out, nothing talks in.
#
# Built from the repository root (docker-compose.yml sets context: ..) so that
# VERSION, requirements.txt and src/ are all reachable.

# Pinned by digest, not just by tag: a tag moves, and a build that cannot be
# reproduced is not a build. Re-pin deliberately, in its own commit.
FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

# PYTHONUNBUFFERED: without it Python block-buffers stdout when it is not a tty,
# and `docker logs` shows nothing until the buffer fills - which for a service
# that logs once every 30 minutes means it looks hung.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    NEWS_RADAR_CONFIG=/app/config/config.yaml

WORKDIR /app

# Dependencies first and alone: this layer is cached until requirements.txt
# itself changes, so editing source does not reinstall anything.
COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt

# VERSION is read at runtime for the User-Agent, so it has to be in the image.
COPY VERSION ./
COPY src/ ./src/

# ponytail: runs as root. The container exposes no port and only fetches feeds,
# and a non-root uid would have to match the owner of the bind-mounted output/
# on the host - which differs between this Windows homelab and a Linux one.
# Switch to a fixed uid once output/ is a named volume rather than a bind mount.

# No HEALTHCHECK: a crawl loop that sleeps 30 minutes has no cheap liveness
# signal yet. P6-1 adds a heartbeat, and the healthcheck belongs with it.

ENTRYPOINT ["python", "-m", "news_radar"]
