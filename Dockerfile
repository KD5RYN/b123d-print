# Optional: run the b123d-print MCP server in a container. This is the strongest isolation for
# model-written part scripts: no network, only the mounted workspace is visible.
#
#   docker build -t b123d-print-mcp .
#   docker run -i --rm --network none -v "$PWD:/work" b123d-print-mcp
#
# MCP clients: command "docker", args ["run","-i","--rm","--network","none","-v","/abs/path/to/parts:/work","b123d-print-mcp"]
#
# The same image as a network service (Streamable HTTP at /mcp, named bearer tokens): use
# deploy/compose.yaml, which runs it twice, an HTTP front (network, no part scripts) and a
# `worker` (network_mode: none) that runs the builds. Single container, for a quick try:
#
#   docker run -d --name b123d-print -p 127.0.0.1:8000:8000 -v "$PWD:/work" \
#     -e B123D_PRINT_TRANSPORT=http -e B123D_PRINT_TOKEN="$(cat token)" b123d-print-mcp
#
# Select HTTP with the environment (not only with arguments) so the HEALTHCHECK knows to probe /health.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /usr/local/bin/

# OpenCascade (in the OCP wheel) links against the libGL/X libraries; bubblewrap lets the HTTP
# deployment's worker run each job in its own mount namespace (deploy/compose.yaml)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libfontconfig1 bubblewrap \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/b123d-print
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/b123d-print/.venv
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# The container is the sandbox here (bubblewrap cannot nest without extra privileges).
ENV PATH=/opt/b123d-print/.venv/bin:$PATH B123D_PRINT_SANDBOX=none MPLCONFIGDIR=/tmp/mpl XDG_CACHE_HOME=/tmp/cache \
    B123D_PRINT_CONFIG_IN_WORKSPACE=1 B123D_PRINT_HOST=0.0.0.0 B123D_PRINT_PORT=8000
RUN useradd --create-home cad && mkdir /work && chown cad /work
USER cad
WORKDIR /work
EXPOSE 8000
# stdio: always healthy while it runs; http: GET /health
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --start-interval=2s CMD ["b123d-print-mcp", "--healthcheck"]
ENTRYPOINT ["b123d-print-mcp", "--workspace", "/work"]
