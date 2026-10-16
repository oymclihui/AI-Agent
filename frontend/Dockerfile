FROM docker.m.daocloud.io/library/node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm config set strict-ssl false && npm ci

FROM docker.m.daocloud.io/library/node:20-alpine AS builder
WORKDIR /app
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM docker.m.daocloud.io/library/node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
EXPOSE 3000
CMD ["npm", "start"]
