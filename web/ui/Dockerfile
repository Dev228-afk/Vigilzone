# ── Stage 1: Build the React UI ──────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app
COPY web/ui/package.json web/ui/package-lock.json ./
RUN npm ci

COPY web/ui/ .
RUN npm run build

# ── Stage 2: Serve via Nginx ─────────────────────────────────
FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our custom nginx config
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf

# Copy Vite build output (dist/public/) to nginx html root
COPY --from=builder /app/dist/public /usr/share/nginx/html

EXPOSE 8085
CMD ["nginx", "-g", "daemon off;"]
