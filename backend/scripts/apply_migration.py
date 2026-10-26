"""Apply a SQL migration file to the Supabase Postgres database.

Tries the direct connection first, then common pooler hosts/regions, using
DB_PASSWORD and the project ref from SUPABASE_URL. Usage:

    python backend/scripts/apply_migration.py backend/database/phase_1_4.sql
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env")


def _project_ref(supabase_url: str) -> str:
    host = urlparse(supabase_url).hostname or ""
    return host.split(".")[0]


def main() -> int:
    _load_env()
    if len(sys.argv) < 2:
        print("Usage: apply_migration.py <path-to-sql>", file=sys.stderr)
        return 2
    sql_path = Path(sys.argv[1])
    if not sql_path.is_absolute():
        sql_path = Path.cwd() / sql_path
    sql = sql_path.read_text(encoding="utf-8")

    url = os.getenv("SUPABASE_URL", "").strip()
    password = os.getenv("DB_PASSWORD", "").strip()
    ref = _project_ref(url)
    if not ref or not password:
        print("Need SUPABASE_URL and DB_PASSWORD.", file=sys.stderr)
        return 1

    import psycopg2

    regions = ["ap-south-1", "ap-southeast-1", "us-east-1", "us-west-1", "eu-central-1"]
    candidates = [
        # (host, port, user)
        (f"db.{ref}.supabase.co", 5432, "postgres"),
    ]
    for r in regions:
        candidates.append((f"aws-0-{r}.pooler.supabase.com", 6543, f"postgres.{ref}"))
        candidates.append((f"aws-0-{r}.pooler.supabase.com", 5432, f"postgres.{ref}"))

    last_err = None
    for host, port, user in candidates:
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                dbname="postgres",
                connect_timeout=8,
                sslmode="require",
            )
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.close()
            print(f"Migration applied via {host}:{port} as {user}.")
            return 0
        except Exception as exc:  # try the next candidate
            last_err = f"{host}:{port} as {user} -> {str(exc)[:120]}"
            continue

    print(f"Could not connect. Last error: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
