# Headless Pi coding-agent, one instance per container, driven over RPC (JSON on stdio).
#
# Built from LOCAL monorepo source (not the published npm package) so it includes the
# `skill_invocation` RPC event added in packages/coding-agent/src/core/agent-session.ts.
# Extended from the recipe in packages/coding-agent/docs/containerization.md to:
#   - build @earendil-works/pi-coding-agent from source and install the packed tarball
#   - bake the Azure provider config into ~/.pi/agent/models.json
#   - default to `--mode rpc --no-extensions --no-session`
#
# BUILD CONTEXT MUST BE THE REPO ROOT (the whole monorepo is copied into the builder):
#   docker build -t pi-sandbox -f docker-pi/Dockerfile .

# ── Builder stage: compile the monorepo and pack the coding-agent tarball ──────────────
FROM node:24-bookworm-slim AS builder
# Pi requires Node >=22.19 (root package.json engines); node:24 satisfies it.

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git python3 make g++ \
  && rm -rf /var/lib/apt/lists/*
# python3/make/g++: node-gyp toolchain for any native deps built during npm ci.

WORKDIR /src
COPY . .
# The whole monorepo (npm workspaces): root package-lock.json + all packages/*.

RUN npm ci --ignore-scripts
# Reproducible install of all workspace deps from the root lockfile. --ignore-scripts
# per repo policy (postinstall model-data hydration is not needed; the bundle bakes it in).

RUN npm run build:offline
# Root offline build: same as `build` but ai uses its committed model data
# (src/providers/data) instead of `generate-models`, which fetches from models.dev/OpenRouter.
# Keeps the image build hermetic (no network codegen). Compiles chord, tui, telemetry, ai,
# agent, protocol, client, server, then coding-agent (tsgo -> esbuild bundle at
# packages/coding-agent/dist/bundle/cli.js).

RUN cd packages/coding-agent && npm pack --pack-destination /tmp
# Produces /tmp/earendil-works-pi-coding-agent-<version>.tgz — same shape as the published
# package (files: dist + npm-shrinkwrap.json), so the runtime install below matches prod.

# ── Runtime stage: slim image with just `pi` installed from the local tarball ──────────
FROM node:24-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates git ripgrep \
  && rm -rf /var/lib/apt/lists/*
# bash: default shell for the bash tool
# git: the agent operates on repos via bash
# ripgrep: backs the `grep` tool (shipping it avoids a runtime GitHub download)
# ca-certificates: HTTPS to the Azure endpoint

COPY --from=builder /tmp/earendil-works-pi-coding-agent-*.tgz /tmp/pi.tgz
RUN npm install -g --ignore-scripts /tmp/pi.tgz && rm /tmp/pi.tgz
# installs `pi` on PATH (bin -> dist/bundle/cli.js) from the locally-built tarball, using its
# bundled npm-shrinkwrap.json. --ignore-scripts per repo policy.

# Bake the Azure provider config into the default agent dir (~/.pi/agent/models.json).
# The apiKey is "$AZURE_API_KEY" and resolves from the container env at runtime,
# so the key is injected per `docker run` with `-e AZURE_API_KEY` — never baked in.
RUN mkdir -p /root/.pi/agent
COPY docker-pi/models.json /root/.pi/agent/models.json

WORKDIR /workspace
ENTRYPOINT ["pi"]
CMD ["--mode", "rpc", "--no-extensions", "--no-session", "--model", "azure-anthropic/claude-opus-4-6"]
