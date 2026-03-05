FROM node:20-slim AS builder
WORKDIR /build
COPY package.json package-lock.json* ./
RUN npm ci --only=production

FROM node:20-slim
RUN groupadd -f -g 1000 mcpuser && \
    useradd -o -u 1000 -g 1000 -m -s /bin/bash mcpuser 2>/dev/null || true

WORKDIR /app

COPY --from=builder --chown=mcpuser:mcpuser /build/node_modules ./node_modules
COPY --chown=mcpuser:mcpuser package.json ./
COPY --chown=mcpuser:mcpuser tools.config.json ./
COPY --chown=mcpuser:mcpuser src/ ./src/

USER mcpuser

ENV MCP_TRANSPORT=http
ENV MCP_HTTP_PORT=8000
ENV MCP_HTTP_HOST=0.0.0.0
ENV NODE_ENV=production

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "const h=require('http');h.get('http://localhost:8000/health',(r)=>{process.exit(r.statusCode===200?0:1)}).on('error',()=>process.exit(1))"

CMD ["node", "src/index.js"]
