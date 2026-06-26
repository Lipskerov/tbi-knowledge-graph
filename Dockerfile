FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY kb/ ./kb/
COPY scripts/ ./scripts/
COPY build_kb.py visualize_graph.py ./

# Materialize vendored frontend libs (vis-9.1.2, tom-select, bindings/utils.js)
# from the installed pyvis package — no network download. Served at /lib.
RUN python scripts/vendor_lib.py

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
