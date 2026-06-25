FROM node:22-alpine AS build

WORKDIR /app
COPY package.json package-lock.json* vite.config.js .env.ports ./
COPY frontend ./frontend
RUN npm install
RUN VITE_API_BASE_URL=/api npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/frontend/dist /usr/share/nginx/html
EXPOSE 5206
