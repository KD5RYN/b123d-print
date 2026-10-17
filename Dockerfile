# Optional: run the cadkit MCP server in a container. This is the strongest isolation for
# model-written part scripts: no network, only the mounted workspace is visible.
#
#   docker build -t cadkit-mcp .
#   docker run -i --rm --network none -v "$PWD:/work" cadkit-mcp
#
# MCP clients: command "docker", args ["run","-i","--rm","--network","none","-v","/abs/path/to/parts:/work","cadkit-mcp"]
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /usr/local/bin/

# OpenCascade (in the OCP wheel) links against these on Linux
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxrender1 libfontconfig1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/cadkit
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/cadkit/.venv
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# The container is the sandbox here (bubblewrap cannot nest without extra privileges).
ENV PATH=/opt/cadkit/.venv/bin:$PATH CADKIT_SANDBOX=none MPLCONFIGDIR=/tmp/mpl
RUN useradd --create-home cad && mkdir /work && chown cad /work
USER cad
WORKDIR /work
ENTRYPOINT ["cadkit-mcp", "--workspace", "/work"]
