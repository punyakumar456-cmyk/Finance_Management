from backend.app import app, init_db
import os


if os.environ.get("FINOVA_DB"):
    init_db()


if __name__ == '__main__':
    init_db()
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

