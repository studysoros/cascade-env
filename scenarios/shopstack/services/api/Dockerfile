FROM python:3.12-slim
WORKDIR /workspace
RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy psycopg[binary] redis pyyaml httpx
# Runtime code is bind-mounted from episode workspace
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
