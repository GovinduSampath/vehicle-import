# Multi-stage: the build stage carries compilers and dev headers, the runtime
# stage carries neither. Smaller image, smaller CVE surface for Trivy to find.
FROM python:3.12-slim AS build
WORKDIR /build
COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install \
      fastapi uvicorn[standard] jinja2 pyyaml pydantic python-multipart sqlalchemy

FROM python:3.12-slim AS runtime
# Never run as root. This is the first thing a reviewer looks for.
RUN useradd --create-home --uid 10001 app
COPY --from=build /install /usr/local
WORKDIR /app
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
