FROM node:24-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

FROM base AS build
WORKDIR /app
COPY . /app

RUN corepack enable
# We add ffmpeg here just in case the build needs to probe anything
RUN apk add --no-cache python3 alpine-sdk ffmpeg

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --prod --frozen-lockfile

RUN pnpm deploy --filter=@imput/cobalt-api --prod /prod/api

FROM base AS api
WORKDIR /app

# Install ffmpeg in the final image - crucial for fixing 'moov atom' issues
RUN apk add --no-cache ffmpeg

COPY --from=build --chown=node:node /prod/api /app
COPY --from=build --chown=node:node /app/.git /app/.git
COPY --chown=node:node cookies.txt /app/cookies.txt

USER node

EXPOSE 9000
CMD [ "node", "src/cobalt" ]
