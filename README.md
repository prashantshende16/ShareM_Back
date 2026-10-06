# F&O Market Screenshot Analysis API (Backend)

Python FastAPI backend for F&O market screenshot analysis with AI vision, technical analysis, and probabilistic scenario modeling.

## Tech Stack
- Python 3.11+ / 3.8+
- FastAPI & Uvicorn
- SQLAlchemy & Alembic
- SQLite / PostgreSQL
- OpenAI / Gemini / Claude / Mock Vision Providers

## Setup & Running

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Running Tests
```bash
pytest tests/ -v
```
