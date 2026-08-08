# Multi-stage: the build stage carries compilers and dev headers, the runtime
# stage carries neither. Smaller image, smaller CVE surface for Trivy to find.
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install \
      fastapi uvicorn[standard] jinja2 pyyaml pydantic python-multipart sqlalchemy

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
COPY --from=build /install /usr/local
WORKDIR /app
COPY --chown=app:app app ./app

# SQLite needs a writable directory. /app itself is root-owned even after
# the chown above, since that only covers the app/ subfolder being copied
# in -- this is what caused "unable to open database file" in CI.
RUN mkdir -p /app/data && chown -R app:app /app/data
ENV DATABASE_URL=sqlite:////app/data/inventory.db

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
