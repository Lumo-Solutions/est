# DWG -> DXF converter sandbox (docs/deploy-deltas.md "DWG conversion").
#
# Wraps the ODA File Converter, installed from a LOCAL .deb (no download at
# build or run time -- the site is air-gapped). The .deb lives in
# deploy/vendor/oda/ (gitignored, never committed) and reaches the build via
# the `oda` additional build context in docker-compose.yml, so this image is
# only ever built on a machine that already holds the package.
#
# LICENCE: the ODA File Converter may not be "licensed, sold, distributed or
# included with other software products without the written consent of Open
# Design Alliance". This image is therefore INTERNAL USE ONLY: build it
# locally, run it on servers we control, never push it to a registry or hand
# it to a third party.
#
# DWG is untrusted input. The runtime (see docker-compose.yml) gives this
# container no network, a read-only root filesystem, tmpfs scratch space, no
# capabilities and CPU/memory/pids limits; it talks to the rest of the stack
# only through the shared /spool volume (converter_loop.py).
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 xvfb xauth \
        libgl1 libglx-mesa0 libegl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 libfreetype6 \
        libdbus-1-3 libglib2.0-0t64 libxcb1 libx11-6 libx11-xcb1 libxcb-xinerama0 libxcb-xkb1 \
        libxrender1 libxi6 libsm6 libice6 libnss3 libopengl0 libgssapi-krb5-2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=oda ODAFileConverter*.deb /tmp/oda.deb
# dpkg -i (not apt) so nothing is fetched; the deb's own deps are the libs above.
RUN dpkg -i /tmp/oda.deb; rm -f /tmp/oda.deb; test -x /usr/bin/ODAFileConverter

# uid 1000 == the `app` user of the backend image, so both containers can
# read and write each other's files on the shared spool volume.
RUN (id ubuntu >/dev/null 2>&1 && userdel -r ubuntu || true) \
    && useradd --create-home --uid 1000 conv \
    && mkdir -p /spool && chown 1000:1000 /spool
COPY converter_loop.py /opt/converter_loop.py

ENV HOME=/tmp \
    QT_QPA_PLATFORM=xcb \
    SPOOL_DIR=/spool
USER 1000
CMD ["python3", "/opt/converter_loop.py"]
