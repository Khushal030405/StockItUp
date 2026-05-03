# StockItUp

Cloud-ready inventory management system built with Flask + PostgreSQL.

## Local Run

```bash
pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Default Login

```text
masteradmin / admin123
admin / admin123
employee / emp123
```

## Render

Use Render Web Service + Render PostgreSQL. Set `DATABASE_URL` if not using `render.yaml`.


## Render Notes

This project includes:

- `runtime.txt` → forces Python 3.11.9
- PostgreSQL SSL support for Supabase
- `/healthz` route for Render health checks

Use Supabase Session Pooler DATABASE_URL with port `6543`.
