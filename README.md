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

## Deploy on Render

This app is ready for Render as a Python web service.

1. Push this repository to GitHub.
2. In Render, choose **New +** -> **Blueprint**.
3. Connect the repository and let Render read `render.yaml`.
4. Deploy the `finova-ai` service.

Render will run:

```bash
pip install -r requirements.txt
gunicorn app:app
```

The `render.yaml` file also creates a small persistent disk at `/var/data` and stores SQLite at `/var/data/finova.db`. Render persistent disks require a paid web service. For a free demo deployment, remove the `disk` block and set `FINOVA_DB=/tmp/finova.db`, but the data will reset on redeploys/restarts.

Netlify is not the best fit for this project as-is because the Flask API and SQLite database need a long-running Python server. To use Netlify, the frontend would need to be split into a static site and the backend deployed separately.

## Notes

- SQLite data is stored in `%LOCALAPPDATA%\FinovaAI\finova.db` by default to avoid OneDrive sync locks. Set `FINOVA_DB=finova.db` if you want the database in the project folder.
- The dashboard starts empty and updates from real user-entered transactions rather than seeded demo data.
- OCR works best when the Tesseract app is installed on the system. If it is not installed, receipt upload still works with a demo fallback.
- Stock suggestions are educational mock data and are not financial advice.
