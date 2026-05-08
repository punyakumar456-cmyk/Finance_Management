from backend.app import app, init_db


if __name__ == '__main__':
    import os

    init_db()
    app.run(debug=True, use_reloader=False, host='127.0.0.1', port=int(os.environ.get('PORT', 5000)))

