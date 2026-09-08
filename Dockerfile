FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get autoremove -y

WORKDIR /fer

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install the project's dependencies using the lockfile and settings
# Mounting for layer caching, recommended in the uv docs
# (see https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers)

RUN --mount=type=cache,target=/fer/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev



# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY . /fer

RUN --mount=type=cache,target=/fer/.cache/uv \
    uv sync --locked --no-dev

# Add a non-root user to run the app
RUN addgroup --system fer && adduser --system --ingroup fer --home /home/fer fer \
    && chown -R fer:fer /fer /home/fer

ENV HOME=/home/fer


# Place executables in the environment at the front of the path
ENV PATH="/fer/.venv/bin:$PATH"

USER fer

# Reset the entrypoint, don't invoke `uv`

ENTRYPOINT []
EXPOSE 8001

CMD ["python", "run_robot.py"]
