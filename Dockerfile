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

# 1. Copy the built API code
COPY --from=build --chown=node:node /prod/api /app

# 2. Copy the .git folder (Required for Cobalt's internal versioning)
COPY --from=build --chown=node:node /app/.git /app/.git

# 3. Copy cookies.txt and ensure permissions are set for the 'node' user
# Even if it's named .txt, it should contain the JSON structure we discussed
COPY --chown=node:node cookies.txt /app/cookies.txt

USER node

EXPOSE 9000

# The CMD remains the same, but your Environment Variables in Koyeb 
# will handle the 'android' backend logic.
CMD [ "node", "src/cobalt" ]
