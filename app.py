import sqlite3
import json
import os
import threading
import time
import copy
import pandas as pd
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta, date
import subprocess
import sys
import re
import requests # Added for motivational quote API

# Import the scraper functions directly
# Make sure these files exist and are correctly implemented
try:
    from scrapers.linkedin_scraper import scrape_linkedin
    from scrapers.indeed_scraper import scrape_indeed
except ImportError as e:
    print(f"Error importing scrapers: {e}. Make sure scraper files exist and are configured.")
    # Define dummy functions if scrapers are not found to allow app to run for UI testing
    def scrape_linkedin(config, existing_urls): return pd.DataFrame()
    def scrape_indeed(config, existing_urls): return pd.DataFrame()


# --- Global variable for scraping status ---
scraping_status = {
    "is_running": False,
    "message": "Idle"
}

# --- Constants ---
RESUME_CREATION_FOLDER = 'resume_cover_creation'

def load_config(file_name="config.json"):
    try:
        with open(file_name) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file '{file_name}' not found. Please ensure it exists.")
        # Provide a default config or exit if critical
        return {
            "app_settings": {"db_path": "data/jobs.db", "jobs_tablename": "jobs", "proxies": [], "headers": {}},
            "linkedin_settings": {"timespan": "r604800", "days_to_scrape": 7, "search_queries": [], "desc_exclude": [], "title_exclude": [], "title_include": [], "languages": [], "company_exclude": [], "pages_to_scrape": 1},
            "indeed_settings": {"search_config": {"max_listing_days": 7}, "master_csv_file": "data/indeed_results.csv", "cache_folder": "data/cache", "log_file": "data/log.log", "block_list_file": "data/indeed_block_list.json", "duplicates_list_file": "data/indeed_duplicates.json", "delay_config": {}},
            "dashboard_settings": {"daily_application_goal": 10, "weekly_application_goal": 50}, # Default for dashboard
            "resume_settings": {"base_output_name": "tailored_resume"} # Default for resume generation
        } # Basic default
    except json.JSONDecodeError:
        print(f"Error: Configuration file '{file_name}' is not valid JSON.")
        sys.exit(1)


config = load_config()
app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# --- DATABASE INITIALIZATION AND HELPERS ---

def get_db_connection():
    db_path = config.get('app_settings', {}).get('db_path', 'data/jobs.db') # Default path
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir): # Check if db_dir is not empty before creating
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row # To access columns by name
    return conn

def initialize_database():
    """Creates/verifies the database schema on startup."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create scrape_history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scrape_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_filter TEXT,
            time_period_scraped TEXT,
            new_jobs_found INTEGER
        )
    """)

    # Create jobs table if not exists, or alter if it exists but lacks application_date
    cursor.execute("PRAGMA table_info(jobs)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'jobs' not in [row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs';").fetchall()]:
        cursor.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                company TEXT,
                location TEXT,
                date TEXT,
                job_url TEXT UNIQUE,
                job_description TEXT,
                source TEXT,
                status TEXT DEFAULT 'inbox',
                date_loaded DATETIME,
                application_date DATETIME,
                scrape_history_id INTEGER,
                FOREIGN KEY (scrape_history_id) REFERENCES scrape_history(id)
            )
        """)
        print("Created 'jobs' table with 'application_date' column.")
    elif 'application_date' not in columns:
        try:
            cursor.execute("ALTER TABLE jobs ADD COLUMN application_date DATETIME")
            print("Added 'application_date' column to 'jobs' table.")
        except sqlite3.OperationalError as e:
            print(f"Could not add 'application_date' column: {e}. It might already exist or another issue occurred.")

    # Create resume_generations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resume_generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            generation_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)

    # Create cover_letter_generations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cover_letter_generations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            generation_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

    # Ensure the 'resume_cover_creation' directory exists
    if not os.path.exists(RESUME_CREATION_FOLDER):
        os.makedirs(RESUME_CREATION_FOLDER)
        print(f"Created directory: {RESUME_CREATION_FOLDER}")

# --- CORE SCRAPING AND DATABASE LOGIC ---

def commit_jobs_to_db(conn, df, history_id):
    table_name = config.get('app_settings', {}).get('jobs_tablename', 'jobs')
    print(f"\n--- commit_jobs_to_db called ---")
    print(f"DataFrame passed to commit_jobs_to_db has {len(df)} rows.")
    if df.empty:
        print("DataFrame is empty. No jobs to commit.")
        return 0

    cursor = conn.cursor()
    cursor.execute(f"SELECT job_url FROM {table_name}")
    existing_urls = {row[0] for row in cursor.fetchall()}
    print(f"Found {len(existing_urls)} existing job URLs in the database.")
    if existing_urls:
        print(f"Sample existing URLs (first 5): {list(existing_urls)[:5]}")

    # Filter out jobs that already exist by their URL
    # Ensure 'job_url' column exists in the DataFrame before filtering
    if 'job_url' not in df.columns:
        print("ERROR: 'job_url' column missing in DataFrame passed to commit_jobs_to_db. Cannot filter duplicates.")
        return 0

    new_jobs_df = df[~df['job_url'].isin(existing_urls)].copy()

    print(f"After filtering existing URLs, {len(new_jobs_df)} truly new jobs remain to be inserted.")
    if new_jobs_df.empty:
        print("No truly new jobs to insert after duplicate check.")
        return 0
        
    new_jobs_df['date_loaded'] = pd.to_datetime('now').strftime("%Y-%m-%d %H:%M:%S")
    new_jobs_df['status'] = 'inbox'
    new_jobs_df['scrape_history_id'] = history_id
    new_jobs_df['application_date'] = None # Explicitly set for new insertions
    
    columns_to_insert = [
        'title', 'company', 'location', 'date', 'job_url', 
        'job_description', 'source', 'status', 'date_loaded',
        'application_date', 'scrape_history_id'
    ]
    
    # Ensure only columns that exist in the DataFrame are used and in correct order for to_sql
    # And ensure the order matches the target table
    df_to_insert = new_jobs_df[[col for col in columns_to_insert if col in new_jobs_df.columns]]
    
    print(f"DataFrame prepared for insertion (head):\n{df_to_insert.head()}")
    print(f"Columns in DataFrame prepared for insertion: {df_to_insert.columns.tolist()}")

    try:
        df_to_insert.to_sql(table_name, conn, if_exists='append', index=False)
        print(f"Successfully inserted {len(df_to_insert)} new jobs into '{table_name}'.")
    except Exception as e:
        print(f"ERROR: Failed to insert jobs into database: {e}")
        import traceback
        traceback.print_exc() # Print full traceback for insertion error
        return 0
    return len(df_to_insert)


def perform_scraping_task(source, time_period_str, timespan_seconds, days_to_scrape, management_option, location, keywords): # ADD location, keywords
    global scraping_status
    scraping_status['is_running'] = True
    print(f"\n--- Initiating scraping task for source: {source} ---")
    print(f"Management Option: {management_option}")
    print(f"Location: {location}, Keywords: {keywords}")
    
    try:
        conn = get_db_connection()
        
        if management_option == 'archive':
            scraping_status['message'] = "Archiving old jobs..."
            print("Archiving 'inbox' jobs...")
            conn.execute("UPDATE jobs SET status = 'archived' WHERE status = 'inbox'")
            conn.commit()
            print("Archiving complete.")
        elif management_option == 'delete':
            scraping_status['message'] = "Deleting old jobs..."
            print("Deleting 'inbox' jobs...")
            conn.execute("DELETE FROM jobs WHERE status = 'inbox'")
            conn.commit()
            print("Deletion complete.")

        scraping_status['message'] = "Creating scrape history record..."
        history_cursor = conn.cursor()
        history_cursor.execute(
            "INSERT INTO scrape_history (source_filter, time_period_scraped, new_jobs_found) VALUES (?, ?, ?)",
            (source, time_period_str, 0)
        )
        history_id = history_cursor.lastrowid
        conn.commit()
        print(f"Scrape history record created with ID: {history_id}")
        
        cursor = conn.cursor()
        cursor.execute(f"SELECT job_url FROM jobs") # Assuming table name is 'jobs'
        existing_urls = {row[0] for row in cursor.fetchall()}
        print(f"Fetched {len(existing_urls)} existing URLs from DB for pre-filtering.")
        
        local_config = copy.deepcopy(config) # Ensure we modify a copy, not the global config

        # --- Apply location and keywords to local_config ---
        # For LinkedIn
        if source in ['linkedin', 'all']:
            if 'linkedin_settings' in local_config:
                if 'search_queries' not in local_config['linkedin_settings'] or not local_config['linkedin_settings']['search_queries']:
                    local_config['linkedin_settings']['search_queries'] = [{}] # Ensure at least one query exists
                
                # Update the first search query with provided location and keywords if they exist
                if keywords:
                    local_config['linkedin_settings']['search_queries'][0]['keywords'] = keywords
                if location:
                    local_config['linkedin_settings']['search_queries'][0]['location'] = location
                
                local_config['linkedin_settings']['timespan'] = f"r{timespan_seconds}"
                local_config['linkedin_settings']['days_to_scrape'] = days_to_scrape
                print(f"LinkedIn settings applied in local_config: {local_config['linkedin_settings']}")

        # For Indeed
        if source in ['indeed', 'all']:
            if 'indeed_settings' in local_config and 'search_config' in local_config['indeed_settings']:
                if keywords:
                    local_config['indeed_settings']['search_config']['keywords'] = [k.strip() for k in keywords.split(',') if k.strip()]
                if location:
                    local_config['indeed_settings']['search_config']['city'] = location
                
                local_config['indeed_settings']['search_config']['max_listing_days'] = days_to_scrape
                print(f"Indeed settings applied in local_config: {local_config['indeed_settings']}")

        all_new_jobs_df_list = []

        if source in ['linkedin', 'all']:
            scraping_status['message'] = "Scraping LinkedIn..."
            print("Calling LinkedIn scraper...")
            linkedin_df = scrape_linkedin(local_config, existing_urls)
            if not linkedin_df.empty:
                print(f"LinkedIn scraper returned {len(linkedin_df)} jobs.")
                all_new_jobs_df_list.append(linkedin_df)
            else:
                print("LinkedIn scraper returned an empty DataFrame.")

        if source in ['indeed', 'all']:
            scraping_status['message'] = "Scraping Indeed..."
            print("Calling Indeed scraper...")
            indeed_df = scrape_indeed(local_config, existing_urls)
            if not indeed_df.empty:
                print(f"Indeed scraper returned {len(indeed_df)} jobs.")
                all_new_jobs_df_list.append(indeed_df)
            else:
                print("Indeed scraper returned an empty DataFrame.")

        num_added = 0
        if all_new_jobs_df_list:
            scraping_status['message'] = "Combining and saving new jobs..."
            print(f"Combining {len(all_new_jobs_df_list)} DataFrames.")
            final_df = pd.concat(all_new_jobs_df_list, ignore_index=True).drop_duplicates(subset=['job_url'])
            print(f"Combined DataFrame has {len(final_df)} unique jobs by URL.")
            num_added = commit_jobs_to_db(conn, final_df, history_id)
        else:
            print("No jobs found by any scraper to combine and save.")
            
        conn.execute("UPDATE scrape_history SET new_jobs_found = ? WHERE id = ?", (num_added, history_id))
        conn.commit()
        
        scraping_status['message'] = f"Scraping complete. Added {num_added} new jobs."
        print(f"Scraping completed. Total new jobs added to DB: {num_added}.")
        conn.close()
        time.sleep(3)

    except Exception as e:
        scraping_status['message'] = f"An error occurred: {e}"
        print(f"An unexpected error occurred during scraping: {e}")
        import traceback
        traceback.print_exc()
        time.sleep(5)
    
    finally:
        scraping_status['is_running'] = False
        scraping_status['message'] = "Idle"
        print("Scraping task finished (idle).")


# --- FLASK ROUTES ---
# (Rest of your app.py remains unchanged)

@app.route('/')
def home():
    return render_template('jobs.html')

@app.route('/dashboard')
def dashboard_page():
    dash_config = config.get('dashboard_settings', {})
    daily_goal = dash_config.get('daily_application_goal', 10) # Default to 10 if not set
    weekly_goal = dash_config.get('weekly_application_goal', 50) # Default to 50 if not set
    return render_template('dashboard.html', daily_goal=daily_goal, weekly_goal=weekly_goal)

@app.route('/get_jobs')
def get_jobs():
    status_filter = request.args.get('status', None)
    jobs_list = []
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if application_date column exists
    cursor.execute("PRAGMA table_info(jobs)")
    columns = [column[1] for column in cursor.fetchall()]
    select_columns_list = ['id', 'title', 'company', 'location', 'date', 'job_url', 'job_description', 'source', 'status', 'date_loaded', 'scrape_history_id']
    if 'application_date' in columns:
        select_columns_list.append('application_date')
    else: # Add a placeholder if the column doesn't exist yet for older data
        select_columns_list.append("NULL as application_date")

    select_columns_str = ", ".join(select_columns_list)

    if status_filter:
        query = f"SELECT {select_columns_str} FROM jobs WHERE status = ? ORDER BY id DESC"
        cursor.execute(query, (status_filter,))
    else:
        query = f"SELECT {select_columns_str} FROM jobs ORDER BY id DESC"
        cursor.execute(query)

    rows = cursor.fetchall()
    for row in rows:
        jobs_list.append(dict(row))
    conn.close()
    return jsonify(jobs_list)

@app.route('/update_job_status/<int:job_id>', methods=['POST'])
def update_job_status_route(job_id): # Renamed to avoid conflict
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "New status not provided."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(jobs)")
    columns = [column[1] for column in cursor.fetchall()]
    has_application_date_column = 'application_date' in columns

    if new_status.lower() == 'applied' and has_application_date_column:
        cursor.execute("SELECT application_date FROM jobs WHERE id = ?", (job_id,))
        current_app_date_row = cursor.fetchone()
        if current_app_date_row and current_app_date_row['application_date'] is None:
            conn.execute("UPDATE jobs SET status = ?, application_date = CURRENT_TIMESTAMP WHERE id = ?", (new_status, job_id))
        else:
            conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    else:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))

    conn.commit()
    conn.close()
    return jsonify({"success": f"Job {job_id} status updated to {new_status}."})

@app.route('/scrape', methods=['POST'])
def scrape_jobs_route_main():
    if scraping_status['is_running']:
        return jsonify({"error": "A scraping process is already running."}), 409

    data = request.get_json()
    source = data.get('source', 'all')
    time_period_str = data.get('time_period_str', '7 Days') # This value isn't used by perform_scraping_task, might be for history only
    timespan = data.get('timespan', 86400 * 7) # This isn't received from UI, `days` is used to calculate it
    days = data.get('days', 7)
    management_option = data.get('management_option', 'add')
    # --- ADDITIONS HERE ---
    location = data.get('location', '')
    keywords = data.get('keywords', '')
    # --- END ADDITIONS ---

    thread = threading.Thread(target=perform_scraping_task, args=(source, time_period_str, timespan, days, management_option, location, keywords)) # Pass new args
    thread.daemon = True
    thread.start()
    return jsonify({"message": "Scraping process initiated."}), 202

@app.route('/scrape_status')
def scrape_status_endpoint():
    return jsonify(scraping_status)

@app.route('/get_stats')
def get_stats_old():
    stats = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    twenty_four_hours_ago = datetime.now() - timedelta(hours=24)
    query = "SELECT SUM(new_jobs_found) FROM scrape_history WHERE scrape_timestamp >= ?"
    cursor.execute(query, (twenty_four_hours_ago.strftime('%Y-%m-%d %H:%M:%S'),))
    result = cursor.fetchone()
    stats['jobs_last_24_hours'] = result[0] if result and result[0] is not None else 0
    conn.close()
    return jsonify(stats)

@app.route('/api/dashboard_stats')
def api_dashboard_stats():
    stats = {}
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(jobs)")
    job_columns = [column[1] for column in cursor.fetchall()]
    has_application_date_column = 'application_date' in job_columns

    # Jobs Scraped in the last 24 hours
    twenty_four_hours_ago_dt = datetime.now() - timedelta(hours=24)
    twenty_four_hours_ago_str = twenty_four_hours_ago_dt.strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT SUM(new_jobs_found) FROM scrape_history WHERE scrape_timestamp >= ?", (twenty_four_hours_ago_str,))
    result = cursor.fetchone()
    stats['jobs_scraped_last_24_hours'] = result[0] if result and result[0] is not None else 0

    applied_statuses = ('applied', 'interviewing', 'offer', 'rejected', 'rejected_after_interview', 'offer_declined')
    status_placeholders = ', '.join(['?'] * len(applied_statuses))

    # Total Applications
    query_total_applications = f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders})"
    if has_application_date_column:
        query_total_applications += " AND application_date IS NOT NULL"
    cursor.execute(query_total_applications, applied_statuses)
    stats['total_applications'] = cursor.fetchone()[0]

    # Applications Today - FIX APPLIED HERE
    today_start_str = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    if has_application_date_column:
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND application_date >= ?", (*applied_statuses, today_start_str))
        result_today = cursor.fetchone() # Fetch once
        stats['applications_today'] = result_today[0] if result_today and result_today[0] is not None else 0
    else:
        stats['applications_today'] = 0

    # Applications This Week - FIX APPLIED HERE
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) # Monday
    start_of_week_str = datetime.combine(start_of_week, datetime.min.time()).strftime('%Y-%m-%d %H:%M:%S')
    if has_application_date_column:
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND application_date >= ?", (*applied_statuses, start_of_week_str))
        result_this_week = cursor.fetchone() # Fetch once
        stats['applications_this_week'] = result_this_week[0] if result_this_week and result_this_week[0] is not None else 0
    else:
        stats['applications_this_week'] = 0

    # Total Resumes Created
    cursor.execute("SELECT COUNT(*) FROM resume_generations")
    stats['resumes_created_total'] = cursor.fetchone()[0]

    # Resumes Created Today
    cursor.execute("SELECT COUNT(*) FROM resume_generations WHERE generation_timestamp >= ?", (today_start_str,))
    stats['resumes_created_today'] = cursor.fetchone()[0]

    # Total Cover Letters Created
    cursor.execute("SELECT COUNT(*) FROM cover_letter_generations")
    stats['cover_letters_created_total'] = cursor.fetchone()[0]

    # Cover Letters Created Today
    cursor.execute("SELECT COUNT(*) FROM cover_letter_generations WHERE generation_timestamp >= ?", (today_start_str,))
    stats['cover_letters_created_today'] = cursor.fetchone()[0]

    # Application Status Breakdown
    cursor.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status")
    stats['application_status_breakdown'] = {row['status']: row['count'] for row in cursor.fetchall()}
    if not stats['application_status_breakdown']:
        stats['application_status_breakdown'] = {}

    # Applications by Source (for jobs that have been applied to)
    query_apps_by_source = f"SELECT source, COUNT(*) as count FROM jobs WHERE status IN ({status_placeholders})"
    if has_application_date_column:
        query_apps_by_source += " AND application_date IS NOT NULL"
    query_apps_by_source += " GROUP BY source"
    cursor.execute(query_apps_by_source, applied_statuses)
    stats['applications_by_source'] = {row['source']: row['count'] for row in cursor.fetchall()}
    if not stats['applications_by_source']:
        stats['applications_by_source'] = {}

    # Applications per day for the last 7 days (for chart)
    applications_per_day = []
    if has_application_date_column:
        for i in range(6, -1, -1):
            day_date = date.today() - timedelta(days=i)
            day_start_str = datetime.combine(day_date, datetime.min.time()).strftime('%Y-%m-%d %H:%M:%S')
            day_end_str = datetime.combine(day_date, datetime.max.time()).strftime('%Y-%m-%d %H:%M:%S')

            query_apps_per_day = f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND application_date >= ? AND application_date <= ?"
            cursor.execute(query_apps_per_day, (*applied_statuses, day_start_str, day_end_str))
            count = cursor.fetchone()[0]
            applications_per_day.append({'date': day_date.strftime('%Y-%m-%d'), 'count': count})
    stats['applications_last_7_days'] = applications_per_day

    conn.close()
    return jsonify(stats)

@app.route('/api/quote')
def get_motivational_quote():
    try:
        response = requests.get("https://zenquotes.io/api/random", timeout=5)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, list) and len(data) > 0:
            quote = data[0].get('q', 'Keep going!')
            author = data[0].get('a', 'Unknown')
            return jsonify({"quote": quote, "author": author})
        else:
            return jsonify({"quote": "The journey of a thousand miles begins with a single step.", "author": "Lao Tzu"})
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching quote: {e}")
        return jsonify({"quote": "The difference between ordinary and extraordinary is that little extra.", "author": "Jimmy Johnson"})


@app.route('/generate_documents', methods=['POST'])
def generate_documents():
    try:
        data = request.get_json()
        job_description = data.get('job_description')
        job_id = data.get('job_id', None) # Get job_id, default to None if not provided

        if not job_description:
            return jsonify({"error": "Job description is required"}), 400

        job_desc_file_path = os.path.join(RESUME_CREATION_FOLDER, 'job_description.txt')

        with open(job_desc_file_path, 'w', encoding='utf-8') as f:
            f.write(job_description)

        cmd = [sys.executable, 'create_resume.py', 'job_description.txt']
        
        if hasattr(app, 'logger') and app.logger:
            app.logger.info(f"Running command: {' '.join(cmd)} in CWD: {RESUME_CREATION_FOLDER}")

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=RESUME_CREATION_FOLDER,
            encoding='utf-8',
            errors='replace'
        )

        if process.returncode != 0:
            if hasattr(app, 'logger') and app.logger:
                app.logger.error(f"Error generating documents. Return code: {process.returncode}")
                app.logger.error(f"Stderr: {process.stderr}")
                app.logger.error(f"Stdout: {process.stdout}")
            return jsonify({
                "error": "Failed to generate documents",
                "details": process.stderr if process.stderr else "Unknown error, check logs."
            }), 500

        if hasattr(app, 'logger') and app.logger:
            app.logger.info(f"Document generation script stdout: {process.stdout}")
        
        conn = get_db_connection()
        try:
            # Log resume generation
            conn.execute("INSERT INTO resume_generations (job_id, generation_timestamp) VALUES (?, CURRENT_TIMESTAMP)",
                         (job_id,)) # job_id can be None, which SQLite handles as NULL
            conn.commit()
            if hasattr(app, 'logger') and app.logger:
                app.logger.info(f"Logged resume generation for job_id: {job_id if job_id else 'N/A'}")

            # Log cover letter generation
            conn.execute("INSERT INTO cover_letter_generations (job_id, generation_timestamp) VALUES (?, CURRENT_TIMESTAMP)",
                         (job_id,)) # job_id can be None, which SQLite handles as NULL
            conn.commit()
            if hasattr(app, 'logger') and app.logger:
                app.logger.info(f"Logged cover letter generation for job_id: {job_id if job_id else 'N/A'}")

        except Exception as e_db:
            if hasattr(app, 'logger') and app.logger:
                app.logger.error(f"Error logging document generation: {e_db}")
        finally:
            conn.close()

        resume_pdf_filename = None
        # Try to find the filename in a more robust way from stdout
        # Assuming the script prints "Successfully created <filename.pdf>"
        match = re.search(r"Successfully created\s+([^\s]+\.pdf)", process.stdout)
        if match:
            resume_pdf_filename = match.group(1)
        
        if not resume_pdf_filename: # Fallback if regex fails
            # Look for the newest PDF in the directory, assuming it's the one just created
            pdf_files = [f for f in os.listdir(RESUME_CREATION_FOLDER) if f.startswith(config.get('resume_settings',{}).get('base_output_name', 'tailored_resume')) and f.endswith('.pdf')]
            if pdf_files:
                pdf_files.sort(key=lambda f: os.path.getmtime(os.path.join(RESUME_CREATION_FOLDER, f)), reverse=True)
                resume_pdf_filename = pdf_files[0]
                if hasattr(app, 'logger') and app.logger:
                    app.logger.warning(f"Could not parse PDF filename from stdout using regex, using newest found: {resume_pdf_filename}")
            else: # If still not found
                if hasattr(app, 'logger') and app.logger:
                    app.logger.error(f"Could not determine resume PDF filename from script output: {process.stdout}")
                return jsonify({
                    "error": "Could not determine resume PDF filename from script output.",
                    "details": process.stdout
                }), 500

        cover_letter_pdf_filename = resume_pdf_filename.replace('.pdf', '_cover_letter.pdf')
        
        expected_resume_path = os.path.join(RESUME_CREATION_FOLDER, resume_pdf_filename)

        if not os.path.exists(expected_resume_path):
            if hasattr(app, 'logger') and app.logger:
                app.logger.error(f"Generated resume PDF not found at: {expected_resume_path}")
            return jsonify({"error": "Resume PDF file not found after generation.", "details": resume_pdf_filename}), 500
        
        return jsonify({
            "success": True,
            "resume_pdf_url": f"/serve_pdf/{resume_pdf_filename}",
            "cover_letter_pdf_url": f"/serve_pdf/{cover_letter_pdf_filename}"
        })

    except Exception as e:
        if hasattr(app, 'logger') and app.logger:
            app.logger.exception("Error in /generate_documents")
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500


@app.route('/serve_pdf/<path:filename>')
def serve_pdf(filename):
    safe_filename = os.path.normpath(filename)
    if ".." in safe_filename or os.path.isabs(safe_filename):
        if hasattr(app, 'logger') and app.logger:
            app.logger.warning(f"Attempt to access potentially unsafe path: {filename}")
        return jsonify({"error": "Invalid filename"}), 400

    # More specific check for PDF files from the resume creation folder
    # This check might be too restrictive if other PDFs are ever served, but good for now.
    if not (safe_filename.startswith(config.get('resume_settings',{}).get('base_output_name', 'tailored_resume')) and (safe_filename.endswith(".pdf") or safe_filename.endswith(".docx"))):
             if hasattr(app, 'logger') and app.logger:
                app.logger.warning(f"Attempt to access non-resume/cover_letter PDF/DOCX: {filename}")
            # return jsonify({"error": "Invalid filename format for document"}), 400 # Commenting out for now to allow original functionality if needed

    if hasattr(app, 'logger') and app.logger:
        app.logger.info(f"Serving PDF: {safe_filename} from {RESUME_CREATION_FOLDER}")
    return send_from_directory(RESUME_CREATION_FOLDER, safe_filename, as_attachment=False)


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True, port=5001)