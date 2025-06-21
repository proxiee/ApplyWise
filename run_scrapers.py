import sqlite3
import pandas as pd
import json
import argparse
import os
from scrapers.linkedin_scraper import scrape_linkedin
from scrapers.indeed_scraper import scrape_indeed

def load_config(file_name="config.json"):
    with open(file_name) as f:
        return json.load(f)

def get_db_connection(config):
    db_path = config['app_settings']['db_path']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    return conn

def verify_and_create_db_schema(conn, table_name):
    """
    Verifies the database table has all necessary columns, creating the table
    and/or columns as needed. This makes the scraper script self-sufficient.
    """
    cursor = conn.cursor()
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    if cursor.fetchone() is None:
        # Table doesn't exist, create it with the full schema
        print(f"Table '{table_name}' not found. Creating it with the full schema.")
        cursor.execute(f"""
            CREATE TABLE {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                company TEXT,
                location TEXT,
                date TEXT,
                job_url TEXT UNIQUE,
                job_description TEXT,
                source TEXT,
                applied INTEGER DEFAULT 0,
                hidden INTEGER DEFAULT 0,
                interview INTEGER DEFAULT 0,
                rejected INTEGER DEFAULT 0,
                cover_letter TEXT,
                resume TEXT,
                date_loaded TEXT
            );
        """)
    else:
        # Table exists, check for missing columns and add them
        print(f"Table '{table_name}' found. Verifying schema...")
        cursor.execute(f"PRAGMA table_info({table_name})")
        table_info = cursor.fetchall()
        existing_columns = [column[1] for column in table_info]

        required_columns = {
            "applied": "INTEGER", "hidden": "INTEGER", "interview": "INTEGER",
            "rejected": "INTEGER", "cover_letter": "TEXT", "resume": "TEXT",
            "source": "TEXT", "date_loaded": "TEXT"
        }

        for col, col_type in required_columns.items():
            if col not in existing_columns:
                print(f"Adding missing column '{col}' to '{table_name}' table.")
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}")

    conn.commit()


def get_existing_job_urls(conn, table_name):
    """Fetches all existing job URLs from the database to avoid duplicates."""
    try:
        df_existing = pd.read_sql(f"SELECT job_url FROM {table_name}", conn)
        return set(df_existing['job_url'])
    except pd.errors.DatabaseError:
        return set()

def commit_jobs_to_db(conn, df, table_name):
    """Appends a DataFrame of new jobs to the specified table."""
    if df.empty:
        return

    df['date_loaded'] = pd.to_datetime('now').strftime("%Y-%m-%d %H:%M:%S")
    df.to_sql(table_name, conn, if_exists='append', index=False)
    print(f"Successfully added {len(df)} new jobs to the '{table_name}' table.")


def main():
    parser = argparse.ArgumentParser(description="Run job scrapers.")
    parser.add_argument('--source', type=str, choices=['linkedin', 'indeed', 'all'], default='all',
                        help='The job source to scrape.')
    args = parser.parse_args()

    config = load_config()
    conn = get_db_connection(config)
    jobs_table = config['app_settings']['jobs_tablename']

    verify_and_create_db_schema(conn, jobs_table)

    existing_urls = get_existing_job_urls(conn, jobs_table)
    print(f"Found {len(existing_urls)} existing job URLs in the database.")

    all_new_jobs_df = []

    if args.source in ['linkedin', 'all']:
        linkedin_df = scrape_linkedin(config, existing_urls)
        if not linkedin_df.empty:
            all_new_jobs_df.append(linkedin_df)

    if args.source in ['indeed', 'all']:
        # --- THIS IS THE FIX ---
        # Changed indeed__df to indeed_df (one underscore)
        indeed_df = scrape_indeed(config, existing_urls)
        if not indeed_df.empty:
            all_new_jobs_df.append(indeed_df)

    if all_new_jobs_df:
        final_df = pd.concat(all_new_jobs_df, ignore_index=True)
        final_df.drop_duplicates(subset=['job_url'], keep='first', inplace=True)
        final_df = final_df[~final_df['job_url'].isin(existing_urls)]

        commit_jobs_to_db(conn, final_df, jobs_table)
    else:
        print("No new jobs found from any source.")

    conn.close()

if __name__ == "__main__":
    main()