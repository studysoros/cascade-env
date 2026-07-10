FROM python:3.12-slim
WORKDIR /workspace
RUN pip install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    sqlalchemy \
    "psycopg[binary]" \
    redis \
    pyyaml \
    httpx \
    pytest
# Runtime code is bind-mounted from the episode workspace.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
