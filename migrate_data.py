import argparse
import logging
import os
import sqlite3

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
load_dotenv()

TABLES_TO_MIGRATE = [
    "users", "daily_quotes", "faq_dataset", "messages", "archived_messages",
    "mood_log", "peer_messages", "ratings", "admin_logs", "group_rooms",
    "group_room_members", "group_messages", "user_settings",
    "used_reset_tokens", "password_reset_codes",
]


def _columns_sqlite(cursor, table):
    cursor.execute(f'PRAGMA table_info("{table}")')
    return [row[1] for row in cursor.fetchall()]


def _columns_postgres(cursor, table):
    cursor.execute(
        """SELECT column_name FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = %s
           ORDER BY ordinal_position""",
        (table,),
    )
    return [row[0] for row in cursor.fetchall()]


def _table_exists_postgres(cursor, table):
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
    return cursor.fetchone()[0] is not None


def _has_rows_postgres(cursor, table):
    cursor.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {} LIMIT 1)").format(sql.Identifier(table)))
    return cursor.fetchone()[0]


def _quoted_list(values):
    return sql.SQL(", ").join(sql.Identifier(value) for value in values)


def migrate_data(reset_destination=False, assume_yes=False):
    """Copy local SQLite data to a new Render PostgreSQL database safely."""
    sqlite_path = os.environ.get("MENTALHEALTHWEB_DB", "database.db")
    postgres_url = os.environ.get("DATABASE_URL")
    if not postgres_url:
        logging.error("DATABASE_URL is missing. Set the new Render PostgreSQL URL first.")
        return False
    if not os.path.exists(sqlite_path):
        logging.error("SQLite source not found: %s", os.path.abspath(sqlite_path))
        return False

    sqlite_conn = postgres_conn = None
    try:
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        source_cursor = sqlite_conn.cursor()
        postgres_conn = psycopg2.connect(postgres_url)
        dest_cursor = postgres_conn.cursor()

        missing_source = [t for t in TABLES_TO_MIGRATE if not _columns_sqlite(source_cursor, t)]
        if missing_source:
            raise RuntimeError("SQLite is missing tables: " + ", ".join(missing_source))
        missing_dest = [t for t in TABLES_TO_MIGRATE if not _table_exists_postgres(dest_cursor, t)]
        if missing_dest:
            raise RuntimeError("Deploy once to initialize PostgreSQL tables: " + ", ".join(missing_dest))

        non_empty = [t for t in TABLES_TO_MIGRATE if _has_rows_postgres(dest_cursor, t)]
        if non_empty and not reset_destination:
            raise RuntimeError("Destination already has data in: " + ", ".join(non_empty) +
                               ". Use --reset-destination only for a replacement database.")

        if not assume_yes:
            action = "clear and copy" if reset_destination else "copy"
            if input(f"Type YES to {action} SQLite -> PostgreSQL: ").strip().upper() != "YES":
                logging.info("Migration cancelled.")
                return False

        if reset_destination:
            logging.warning("Deleting all rows in destination tables before migration.")
            dest_cursor.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                _quoted_list(TABLES_TO_MIGRATE)))

        for table in TABLES_TO_MIGRATE:
            source_columns = _columns_sqlite(source_cursor, table)
            destination_columns = set(_columns_postgres(dest_cursor, table))
            missing_columns = [c for c in source_columns if c not in destination_columns]
            if missing_columns:
                raise RuntimeError(f"{table} is missing PostgreSQL columns: " + ", ".join(missing_columns))

            source_cursor.execute(sql.SQL("SELECT {} FROM {}").format(
                _quoted_list(source_columns), sql.Identifier(table)))
            rows = [tuple(row) for row in source_cursor.fetchall()]
            if not rows:
                logging.info("%s: no rows to copy", table)
                continue

            insert_query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(table), _quoted_list(source_columns),
                sql.SQL(", ").join(sql.Placeholder() for _ in source_columns))
            dest_cursor.executemany(insert_query, rows)
            logging.info("%s: copied %d rows", table, len(rows))

        postgres_conn.commit()
        logging.info("Migration completed successfully.")
        return True
    except Exception as exc:
        if postgres_conn is not None:
            postgres_conn.rollback()
        logging.error("Migration failed; destination transaction rolled back: %s", exc)
        return False
    finally:
        if sqlite_conn is not None:
            sqlite_conn.close()
        if postgres_conn is not None:
            postgres_conn.close()
        logging.info("Database connections closed.")


def main():
    parser = argparse.ArgumentParser(description="Migrate local SQLite data to Render PostgreSQL.")
    parser.add_argument("--reset-destination", action="store_true",
                        help="Delete destination rows before copying.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the interactive confirmation.")
    args = parser.parse_args()
    migrate_data(reset_destination=args.reset_destination, assume_yes=args.yes)


if __name__ == "__main__":
    main()
