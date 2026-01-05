# syntax=docker/dockerfile:1

# ============ DEVELOPMENT ============
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm i

FROM node:20-alpine AS dev
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . ./
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ============ PRODUCTION BUILD ============
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . ./
RUN npm run build

# ============ PRODUCTION SERVE ============
FROM nginx:alpine AS prod
# Copy built static files
COPY --from=build /app/dist /usr/share/nginx/html
# Copy custom nginx config for SPA routing
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
