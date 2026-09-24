FROM node:22-alpine

WORKDIR /app

# The lockfile is copied so the install resolves the versions the project pinned.
COPY package.json package-lock.json ./
RUN npm install

COPY . .

# vite.config.ts sets server.host=0.0.0.0 and server.port=5174, so the dev server
# is reachable from outside the container on 5174.
EXPOSE 5174

CMD ["npm", "run", "dev"]
