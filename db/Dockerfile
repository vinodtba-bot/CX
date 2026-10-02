# The init script is copied into the image (not bind-mounted) so it is always
# executable, whatever file permissions the host checkout or Docker Desktop's
# file sharing report.
FROM postgres:16-alpine
COPY --chmod=755 init.sh /docker-entrypoint-initdb.d/10-init.sh
