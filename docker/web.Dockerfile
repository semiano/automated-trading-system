FROM node:20-alpine

WORKDIR /app/web

COPY web/package*.json ./
RUN npm install

COPY web/ ./

RUN chown -R node:node /app
USER node

ENV VITE_API_BASE_URL=http://localhost:8000/api/v1

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
