FROM python:3.12.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy model for NER-based entity extraction
RUN python -m spacy download en_core_web_md

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
