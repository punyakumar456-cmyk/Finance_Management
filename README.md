# Finova AI

Finova AI is a Flask-based personal finance tracker built for a college project. It provides a responsive desktop/mobile finance workspace, real SQLite-backed transactions, AI-style insights, prediction, OCR receipt upload, chatbot answers, charts, a 3D dashboard, and savings-based investment planning cards.

## Project structure

```text
app.py                       # Small launcher kept for the old run command
backend/app.py               # Flask routes, SQLite, planner, insights
frontend/templates/index.html # Dashboard UI
requirements.txt
```

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Notes

- SQLite data is stored in `%LOCALAPPDATA%\FinovaAI\finova.db` by default to avoid OneDrive sync locks. Set `FINOVA_DB=finova.db` if you want the database in the project folder.
- The dashboard starts empty and updates from real user-entered transactions rather than seeded demo data.
- OCR works best when the Tesseract app is installed on the system. If it is not installed, receipt upload still works with a demo fallback.
- Stock suggestions are educational mock data and are not financial advice.
