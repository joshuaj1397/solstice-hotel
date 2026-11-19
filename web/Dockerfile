# Solstice web (Next.js 16, output: "standalone"). Build context = web/:
#   docker build -t solstice/web web
# Secrets (service token, session secret) are fetched from Vault at runtime via AppRole;
# nothing secret is baked into the image.

FROM node:22-alpine AS deps
WORKDIR /app
RUN apk add --no-cache libc6-compat
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 solstice && adduser -S -u 10001 -G solstice solstice
COPY --from=build --chown=solstice:solstice /app/public ./public
COPY --from=build --chown=solstice:solstice /app/.next/standalone ./
COPY --from=build --chown=solstice:solstice /app/.next/static ./.next/static
USER solstice
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
