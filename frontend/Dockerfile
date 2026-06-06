###############################################################################
# Company Brain – Frontend (Next.js)
# Multi-stage, Alpine-based, non-root, production-hardened
###############################################################################

# ── Stage 1: Install dependencies ────────────────────────────────────────────
FROM node:22-alpine AS deps

RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts

# ── Stage 2: Build the Next.js application ───────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Enable standalone output for minimal final image
ENV NEXT_TELEMETRY_DISABLED=1
RUN npx next build

# ── Stage 3: Production runner ───────────────────────────────────────────────
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user & group
RUN addgroup --system --gid 1001 nextjs && \
    adduser  --system --uid 1001 nextjs

# Copy only the artifacts needed at runtime
COPY --from=builder /app/public                        ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static    ./.next/static

# Drop privileges
USER nextjs

EXPOSE 3000

ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

# Standalone server entrypoint created by `next build`
CMD ["node", "server.js"]
