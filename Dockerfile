FROM node:24-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

FROM base AS build
WORKDIR /app
COPY . /app

RUN corepack enable
RUN apk add --no-cache python3 alpine-sdk

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --prod --frozen-lockfile

RUN pnpm deploy --filter=@imput/cobalt-api --prod /prod/api

FROM base AS api
WORKDIR /app

# 1. Copy the built API
COPY --from=build --chown=node:node /prod/api /app

# 2. Copy the .git folder
COPY --from=build --chown=node:node /app/.git /app/.git

# 3. FIX: Use a wildcard. This will copy any file starting with 'cookie' 
# and won't crash the build if the file is missing or named slightly differently.
COPY cookie* /app/

USER node

EXPOSE 9000
CMD [ "node", "src/cobalt" ]
