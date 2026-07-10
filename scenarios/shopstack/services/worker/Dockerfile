FROM python:3.12-slim
WORKDIR /workspace
RUN pip install --no-cache-dir sqlalchemy psycopg[binary] redis pyyaml
CMD ["python", "app/worker/handler.py"]
