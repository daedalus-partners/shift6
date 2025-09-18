# syntax=docker/dockerfile:1
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm i

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . ./
RUN npm run build || true

FROM node:20-alpine AS dev
WORKDIR /app
COPY . ./
RUN npm i
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
