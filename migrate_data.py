import os
import sqlite3
import psycopg2
from dotenv import load_dotenv
import logging

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load environment variables from .env file
load_dotenv()

# --- Source and Destination Databases ---
SQLITE_DB_PATH = os.environ.get("MENTALHEALTHWEB_DB", "database.db")
POSTGRES_DB_URL = os.environ.get("DATABASE_URL")

# --- List of tables to migrate ---
# Order matters if you have foreign keys. Start with tables that don't depend on others.
TABLES_TO_MIGRATE = [
    "users",
    "daily_quotes",
    "faq_dataset",
    "messages",
    "archived_messages",
    "mood_log",
    "peer_messages",
    "ratings",
    "admin_logs",
]

def migrate_data():
    """
    Extracts data from a local SQLite database and loads it into a production PostgreSQL database.
    """
    if not POSTGRES_DB_URL:
        logging.error("DATABASE_URL not found in environment variables. Please add it to your .env file.")
        return

    if not os.path.exists(SQLITE_DB_PATH):
        logging.error(f"SQLite database file not found at '{SQLITE_DB_PATH}'.")
        return

    # --- Safety Check ---
    logging.warning("!!! WARNING: This script will TRUNCATE (delete all data from) the tables in the destination database before migrating.")
    logging.warning(f"Destination Host: {psycopg2.connect(POSTGRES_DB_URL).get_dsn_parameters()['host']}")
    
    confirmation = input("Are you sure you want to proceed? (yes/no): ")
    if confirmation.lower() != 'yes':
        logging.info("Migration cancelled by user.")
        return
    
    logging.info("User confirmed. Starting migration process...")

    try:
        # Connect to both databases
        sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()

        postgres_conn = psycopg2.connect(POSTGRES_DB_URL)
        postgres_cursor = postgres_conn.cursor()

        logging.info("Successfully connected to both SQLite and PostgreSQL databases.")

        for table_name in TABLES_TO_MIGRATE:
            logging.info(f"--- Starting migration for table: {table_name} ---")

            # 1. Clear the table in PostgreSQL to avoid duplicates
            logging.info(f"Truncating table '{table_name}' in PostgreSQL...")
            # Using TRUNCATE ... RESTART IDENTITY to also reset auto-incrementing primary keys
            postgres_cursor.execute(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE;')

            # 2. Fetch all data from the SQLite table
            logging.info(f"Fetching data from '{table_name}' in SQLite...")
            sqlite_cursor.execute(f"SELECT * FROM {table_name}")
            rows = sqlite_cursor.fetchall()

            if not rows:
                logging.warning(f"No data found in SQLite table '{table_name}'. Skipping.")
                continue

            # 3. Get column names from the SQLite table
            column_names = [description[0] for description in sqlite_cursor.description]
            
            # 4. Prepare the INSERT statement for PostgreSQL
            # Using %s placeholders for psycopg2
            placeholders = ", ".join(["%s"] * len(column_names))
            # Enclosing column names in double quotes to handle reserved keywords
            quoted_columns = ", ".join([f'"{col}"' for col in column_names])
            
            insert_query = f"INSERT INTO {table_name} ({quoted_columns}) VALUES ({placeholders})"

            # 5. Insert data into PostgreSQL
            logging.info(f"Inserting {len(rows)} rows into PostgreSQL table '{table_name}'...")
            
            # Convert each sqlite3.Row object to a tuple for insertion
            data_to_insert = [tuple(row) for row in rows]
            
            postgres_cursor.executemany(insert_query, data_to_insert)
            logging.info(f"Successfully inserted data into '{table_name}'.")

        # Commit all changes to the PostgreSQL database
        postgres_conn.commit()
        logging.info("\n✅ All tables migrated successfully! Changes have been committed.")

    except (sqlite3.Error, psycopg2.Error) as e:
        logging.error(f"A database error occurred: {e}")
        if 'postgres_conn' in locals() and postgres_conn:
            postgres_conn.rollback()
            logging.warning("PostgreSQL transaction has been rolled back.")
    finally:
        # Close all connections
        if 'sqlite_conn' in locals() and sqlite_conn:
            sqlite_conn.close()
        if 'postgres_conn' in locals() and postgres_conn:
            postgres_conn.close()
        logging.info("Database connections closed.")

if __name__ == "__main__":
    migrate_data()