# Dashboard image: build the React app, serve it with nginx (non-root) and proxy /api to the backend.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30-alpine
# Alpine publishes security fixes before the base image is rebuilt: install them at build time,
# then switch back to the image's unprivileged nginx user (uid 101)
USER root
RUN apk upgrade --no-cache
USER 101
ENV API_UPSTREAM=http://api:8000 \
    API_KEY=""
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
