FROM node:20-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS app
WORKDIR /app

RUN pip install poetry && poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-interaction --no-ansi

COPY . .
COPY --from=frontend-builder /frontend/dist ./frontend/dist

EXPOSE 8000
CMD ["uvicorn", "sol.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
