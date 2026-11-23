"""Optional: create the PostgreSQL database named in DATABASE_URL (SQLite needs no setup).

Set DATABASE_URL in .env first, e.g.
    DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:5432/travel_db
"""
import sys

from sqlalchemy.engine import make_url

from config import Config


def main():
    url = make_url(Config.SQLALCHEMY_DATABASE_URI)
    if url.get_backend_name() != "postgresql":
        print("DATABASE_URL is not set to PostgreSQL: the app uses SQLite and creates it automatically.")
        return

    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    target = url.database
    try:
        con = psycopg2.connect(
            dbname="postgres", user=url.username, password=url.password,
            host=url.host or "127.0.0.1", port=url.port or 5432,
        )
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with con.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,))
            if cur.fetchone():
                print(f"Database '{target}' already exists.")
            else:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
                print(f"Database '{target}' created.")
        con.close()
    except Exception as exc:
        sys.exit(f"Could not set up the database: {exc}\nCheck the credentials in DATABASE_URL.")


if __name__ == "__main__":
    main()
