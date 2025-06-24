import psycopg2
import psycopg2.extras # Import DictCursor
import pandas as pd
import json
import argparse
import os
from scrapers.linkedin_scraper import scrape_linkedin
from scrapers.indeed_scraper import scrape_indeed

def load_config(file_name="config.json"):
    with open(file_name) as f:
        return json.load(f)

def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("No DATABASE_URL set for the connection")
    conn = psycopg2.connect(db_url)
    conn.cursor_factory = psycopg2.extras.DictCursor # Use DictCursor
    return conn

def verify_and_create_db_schema(conn, user_id_for_schema_check=None):
    """
    Verifies the database table 'jobs' has all necessary columns, creating the table
    and/or columns as needed, targeting the schema used by app.py.
    It uses the main 'jobs' table schema defined in app.py.
    If user_id_for_schema_check is provided, it will also ensure that this user
    exists, which is a prerequisite for inserting jobs for that user.
    """
    cursor = conn.cursor()
    table_name = 'jobs' # Hardcoding to 'jobs' as this script interacts with the main jobs table

    # Check if table exists
    cursor.execute(f"""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = '{table_name}'
        );
    """)
    if not cursor.fetchone()[0]:
        print(f"Table '{table_name}' not found. Please run the main Flask app (app.py) first to initialize the database schema.")
        # We won't create the table here as app.py is responsible for the full schema.
        # This script should only run after the main app has set up the DB.
        # However, for standalone operation or a more robust script, one might include
        # the CREATE TABLE statement from app.py here as well.
        # For now, we assume app.py handles table creation.
        return

    print(f"Table '{table_name}' found. Verifying schema (columns relevant to this script)...")
    cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'")
    existing_columns = [row['column_name'] for row in cursor.fetchall()]

    # Columns this script will try to insert (subset of the main table schema)
    # These are based on what scrape_linkedin and scrape_indeed provide, plus some defaults.
    script_relevant_columns = {
        'title': 'TEXT', 'company': 'TEXT', 'location': 'TEXT', 'date': 'TEXT',
        'job_url': 'TEXT', 'job_description': 'TEXT', 'source': 'TEXT',
        'status': 'TEXT', 'date_loaded': 'TIMESTAMPTZ', 'user_id': 'INTEGER'
        # 'scrape_history_id' and 'application_date' are handled by app.py or set to NULL.
    }

    missing_columns = False
    for col, col_type in script_relevant_columns.items():
        if col not in existing_columns:
            print(f"WARNING: Column '{col}' (expected type {col_type}) not found in '{table_name}' table. Jobs might not be inserted correctly by this script if it relies on this column.")
            # This script won't alter the table; schema changes should be managed by app.py's initialize_database.
            missing_columns = True

    if missing_columns:
        print(f"One or more expected columns are missing in '{table_name}'. Please ensure the database schema is up-to-date by running app.py.")

    # If a user_id is provided for context (e.g., jobs will be inserted for this user),
    # check if this user exists.
    if user_id_for_schema_check:
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id_for_schema_check,))
        if not cursor.fetchone():
            print(f"WARNING: User with ID {user_id_for_schema_check} does not exist in the 'users' table. Jobs cannot be associated with this user.")
            # Consider raising an error or handling this case based on script requirements.

    conn.commit() # Commit any checks if needed, though mostly SELECTs here.

def get_existing_job_urls(conn, user_id):
    """Fetches all existing job URLs for a specific user from the database to avoid duplicates."""
    # Assuming 'jobs' is the table name, consistent with app.py
    table_name = 'jobs'
    try:
        # Modify query to be user-specific
        query = f"SELECT job_url FROM {table_name} WHERE user_id = %s"
        df_existing = pd.read_sql(query, conn, params=(user_id,))
        return set(df_existing['job_url'])
    except Exception as e: # Catch a broader exception for database errors
        print(f"Error reading existing job URLs for user {user_id}: {e}")
        return set()

def commit_jobs_to_db(conn, df, user_id):
    """Appends a DataFrame of new jobs to the 'jobs' table for a specific user."""
    table_name = 'jobs' # Consistent with app.py
    if df.empty:
        print(f"No new jobs to commit for user {user_id}.")
        return 0

    cursor = conn.cursor()

    # Prepare DataFrame for insertion
    df_to_insert = df.copy()
    df_to_insert['user_id'] = user_id
    df_to_insert['date_loaded'] = pd.to_datetime('now', utc=True) # Use timezone-aware datetime
    df_to_insert['status'] = 'inbox' # Default status
    # 'scrape_history_id' and 'application_date' can be NULL or handled differently if needed
    df_to_insert['scrape_history_id'] = None
    df_to_insert['application_date'] = None

    # Ensure columns match the target table structure expected by this script's context
    # (title, company, location, date, job_url, job_description, source, status, date_loaded, user_id)
    # Other columns in the DB table like 'id' (serial), 'applied', 'hidden' etc. will take defaults or are not set here.

    columns_to_insert = [
        'title', 'company', 'location', 'date', 'job_url',
        'job_description', 'source', 'status', 'date_loaded', 'user_id',
        'scrape_history_id', 'application_date'
    ]

    # Filter df_to_insert to only include these columns, in this order
    # Fill missing expected columns with None if not present in the scraped data
    for col in columns_to_insert:
        if col not in df_to_insert.columns:
            df_to_insert[col] = None

    df_final_insert = df_to_insert[columns_to_insert]

    # Use psycopg2.extras.execute_values for efficient batch insert
    from psycopg2.extras import execute_values

    tuples = [tuple(x) for x in df_final_insert.to_numpy()]
    cols_str = ','.join(columns_to_insert)

    # ON CONFLICT (job_url, user_id) DO NOTHING ensures that if a job URL for that user already exists, it's skipped.
    # This is crucial for preventing duplicate entries if get_existing_job_urls somehow missed an entry or in concurrent scenarios.
    query  = f"INSERT INTO {table_name} ({cols_str}) VALUES %s ON CONFLICT (job_url, user_id) DO NOTHING"

    try:
        execute_values(cursor, query, tuples)
        conn.commit()
        # cursor.rowcount will give the number of rows affected by the INSERT.
        # This count might be less than len(tuples) if some rows caused conflicts and were ignored.
        num_inserted = cursor.rowcount
        print(f"Successfully processed {len(tuples)} jobs for user {user_id}. Inserted {num_inserted} new unique jobs into '{table_name}'.")
        return num_inserted
    except Exception as e:
        print(f"ERROR: Failed to insert jobs into database for user {user_id}: {e}")
        conn.rollback()
        return 0
    finally:
        cursor.close()


def main():
    parser = argparse.ArgumentParser(description="Run job scrapers and add jobs to the PostgreSQL database for a specific user.")
    parser.add_argument('--source', type=str, choices=['linkedin', 'indeed', 'all'], default='all',
                        help='The job source to scrape.')
    parser.add_argument('--user_id', type=int, required=True,
                        help='The ID of the user for whom to scrape and store jobs.')

    args = parser.parse_args()

    config = load_config() # config.json is still used for scraper-specific settings

    try:
        conn = get_db_connection() # Connects to PostgreSQL using DATABASE_URL
    except ValueError as e:
        print(f"Database connection error: {e}")
        return
    except psycopg2.Error as e:
        print(f"PostgreSQL connection error: {e}")
        return

    # Verify schema and user existence
    # Pass user_id to check if the user exists, which is a prerequisite for inserting jobs.
    verify_and_create_db_schema(conn, user_id_for_schema_check=args.user_id)

    # Fetch existing job URLs for the specified user
    existing_urls = get_existing_job_urls(conn, args.user_id)
    print(f"Found {len(existing_urls)} existing job URLs in the database for user {args.user_id}.")

    all_new_jobs_df_list = [] # Renamed to avoid confusion with final_df

    if args.source in ['linkedin', 'all']:
        print(f"\nScraping LinkedIn for user {args.user_id}...")
        linkedin_df = scrape_linkedin(config, existing_urls) # existing_urls is already user-specific
        if not linkedin_df.empty:
            print(f"LinkedIn scraper found {len(linkedin_df)} potential new jobs for user {args.user_id}.")
            all_new_jobs_df_list.append(linkedin_df)
        else:
            print(f"LinkedIn scraper found no new jobs for user {args.user_id}.")

    if args.source in ['indeed', 'all']:
        print(f"\nScraping Indeed for user {args.user_id}...")
        indeed_df = scrape_indeed(config, existing_urls) # existing_urls is already user-specific
        if not indeed_df.empty:
            print(f"Indeed scraper found {len(indeed_df)} potential new jobs for user {args.user_id}.")
            all_new_jobs_df_list.append(indeed_df)
        else:
            print(f"Indeed scraper found no new jobs for user {args.user_id}.")

    if all_new_jobs_df_list:
        final_df = pd.concat(all_new_jobs_df_list, ignore_index=True)
        # Drop duplicates based on job_url that might have been scraped from multiple sources (if applicable)
        # or if a single scraper returned duplicates internally (though scrapers should ideally handle this).
        final_df.drop_duplicates(subset=['job_url'], keep='first', inplace=True)

        # Filter again against existing_urls, as the initial set might have been from a slightly earlier DB state
        # or if scrapers don't perfectly use the passed existing_urls for pre-filtering.
        # This is a safety net.
        final_df_to_commit = final_df[~final_df['job_url'].isin(existing_urls)].copy()

        if not final_df_to_commit.empty:
            print(f"\nAttempting to commit {len(final_df_to_commit)} unique new jobs to the database for user {args.user_id}.")
            # Pass args.user_id to commit_jobs_to_db
            num_actually_inserted = commit_jobs_to_db(conn, final_df_to_commit, args.user_id)
            print(f"Finished commit process. {num_actually_inserted} jobs were newly inserted for user {args.user_id}.")
        else:
            print(f"\nNo new unique jobs to commit to the database for user {args.user_id} after final filtering.")

    else:
        print(f"\nNo new jobs found from any source for user {args.user_id}.")

    if conn:
        conn.close()
    print(f"\nScraping process finished for user {args.user_id}.")

if __name__ == "__main__":
    # Make sure environment variables are loaded if you use a .env file
    # from dotenv import load_dotenv
    # load_dotenv() # You might need to install python-dotenv: pip install python-dotenv
    main()