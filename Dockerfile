# 3.13 matches .python-version, which is copied in with the rest of the tree; on a
# mismatch uv downloads its own 3.13 and this image's interpreter goes unused.
FROM python:3.13-slim

# Install uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the application into the container.
COPY . /app

# Install the application dependencies.
#
# --frozen installs uv.lock verbatim and fails if it has drifted from pyproject.toml,
# so a forgotten `uv lock` breaks the build rather than the deploy.
WORKDIR /app
RUN uv sync --frozen --no-cache --no-dev

# Run the bot. `-O` strips the assert statements the modules use to narrow types -
# they are checks on our own wiring, not on anything Discord sends.
CMD ["/app/.venv/bin/python", "-O", "-m", "alfred"]
