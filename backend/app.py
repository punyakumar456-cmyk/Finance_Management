from __future__ import annotations

import base64
import calendar
import io
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean

from flask import Flask, jsonify, render_template, request

try:
    import pytesseract
    from PIL import Image
except Exception:  # OCR is optional so the app still runs on a college laptop.
    pytesseract = None
    Image = None

try:
    import numpy as np
    from sklearn.linear_model import LinearRegression
except Exception:
    np = None
    LinearRegression = None


APP_NAME = "Finova AI"
DB_PATH = Path(
    os.environ.get(
        "FINOVA_DB",
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FinovaAI" / "finova.db",
    )
)

app = Flask(__name__, template_folder="../frontend/templates", static_folder="../frontend/static")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


CATEGORIES = ["Food", "Travel", "Bills", "Shopping", "Entertainment", "Health", "Investments"]
PAYMENT_MODES = ["UPI", "Card", "Cash", "Net Banking", "Wallet"]

KEYWORDS = {
    "Food": ["swiggy", "zomato", "restaurant", "pizza", "burger", "cafe", "coffee", "food", "lunch", "dinner"],
    "Travel": ["uber", "ola", "metro", "train", "flight", "bus", "petrol", "diesel", "taxi", "travel"],
    "Bills": ["bill", "electricity", "wifi", "internet", "rent", "recharge", "subscription", "netflix", "spotify"],
    "Shopping": ["amazon", "flipkart", "myntra", "order", "mall", "clothes", "shoes", "shopping"],
    "Entertainment": ["movie", "cinema", "game", "concert", "party", "prime", "hotstar"],
    "Health": ["doctor", "medicine", "pharmacy", "hospital", "gym", "health", "medical"],
    "Investments": ["sip", "mutual", "stock", "etf", "zerodha", "groww", "investment"],
}

MOCK_STOCKS = [
    {"symbol": "NIFTYBEES", "name": "Nippon India Nifty 50 ETF", "risk": "Low", "growth": "8-11%", "sector": "Index ETF", "insight": "Broad market exposure for beginners.", "spark": [34, 35, 36, 36, 38, 39, 41]},
    {"symbol": "JUNIORBEES", "name": "Nifty Next 50 ETF", "risk": "Medium", "growth": "10-14%", "sector": "Index ETF", "insight": "Higher growth with more volatility.", "spark": [22, 23, 22, 24, 26, 25, 28]},
    {"symbol": "HDFCBANK", "name": "HDFC Bank", "risk": "Medium", "growth": "9-13%", "sector": "Banking", "insight": "Large-cap banking leader with stable fundamentals.", "spark": [54, 53, 55, 56, 58, 57, 60]},
    {"symbol": "INFY", "name": "Infosys", "risk": "Medium", "growth": "8-12%", "sector": "IT Services", "insight": "Export-focused technology blue chip.", "spark": [41, 42, 43, 42, 44, 46, 45]},
    {"symbol": "GOLDBEES", "name": "Gold ETF", "risk": "Low", "growth": "6-9%", "sector": "Commodity ETF", "insight": "Useful hedge during uncertain markets.", "spark": [18, 19, 19, 20, 21, 21, 22]},
]

YF_SYMBOLS = {
    "NIFTYBEES": "NIFTYBEES.NS",
    "JUNIORBEES": "JUNIORBEES.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "INFY": "INFY.NS",
    "GOLDBEES": "GOLDBEES.NS",
}

_QUOTE_CACHE: dict[str, object] = {"at": 0.0, "data": []}
_QUOTE_CACHE_TTL_S = 60.0


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                payment_mode TEXT NOT NULL,
                date TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS months (
                month TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS planner (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                income REAL DEFAULT 0,
                savings_goal REAL DEFAULT 0,
                budget REAL DEFAULT 0
            )
            """
        )
        con.execute("INSERT OR IGNORE INTO planner (id) VALUES (1)")
        ensure_month_row(con, date.today().strftime("%Y-%m"))


def ensure_month_row(con: sqlite3.Connection, month: str) -> None:
    con.execute(
        "INSERT OR IGNORE INTO months (month, created_at) VALUES (?, ?)",
        (month, datetime.utcnow().isoformat()),
    )


def rows(month: str | None = None) -> list[dict]:
    with db() as con:
        if month:
            data = con.execute(
                "SELECT * FROM transactions WHERE date LIKE ? ORDER BY date DESC, id DESC",
                (f"{month}-%",),
            ).fetchall()
        else:
            data = con.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC").fetchall()
    return [dict(r) for r in data]


def planner() -> dict:
    with db() as con:
        p = dict(con.execute("SELECT income, savings_goal, budget FROM planner WHERE id = 1").fetchone())
    return p


def classify(text: str) -> str:
    text_l = text.lower()
    scores = {cat: sum(1 for word in words if word in text_l) for cat, words in KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else "Shopping"


def amount_from_text(text: str) -> float:
    match = re.search(r"(?:rs\.?|inr)?\s*(\d+(?:,\d{3})*(?:\.\d+)?)", text.lower())
    return float(match.group(1).replace(",", "")) if match else 0


def add_tx(amount: float, category: str, payment_mode: str, tx_date: str, notes: str) -> dict:
    with db() as con:
        month = str(tx_date)[:7]
        if re.match(r"^\d{4}-\d{2}$", month):
            ensure_month_row(con, month)
        cur = con.execute(
            "INSERT INTO transactions (amount, category, payment_mode, date, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (amount, category, payment_mode, tx_date, notes, datetime.utcnow().isoformat()),
        )
        tx_id = cur.lastrowid
        row = con.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    return dict(row)


def category_totals(transactions: list[dict]) -> dict:
    totals = defaultdict(float)
    for t in transactions:
        totals[t["category"]] += float(t["amount"])
    return {c: round(totals[c], 2) for c in CATEGORIES}


def daily_totals(transactions: list[dict]) -> dict:
    totals = defaultdict(float)
    for t in transactions:
        totals[t["date"]] += float(t["amount"])
    return dict(sorted(totals.items()))


def predict_month_end(transactions: list[dict], budget: float) -> dict:
    if not transactions:
        return {"prediction": 0, "overflow": 0, "trend": []}

    today = date.today()
    month_rows = [t for t in transactions if t["date"].startswith(today.strftime("%Y-%m"))]
    if not month_rows:
        month_rows = transactions

    days = []
    cumulative = []
    running = 0.0
    for d, total in sorted(daily_totals(month_rows).items()):
        running += total
        try:
            days.append(datetime.strptime(d, "%Y-%m-%d").date().day)
        except ValueError:
            days.append(len(days) + 1)
        cumulative.append(running)

    month_days = calendar.monthrange(today.year, today.month)[1]
    if LinearRegression and np and len(days) >= 2:
        model = LinearRegression().fit(np.array(days).reshape(-1, 1), np.array(cumulative))
        prediction = max(float(model.predict(np.array([[month_days]]))[0]), cumulative[-1])
        trend = [max(0, round(float(model.predict(np.array([[d]]))[0]), 0)) for d in range(1, month_days + 1, 5)]
    else:
        avg_daily = cumulative[-1] / max(max(days), 1)
        prediction = avg_daily * month_days
        trend = [round(avg_daily * d, 0) for d in range(1, month_days + 1, 5)]

    overflow = 0 if budget <= 0 else max(0, min(99, round((prediction - budget) / budget * 100)))
    return {"prediction": round(prediction, 2), "overflow": overflow, "trend": trend}


def investment_plan(investable: float, savings_goal: float) -> dict:
    if investable <= 0:
        return {
            "investable": 0,
            "cash_buffer": round(max(savings_goal, 0), 2),
            "headline": "No extra investment room yet",
            "allocation": [],
            "note": "Set income, budget, and savings goal first. The planner will suggest stocks only after your emergency/savings goal is protected.",
        }

    if investable < 1000:
        allocation = [("Emergency buffer", 100)]
        headline = "Build cash buffer first"
        note = "The extra saving room is small, so keep it liquid instead of forcing a stock purchase."
    elif investable < 5000:
        allocation = [("NIFTYBEES", 70), ("GOLDBEES", 30)]
        headline = "Starter ETF split"
        note = "A simple index-plus-gold split keeps risk controlled while you build consistency."
    else:
        allocation = [("NIFTYBEES", 45), ("JUNIORBEES", 20), ("HDFCBANK", 15), ("INFY", 10), ("GOLDBEES", 10)]
        headline = "Balanced stock market basket"
        note = "Use this as an educational basket idea, not live financial advice. Review risk before investing real money."

    return {
        "investable": round(investable, 2),
        "cash_buffer": round(max(savings_goal, 0), 2),
        "headline": headline,
        "allocation": [
            {"label": name, "percent": pct, "amount": round(investable * pct / 100, 2)}
            for name, pct in allocation
        ],
        "note": note,
    }


def _to_float(v: object) -> float | None:
    try:
        return float(v)
    except Exception:
        return None


def live_quotes() -> list[dict]:
    """
    Best-effort live market quotes for the demo symbols.
    Cached to keep the UI responsive and avoid repeated requests.
    """
    now = datetime.utcnow().timestamp()
    cached_at = float(_QUOTE_CACHE.get("at") or 0.0)
    if (now - cached_at) < _QUOTE_CACHE_TTL_S and isinstance(_QUOTE_CACHE.get("data"), list):
        return _QUOTE_CACHE["data"]  # type: ignore[return-value]

    try:
        import yfinance as yf  # type: ignore
    except Exception:
        _QUOTE_CACHE["at"] = now
        _QUOTE_CACHE["data"] = []
        return []

    out: list[dict] = []
    try:
        tickers = yf.Tickers(" ".join(YF_SYMBOLS.values()))
        for st in MOCK_STOCKS:
            sym = st["symbol"]
            yf_sym = YF_SYMBOLS.get(sym)
            q: dict = dict(st)
            q["quote"] = None
            q["as_of"] = None
            if yf_sym:
                t = tickers.tickers.get(yf_sym)
                info = getattr(t, "fast_info", None)
                last = _to_float(getattr(info, "last_price", None)) if info else None
                prev = _to_float(getattr(info, "previous_close", None)) if info else None
                if last is not None:
                    change_pct = None
                    if prev not in (None, 0):
                        change_pct = round(((last - prev) / prev) * 100, 2)
                    q["quote"] = {
                        "price": round(last, 2),
                        "change_percent": change_pct,
                        "currency": getattr(info, "currency", None) if info else None,
                    }
                    q["as_of"] = datetime.utcnow().isoformat() + "Z"
            out.append(q)
    except Exception:
        out = []

    _QUOTE_CACHE["at"] = now
    _QUOTE_CACHE["data"] = out
    return out


def insights(transactions: list[dict], p: dict) -> dict:
    total = sum(float(t["amount"]) for t in transactions)
    cats = category_totals(transactions)
    top_cat = max(cats, key=cats.get) if transactions else "-"
    income = float(p["income"])
    budget = float(p["budget"])
    savings_goal = float(p["savings_goal"])
    spend_limit = max(0, min(float(p["budget"]) or income, income - savings_goal if income else float(p["budget"])))
    projected_savings = max(0, income - total)
    savings_progress = 100 if savings_goal <= 0 and income > 0 else min(100, projected_savings / max(savings_goal, 1) * 100)
    budget_score = 100 if budget <= 0 else max(0, 100 - (total / budget * 100))
    health = 0 if not transactions and income == 0 and budget == 0 else max(0, min(100, round((budget_score * 0.55) + (savings_progress * 0.45))))
    prediction = predict_month_end(transactions, budget)

    suggestions = []
    if not transactions:
        suggestions.append("Add your first real expense to unlock personalized insights and predictions.")
    if total and cats["Food"] > total * 0.22:
        suggestions.append("Food delivery is taking a large share. A 20% cut here could create instant savings.")
    if cats["Entertainment"] > 2000:
        suggestions.append("Review entertainment subscriptions. Canceling low-use plans can save about Rs. 2,500/month.")
    if prediction["overflow"] > 0:
        suggestions.append(f"Budget overflow probability is elevated at {prediction['overflow']}%. Slow discretionary spending this week.")
    if projected_savings > savings_goal:
        suggestions.append(f"You can safely invest around Rs. {int(min(projected_savings - savings_goal, 15000)):,} this month.")
    if income > 0 and budget <= 0:
        suggestions.append("Add a monthly budget so the planner can calculate overflow risk accurately.")
    if income > 0 and savings_goal <= 0:
        suggestions.append("Add a savings goal before investing so the plan protects your cash buffer first.")
    if not suggestions:
        suggestions.append("Your spending pattern looks stable. Keep auto-saving before discretionary expenses.")

    fraud = []
    by_cat = defaultdict(list)
    for t in transactions:
        by_cat[t["category"]].append(float(t["amount"]))
    for t in transactions:
        cat_avg = mean(by_cat[t["category"]]) if by_cat[t["category"]] else 0
        if cat_avg and float(t["amount"]) > cat_avg * 2.2 and float(t["amount"]) > 2000:
            fraud.append(f"Rs. {int(t['amount']):,} in {t['category']} is unusually higher than your average.")

    investable = max(0, projected_savings - savings_goal)
    plan = investment_plan(investable, savings_goal)
    stock_count = 5 if investable >= 5000 else (2 if investable >= 1000 else 0)
    quotes = live_quotes()
    quote_by_symbol = {q["symbol"]: q for q in quotes} if quotes else {}
    return {
        "total": round(total, 2),
        "top_category": top_cat,
        "category_totals": cats,
        "daily_totals": daily_totals(transactions),
        "recommended_limit": round(spend_limit, 2),
        "safe_savings": round(projected_savings, 2),
        "health": health,
        "risk": prediction["overflow"],
        "prediction": prediction,
        "suggestions": suggestions,
        "fraud": fraud[:3],
        "stocks": [(quote_by_symbol.get(s["symbol"]) or s) for s in MOCK_STOCKS[:stock_count]],
        "market_ticker": [(quote_by_symbol.get(s["symbol"]) or s) for s in MOCK_STOCKS],
        "investment_plan": plan,
        "planner_summary": {
            "income": round(income, 2),
            "budget": round(budget, 2),
            "savings_goal": round(savings_goal, 2),
            "remaining_budget": round(max(0, budget - total), 2) if budget else 0,
            "spend_limit": round(spend_limit, 2),
        },
        "heatmap": [round((i * 17 + total) % 100) for i in range(35)],
    }


def answer_question(question: str, transactions: list[dict], p: dict) -> str:
    q = question.lower()
    ai = insights(transactions, p)
    cats = ai["category_totals"]
    if not transactions:
        return "I do not have any saved transactions yet. Add a real expense first, then I can analyze your categories, risk, savings, and investment room."
    if "most" in q or "highest" in q:
        return f"You spent the most on {ai['top_category']}: Rs. {int(cats[ai['top_category']]):,}. That is the biggest optimization area."
    if "invest" in q:
        plan = ai["investment_plan"]
        split = ", ".join(f"{a['label']} {a['percent']}%" for a in plan["allocation"]) or plan["note"]
        return f"Based on your current entries, investable room is about Rs. {int(plan['investable']):,}. Suggested split: {split}."
    for cat in CATEGORIES:
        if cat.lower() in q:
            return f"Your {cat} expenses are Rs. {int(cats[cat]):,}. I found {sum(1 for t in transactions if t['category'] == cat)} transactions in that category."
    if "save" in q or "saving" in q:
        return f"Projected safe savings are Rs. {int(ai['safe_savings']):,}. {ai['suggestions'][0]}"
    if "risk" in q or "budget" in q:
        return f"Your overspending risk is {ai['risk']}%, with predicted month-end expenses of Rs. {int(ai['prediction']['prediction']):,}."
    return f"Finova AI sees Rs. {int(ai['total']):,} tracked spend, a health score of {ai['health']}/100, and recommends: {ai['suggestions'][0]}"


def months_index() -> list[dict]:
    with db() as con:
        ensure_month_row(con, date.today().strftime("%Y-%m"))
        months = [r["month"] for r in con.execute("SELECT month FROM months ORDER BY month DESC").fetchall()]
        totals = {
            r["month"]: {"month": r["month"], "total": round(float(r["total"] or 0), 2), "count": int(r["count"] or 0)}
            for r in con.execute(
                "SELECT substr(date,1,7) AS month, SUM(amount) AS total, COUNT(*) AS count FROM transactions GROUP BY substr(date,1,7)"
            ).fetchall()
        }
    out = []
    for m in months:
        out.append(totals.get(m) or {"month": m, "total": 0.0, "count": 0})
    return out


def state_payload(month: str | None = None) -> dict:
    transactions = rows(month=month)
    p = planner()
    return {
        "transactions": transactions,
        "planner": p,
        "ai": insights(transactions, p),
        "months": months_index(),
        "active_month": month,
        "current_month": date.today().strftime("%Y-%m"),
    }


@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES, modes=PAYMENT_MODES)


@app.get("/api/state")
def state():
    month = request.args.get("month")
    if month and not re.match(r"^\d{4}-\d{2}$", month):
        return jsonify({"error": "Invalid month. Use YYYY-MM."}), 400
    return jsonify(state_payload(month=month))


@app.get("/api/months")
def months():
    return jsonify({"months": months_index(), "current": date.today().strftime("%Y-%m")})


@app.post("/api/months/new")
def months_new():
    month = request.get_json(force=True).get("month") if request.data else None
    if not month:
        month = date.today().strftime("%Y-%m")
    if not re.match(r"^\d{4}-\d{2}$", str(month)):
        return jsonify({"error": "Invalid month. Use YYYY-MM."}), 400
    with db() as con:
        ensure_month_row(con, str(month))
    return jsonify({"ok": True, "months": months_index(), "current": date.today().strftime("%Y-%m")})


@app.get("/api/quotes")
def quotes():
    return jsonify({"quotes": live_quotes(), "as_of": datetime.utcnow().isoformat() + "Z"})


@app.post("/api/expense")
def expense():
    data = request.get_json(force=True)
    category = data.get("category") or classify(data.get("notes", ""))
    tx = add_tx(
        float(data.get("amount") or 0),
        category,
        data.get("payment_mode") or "UPI",
        data.get("date") or date.today().isoformat(),
        data.get("notes", ""),
    )
    return jsonify({"transaction": tx, "state": state_payload()})


@app.post("/api/quick")
def quick():
    text = request.get_json(force=True).get("text", "")
    amount = amount_from_text(text)
    category = classify(text)
    if amount <= 0:
        return jsonify({"error": "Please include an amount, for example: Swiggy 450"}), 400
    tx = add_tx(amount, category, "UPI", date.today().isoformat(), text)
    return jsonify({"transaction": tx, "category": category, "state": state_payload()})


@app.delete("/api/expense/<int:tx_id>")
def delete_expense(tx_id: int):
    with db() as con:
        con.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
    return jsonify(state_payload())


@app.post("/api/clear")
def clear_expenses():
    with db() as con:
        con.execute("DELETE FROM transactions")
    return jsonify(state_payload())


@app.post("/api/planner")
def update_planner():
    data = request.get_json(force=True)
    with db() as con:
        con.execute(
            "UPDATE planner SET income = ?, savings_goal = ?, budget = ? WHERE id = 1",
            (float(data.get("income") or 0), float(data.get("savings_goal") or 0), float(data.get("budget") or 0)),
        )
    return jsonify(state_payload())


@app.post("/api/scan")
def scan():
    if "receipt" not in request.files:
        return jsonify({"error": "Upload a receipt image first."}), 400
    file = request.files["receipt"]
    raw = file.read()
    text = ""
    if pytesseract and Image:
        try:
            text = pytesseract.image_to_string(Image.open(io.BytesIO(raw)))
        except Exception:
            text = ""
    if not text:
        text = file.filename.replace("_", " ")
    amount = amount_from_text(text) or 499
    category = classify(text)
    store = (text.strip().splitlines() or ["Scanned receipt"])[0][:70]
    tx = add_tx(amount, category, "Card", date.today().isoformat(), f"Receipt: {store}")
    preview = base64.b64encode(raw[:120000]).decode("utf-8")
    return jsonify({"transaction": tx, "ocr_text": text[:500], "preview": preview, "state": state_payload()})


@app.post("/api/chat")
def chat():
    question = request.get_json(force=True).get("message", "")
    return jsonify({"reply": answer_question(question, rows(), planner())})


@app.post("/api/report")
def report():
    transactions = rows()
    p = planner()
    ai = insights(transactions, p)
    stock_lines = "\n- ".join(f"{s['symbol']} ({s['risk']} risk): {s['insight']}" for s in ai["stocks"]) or "No stock ideas yet. Protect your savings goal first."
    allocation_lines = "\n- ".join(
        f"{a['label']}: {a['percent']}% (about Rs. {int(a['amount']):,})"
        for a in ai["investment_plan"]["allocation"]
    ) or ai["investment_plan"]["note"]
    report_text = (
        f"{APP_NAME} Monthly AI Report\n\n"
        f"Total tracked expenses: Rs. {int(ai['total']):,}\n"
        f"Financial health score: {ai['health']}/100\n"
        f"Predicted month-end expense: Rs. {int(ai['prediction']['prediction']):,}\n"
        f"Top spending category: {ai['top_category']}\n\n"
        "AI Recommendations:\n- " + "\n- ".join(ai["suggestions"]) + "\n\n"
        f"Investment room: Rs. {int(ai['investment_plan']['investable']):,}\n"
        "Suggested allocation:\n- " + allocation_lines + "\n\n"
        "Educational investment ideas:\n- " + stock_lines
    )
    return jsonify({"report": report_text})





if __name__ == "__main__":
    init_db()
    app.run(debug=True, use_reloader=False, host="127.0.0.1", port=int(os.environ.get("PORT", 5000)))

