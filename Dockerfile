FROM python:3.12-slim

RUN groupadd -f -g 1000 mcpuser && \
    useradd -o -u 1000 -g 1000 -m -s /bin/bash mcpuser 2>/dev/null || true

WORKDIR /app

COPY --chown=mcpuser:mcpuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=mcpuser:mcpuser tools.config.json .
COPY --chown=mcpuser:mcpuser src/ ./src/

USER mcpuser

ENV MCP_TRANSPORT=http
ENV MCP_HTTP_PORT=8000
ENV MCP_HTTP_HOST=0.0.0.0

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "src.main"]
