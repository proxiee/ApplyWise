```python
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
            "app_settings": {"db_path": "data/jobs.db", "jobs_tablename": "jobs"},
            "linkedin_settings": {"timespan": "r604800", "days_to_scrape": 7, "search_queries": [], "desc_exclude": [], "title_exclude": [], "title_include": [], "languages": [], "company_exclude": []},
            "indeed_settings": {"search_config": {"max_listing_days": 7}, "master_csv_file": "data/indeed_results.csv", "cache_folder": "data/cache", "log_file": "data/log.log", "block_list_file": "data/indeed_block_list.json", "duplicates_list_file": "data/indeed_duplicates.json", "delay_config": {}}
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
    if df.empty:
        return 0

    cursor = conn.cursor()
    cursor.execute(f"SELECT job_url FROM {table_name}")
    existing_urls = {row[0] for row in cursor.fetchall()}
    
    new_jobs_df = df[~df['job_url'].isin(existing_urls)].copy()

    if new_jobs_df.empty:
        return 0
        
    new_jobs_df['date_loaded'] = pd.to_datetime('now').strftime("%Y-%m-%d %H:%M:%S")
    new_jobs_df['status'] = 'inbox'
    new_jobs_df['scrape_history_id'] = history_id
    new_jobs_df['application_date'] = None
    
    columns_to_insert = ['title', 'company', 'location', 'date', 'job_url', 
                         'job_description', 'source', 'status', 'date_loaded',
                         'application_date', 'scrape_history_id']
    
    # Ensure only columns that exist in the DataFrame are used and in correct order for to_sql
    df_to_insert = new_jobs_df[[col for col in columns_to_insert if col in new_jobs_df.columns]]
    
    df_to_insert.to_sql(table_name, conn, if_exists='append', index=False)
    return len(df_to_insert)


def perform_scraping_task(source, time_period_str, timespan_seconds, days_to_scrape, management_option):
    global scraping_status
    scraping_status['is_running'] = True
    
    try:
        conn = get_db_connection()
        
        if management_option == 'archive':
            scraping_status['message'] = "Archiving old jobs..."
            conn.execute("UPDATE jobs SET status = 'archived' WHERE status = 'inbox'")
            conn.commit()
        elif management_option == 'delete':
            scraping_status['message'] = "Deleting old jobs..."
            conn.execute("DELETE FROM jobs WHERE status = 'inbox'")
            conn.commit()

        scraping_status['message'] = "Creating scrape history record..."
        history_cursor = conn.cursor()
        history_cursor.execute(
            "INSERT INTO scrape_history (source_filter, time_period_scraped, new_jobs_found) VALUES (?, ?, ?)",
            (source, time_period_str, 0)
        )
        history_id = history_cursor.lastrowid
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute(f"SELECT job_url FROM jobs") # Assuming table name is 'jobs'
        existing_urls = {row[0] for row in cursor.fetchall()}
        
        local_config = copy.deepcopy(config)
        if 'linkedin_settings' in local_config:
            local_config['linkedin_settings']['timespan'] = f"r{timespan_seconds}"
            local_config['linkedin_settings']['days_to_scrape'] = days_to_scrape
        if 'indeed_settings' in local_config and 'search_config' in local_config['indeed_settings']:
            local_config['indeed_settings']['search_config']['max_listing_days'] = days_to_scrape

        all_new_jobs_df_list = []

        if source in ['linkedin', 'all']:
            scraping_status['message'] = "Scraping LinkedIn..."
            linkedin_df = scrape_linkedin(local_config, existing_urls)
            if not linkedin_df.empty:
                all_new_jobs_df_list.append(linkedin_df)

        if source in ['indeed', 'all']:
            scraping_status['message'] = "Scraping Indeed..."
            indeed_df = scrape_indeed(local_config, existing_urls)
            if not indeed_df.empty:
                all_new_jobs_df_list.append(indeed_df)

        num_added = 0
        if all_new_jobs_df_list:
            scraping_status['message'] = "Combining and saving new jobs..."
            final_df = pd.concat(all_new_jobs_df_list, ignore_index=True).drop_duplicates(subset=['job_url'])
            num_added = commit_jobs_to_db(conn, final_df, history_id)
        
        conn.execute("UPDATE scrape_history SET new_jobs_found = ? WHERE id = ?", (num_added, history_id))
        conn.commit()
        
        scraping_status['message'] = f"Scraping complete. Added {num_added} new jobs."
        conn.close()
        time.sleep(3)

    except Exception as e:
        scraping_status['message'] = f"An error occurred: {e}"
        import traceback
        traceback.print_exc()
        time.sleep(5)
    
    finally:
        scraping_status['is_running'] = False
        scraping_status['message'] = "Idle"

# --- FLASK ROUTES ---

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
    time_period_str = data.get('time_period_str', '7 Days')
    timespan = data.get('timespan', 86400 * 7)
    days = data.get('days', 7)
    management_option = data.get('management_option', 'add')

    thread = threading.Thread(target=perform_scraping_task, args=(source, time_period_str, timespan, days, management_option))
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

    # Applications Today
    today_start_str = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    if has_application_date_column:
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND application_date >= ?", (*applied_statuses, today_start_str))
        stats['applications_today'] = cursor.fetchone()[0]
    else:
        stats['applications_today'] = 0

    # Applications This Week
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday()) # Monday
    start_of_week_str = datetime.combine(start_of_week, datetime.min.time()).strftime('%Y-%m-%d %H:%M:%S')
    if has_application_date_column:
        cursor.execute(f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND application_date >= ?", (*applied_statuses, start_of_week_str))
        stats['applications_this_week'] = cursor.fetchone()[0]
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
```

**Next, `templates/dashboard.html` (New File):**
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Job Application Dashboard</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { font-family: sans-serif; margin: 20px; background-color: #f4f7f6; color: #333; }
        .dashboard-container { display: flex; flex-wrap: wrap; gap: 20px; justify-content: center; }
        .card {
            background-color: #fff;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            padding: 20px;
            flex-grow: 1;
            min-width: 200px; /* Ensure cards don't get too small */
        }
        .kpi-card { text-align: center; }
        .kpi-value { font-size: 2.5em; font-weight: bold; color: #007bff; }
        .kpi-label { font-size: 1em; color: #555; margin-top: 5px; }
        .chart-container {
            width: 100%;
            max-width: 48%; /* Adjust for two charts per row */
            min-width: 300px; /* Minimum width for charts */
            margin-bottom: 20px;
            background-color: #fff;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }
        #motivationalQuote {
            font-style: italic;
            text-align: center;
            margin-top: 20px;
            margin-bottom: 30px;
            padding: 20px;
            background-color: #e9ecef;
            border-radius: 8px;
            font-size: 1.1em;
        }
        nav a { margin-right: 15px; }
        .progress { height: 30px; font-size: 1rem; }
        .progress-bar { font-weight: bold; }

        /* Responsive adjustments */
        @media (max-width: 768px) {
            .chart-container {
                max-width: 100%; /* Full width on smaller screens */
            }
            .dashboard-container .card {
                flex-basis: calc(50% - 10px); /* Two cards per row, accounting for gap */
            }
        }
        @media (max-width: 576px) {
            .dashboard-container .card {
                flex-basis: 100%; /* One card per row on very small screens */
            }
        }
    </style>
</head>
<body>
    <div class="container-fluid">
        <nav class="navbar navbar-expand-lg navbar-light bg-light mb-4">
            <a class="navbar-brand" href="#">Job Tracker</a>
            <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarNav" aria-controls="navbarNav" aria-expanded="false" aria-label="Toggle navigation">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link" href="{{ url_for('home') }}">Jobs List</a>
                    </li>
                    <li class="nav-item active">
                        <a class="nav-link" href="{{ url_for('dashboard_page') }}">Dashboard <span class="sr-only">(current)</span></a>
                    </li>
                </ul>
            </div>
        </nav>

        <h1 class="mb-4 text-center">Job Application Dashboard</h1>

        <div id="motivationalQuote" class="mb-4 alert alert-info">
            Loading motivational quote...
        </div>

        <div class="dashboard-container mb-4">
            <div class="card kpi-card">
                <div class="kpi-value" id="jobsScraped24h">0</div>
                <div class="kpi-label">Jobs Scraped (Last 24h)</div>
            </div>
            <div class="card kpi-card">
                <div class="kpi-value" id="applicationsToday">0</div>
                <div class="kpi-label">Applications Today</div>
            </div>
            <div class="card kpi-card">
                <div class="kpi-value" id="applicationsThisWeek">0</div>
                <div class="kpi-label">Applications This Week</div>
            </div>
            <div class="card kpi-card">
                <div class="kpi-value" id="totalApplications">0</div>
                <div class="kpi-label">Total Applications</div>
            </div>
            <div class="card kpi-card">
                <div class="kpi-value" id="resumesCreatedToday">0</div>
                <div class="kpi-label">Resumes Created Today</div>
            </div>
             <div class="card kpi-card">
                <div class="kpi-value" id="totalResumesCreated">0</div>
                <div class="kpi-label">Total Resumes Created</div>
            </div>
        </div>

        <div class="card mb-4">
            <h5>Daily Application Goal</h5>
            <div id="dailyGoalGauge">
                <p>Applied Today: <span id="appliedTodayCount">0</span> / 50</p>
                <div class="progress">
                    <div id="dailyGoalProgress" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="50">0%</div>
                </div>
            </div>
        </div>

        <div class="dashboard-container mt-4">
            <div class="card chart-container">
                <h5 class="text-center">Applications Per Day (Last 7 Days)</h5>
                <canvas id="applicationsOverTimeChart"></canvas>
            </div>
            <div class="card chart-container">
                <h5 class="text-center">Applications by Source</h5>
                <canvas id="applicationsBySourceChart"></canvas>
            </div>
            <div class="card chart-container">
                <h5 class="text-center">Application Status Breakdown</h5>
                <canvas id="applicationStatusChart"></canvas>
            </div>
        </div>

    </div>

    <script src="{{ url_for('static', filename='js/dashboard.js') }}"></script>
    <!-- Bootstrap JS and Popper.js (optional, but good for some Bootstrap components) -->
    <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.5.4/dist/umd/popper.min.js"></script>
    <script src="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/js/bootstrap.min.js"></script>
</body>
</html>
```

Next, **`static/js/dashboard.js`** (New File):
```javascript
document.addEventListener('DOMContentLoaded', function() {
    const dailyGoal = 50;
    let applicationsOverTimeChartInstance = null;
    let applicationsBySourceChartInstance = null;
    let applicationStatusChartInstance = null;

    const chartColors = [
        'rgba(255, 99, 132, 0.7)',
        'rgba(54, 162, 235, 0.7)',
        'rgba(255, 206, 86, 0.7)',
        'rgba(75, 192, 192, 0.7)',
        'rgba(153, 102, 255, 0.7)',
        'rgba(255, 159, 64, 0.7)',
        'rgba(199, 199, 199, 0.7)',
        'rgba(83, 102, 83, 0.7)'
    ];

    const chartBorderColors = [
        'rgba(255, 99, 132, 1)',
        'rgba(54, 162, 235, 1)',
        'rgba(255, 206, 86, 1)',
        'rgba(75, 192, 192, 1)',
        'rgba(153, 102, 255, 1)',
        'rgba(255, 159, 64, 1)',
        'rgba(199, 199, 199, 1)',
        'rgba(83, 102, 83, 1)'
    ];


    function fetchDashboardData() {
        fetch('/api/dashboard_stats')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data) {
                    updateKPIs(data);
                    updateCharts(data);
                    updateDailyGoal(data.applications_today);
                } else {
                    console.error('No data received from /api/dashboard_stats');
                    setDefaultKPIs();
                    setDefaultCharts();
                    updateDailyGoal(0);
                }
            })
            .catch(error => {
                console.error('Error fetching dashboard stats:', error);
                setDefaultKPIs();
                setDefaultCharts();
                updateDailyGoal(0);
                document.getElementById('motivationalQuote').textContent = 'Error loading dashboard data. Please try again later.';
            });
    }

    function fetchMotivationalQuote() {
        fetch('/api/quote')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                const quoteElement = document.getElementById('motivationalQuote');
                if (data.quote && data.author) {
                    quoteElement.innerHTML = `"${data.quote}" - <em>${data.author}</em>`;
                } else {
                    quoteElement.textContent = 'Keep pushing, you are doing great!'; // Fallback
                }
            })
            .catch(error => {
                console.error('Error fetching motivational quote:', error);
                document.getElementById('motivationalQuote').textContent = 'Stay motivated! (Error fetching quote)'; // Fallback
            });
    }

    function setDefaultKPIs() {
        document.getElementById('jobsScraped24h').textContent = '0';
        document.getElementById('applicationsToday').textContent = '0';
        document.getElementById('applicationsThisWeek').textContent = '0';
        document.getElementById('totalApplications').textContent = '0';
        document.getElementById('resumesCreatedToday').textContent = '0';
        document.getElementById('totalResumesCreated').textContent = '0';
    }

    function updateKPIs(data) {
        document.getElementById('jobsScraped24h').textContent = data.jobs_scraped_last_24_hours !== undefined ? data.jobs_scraped_last_24_hours : 0;
        document.getElementById('applicationsToday').textContent = data.applications_today !== undefined ? data.applications_today : 0;
        document.getElementById('applicationsThisWeek').textContent = data.applications_this_week !== undefined ? data.applications_this_week : 0;
        document.getElementById('totalApplications').textContent = data.total_applications !== undefined ? data.total_applications : 0;
        document.getElementById('resumesCreatedToday').textContent = data.resumes_created_today !== undefined ? data.resumes_created_today : 0;
        document.getElementById('totalResumesCreated').textContent = data.resumes_created_total !== undefined ? data.resumes_created_total : 0;
    }

    function updateDailyGoal(appliedToday) {
        const appliedCountElement = document.getElementById('appliedTodayCount');
        const progressBarElement = document.getElementById('dailyGoalProgress');

        appliedToday = appliedToday || 0;
        appliedCountElement.textContent = appliedToday;

        const percentage = Math.min((appliedToday / dailyGoal) * 100, 100);
        progressBarElement.style.width = percentage + '%';
        progressBarElement.setAttribute('aria-valuenow', appliedToday);
        progressBarElement.textContent = `${Math.round(percentage)}%`;

        progressBarElement.classList.remove('bg-success', 'bg-warning', 'bg-info');
        if (percentage >= 100) {
            progressBarElement.classList.add('bg-success');
        } else if (percentage >= 50) {
            progressBarElement.classList.add('bg-warning');
        } else {
            progressBarElement.classList.add('bg-info');
        }
    }

    const defaultChartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                position: 'top',
            },
            tooltip: {
                enabled: true
            }
        }
    };

    const noDataConfig = (label) => ({
        labels: ['No Data'],
        datasets: [{
            label: label,
            data: [1], // Chart.js needs at least one data point to render
            backgroundColor: ['rgba(200, 200, 200, 0.2)'],
            borderColor: ['rgba(200, 200, 200, 1)'],
            borderWidth: 1
        }]
    });

    function updateCharts(data) {
        // Applications Over Time Chart
        const ctxTime = document.getElementById('applicationsOverTimeChart').getContext('2d');
        const timeLabels = data.applications_last_7_days ? data.applications_last_7_days.map(item => item.date.substring(5)) : []; // MM-DD format
        const timeData = data.applications_last_7_days ? data.applications_last_7_days.map(item => item.count) : [];

        if (applicationsOverTimeChartInstance) {
            applicationsOverTimeChartInstance.destroy();
        }
        applicationsOverTimeChartInstance = new Chart(ctxTime, {
            type: 'line',
            data: timeLabels.length > 0 ? {
                labels: timeLabels,
                datasets: [{
                    label: 'Applications per Day',
                    data: timeData,
                    borderColor: 'rgb(75, 192, 192)',
                    backgroundColor: 'rgba(75, 192, 192, 0.2)',
                    tension: 0.1,
                    fill: true
                }]
            } : noDataConfig('Applications per Day'),
            options: {
                ...defaultChartOptions,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                            precision: 0
                        }
                    }
                }
            }
        });

        // Applications by Source Chart
        const ctxSource = document.getElementById('applicationsBySourceChart').getContext('2d');
        const sourceLabels = data.applications_by_source && Object.keys(data.applications_by_source).length > 0 ? Object.keys(data.applications_by_source) : ['No Data'];
        const sourceData = data.applications_by_source && Object.keys(data.applications_by_source).length > 0 ? Object.values(data.applications_by_source) : [1];

        if (applicationsBySourceChartInstance) {
            applicationsBySourceChartInstance.destroy();
        }
        applicationsBySourceChartInstance = new Chart(ctxSource, {
            type: 'pie',
            data: {
                labels: sourceLabels,
                datasets: [{
                    label: 'Applications by Source',
                    data: sourceData,
                    backgroundColor: chartColors.slice(0, sourceLabels.length),
                    borderColor: chartBorderColors.slice(0, sourceLabels.length),
                    borderWidth: 1
                }]
            },
            options: defaultChartOptions
        });

        // Application Status Breakdown Chart
        const ctxStatus = document.getElementById('applicationStatusChart').getContext('2d');
        const statusLabels = data.application_status_breakdown && Object.keys(data.application_status_breakdown).length > 0 ? Object.keys(data.application_status_breakdown) : ['No Data'];
        const statusData = data.application_status_breakdown && Object.keys(data.application_status_breakdown).length > 0 ? Object.values(data.application_status_breakdown) : [1];

        if (applicationStatusChartInstance) {
            applicationStatusChartInstance.destroy();
        }
        applicationStatusChartInstance = new Chart(ctxStatus, {
            type: 'doughnut',
            data: {
                labels: statusLabels,
                datasets: [{
                    label: 'Application Status',
                    data: statusData,
                    backgroundColor: chartColors.slice(0, statusLabels.length),
                    borderColor: chartBorderColors.slice(0, statusLabels.length),
                    borderWidth: 1
                }]
            },
            options: defaultChartOptions
        });
    }

    function setDefaultCharts() {
        const ctxTime = document.getElementById('applicationsOverTimeChart').getContext('2d');
        if (applicationsOverTimeChartInstance) applicationsOverTimeChartInstance.destroy();
        applicationsOverTimeChartInstance = new Chart(ctxTime, { type: 'line', data: noDataConfig('Applications per Day'), options: {...defaultChartOptions, scales: { y: { beginAtZero: true, ticks: { stepSize: 1, precision: 0 }}}} });

        const ctxSource = document.getElementById('applicationsBySourceChart').getContext('2d');
        if (applicationsBySourceChartInstance) applicationsBySourceChartInstance.destroy();
        applicationsBySourceChartInstance = new Chart(ctxSource, { type: 'pie', data: noDataConfig('Applications by Source'), options: defaultChartOptions });

        const ctxStatus = document.getElementById('applicationStatusChart').getContext('2d');
        if (applicationStatusChartInstance) applicationStatusChartInstance.destroy();
        applicationStatusChartInstance = new Chart(ctxStatus, { type: 'doughnut', data: noDataConfig('Application Status'), options: defaultChartOptions });
    }

    // Initial data load
    fetchDashboardData();
    fetchMotivationalQuote();

    // Optional: Refresh data periodically
    // setInterval(fetchDashboardData, 60000); // Refresh every 60 seconds
    // setInterval(fetchMotivationalQuote, 300000); // Refresh quote every 5 minutes
});
```

And finally, the updated **`templates/jobs.html`**:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Unified Job Board</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}" />
    <style>
        /* Additional styles for better layout if needed */
        .action-btn { margin-right: 5px; margin-bottom: 5px; }
        .badge { display: inline-block; padding: .25em .4em; font-size: 75%; font-weight: 700; line-height: 1; text-align: center; white-space: nowrap; vertical-align: baseline; border-radius: .25rem; }
        .linkedin { background-color: #007bff; color: white; }
        .indeed { background-color: #28a745; color: white; }
        .table th, .table td { vertical-align: middle; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header-container">
            <h1>My Job Feed</h1>
            <span id="job-count"></span>
        </div>

        <!-- Stats -->
        <div id="stats-container" class="stats-container">Loading stats...</div>

        <!-- Scrape Controls -->
        <div class="controls-container">
            <fieldset>
                <legend>Scrape Controls</legend>
                <div class="controls-grid">
                    <div class="control-group">
                        <label for="source-select">Source:</label>
                        <select id="source-select" onchange="updateTimeUnitOptions()">
                            <option value="all" selected>All Sources</option>
                            <option value="linkedin">LinkedIn Only</option>
                            <option value="indeed">Indeed Only</option>
                        </select>
                    </div>
                    <div class="control-group">
                        <label for="time-value">Time Period:</label>
                        <input type="number" id="time-value" value="7" min="1" />
                        <select id="time-unit"></select>
                    </div>
                    <div class="control-group">
                        <label>Scrape Mode:</label>
                        <div class="radio-group">
                            <input type="radio" id="mode-add" name="scrape-mode" value="add" checked />
                            <label for="mode-add">Add to Inbox</label>
                            <input type="radio" id="mode-archive" name="scrape-mode" value="archive" />
                            <label for="mode-archive">Archive Inbox & Add</label>
                            <input type="radio" id="mode-delete" name="scrape-mode" value="delete" />
                            <label for="mode-delete">Clear Inbox & Add</label>
                        </div>
                    </div>
                </div>
                <div class="scrape-action-bar">
                    <button id="scrape-button" onclick="startScrape()">Scrape New Jobs</button>
                    <span id="scrape-status">Status: Idle</span>
                </div>
            </fieldset>
        </div>

        <!-- Tabs -->
        <div class="tab-container">
            <button class="tab-link active" onclick="openTab('inbox')">Inbox</button>
            <button class="tab-link" onclick="openTab('want_to_apply')">Want to Apply</button>
            <button class="tab-link" onclick="openTab('applied')">Applied</button>
            <button class="tab-link" onclick="openTab('interviewing')">Interviewing</button>
            <button class="tab-link" onclick="openTab('offer')">Offer</button>
            <button class="tab-link" onclick="openTab('rejected')">Rejected</button>
            <button class="tab-link" onclick="openTab('archived')">Archived</button>
            <button class="tab-link" onclick="openResumeCreatorTab()">Create Resume/CV</button>
            <a href="{{ url_for('dashboard_page') }}" class="tab-link">Dashboard</a>
        </div>

        <!-- Jobs -->
        <div id="jobs-content">
            <table id="jobs-table" class="table table-striped">
                <thead>
                    <tr>
                        <th class="index-col">#</th>
                        <th>Source</th>
                        <th>Date Posted</th>
                        <th>Date Loaded</th>
                        <th>Title & Company</th>
                        <th>Location</th>
                        <th>Applied Date</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody id="jobs-tbody"></tbody>
            </table>
            <div id="loading-spinner" class="spinner"></div>
        </div>
        <div id="resume-creator-content" style="display: none;">
            <h2>Create Resume and Cover Letter</h2>
            <input type="hidden" id="resume-job-id" value="">
            <div><small>Job to tailor for: <span id="resume-job-title-display">None selected. Paste job description below or select a job from the list and click "Generate Resume/CV".</span></small></div>
            <textarea id="job-description-input" placeholder="Job description will be auto-filled if you use 'Generate Resume/CV' from a job row in Inbox/Want to Apply tabs." style="width: 98%; height: 150px; margin-bottom: 10px;"></textarea>
            <button id="generate-resume-cv-button" class="btn btn-primary">Generate Documents</button>
            <div id="resume-creator-status" style="margin-top: 10px; margin-bottom: 10px;"></div>
            <div id="pdf-preview-area" style="display: none; margin-top: 10px;">
                <div style="display: flex; justify-content: space-between; height: 600px;">
                    <iframe id="resume-preview-iframe" style="width: 49%; height: 100%; border: 1px solid #ccc;"></iframe>
                    <iframe id="cv-preview-iframe" style="width: 49%; height: 100%; border: 1px solid #ccc;"></iframe>
                </div>
            </div>
        </div>
    </div>

<script>
    let currentTab = 'inbox';
    let statusInterval;
    const timeUnitSelect = document.getElementById('time-unit');

    const timeOptions = {
        full: `
            <option value="seconds">Seconds</option>
            <option value="minutes">Minutes</option>
            <option value="hours">Hours</option>
            <option value="days" selected>Days</option>
            <option value="weeks">Weeks</option>
            <option value="months">Months</option>
        `,
        indeed: `
            <option value="days" selected>Days</option>
            <option value="weeks">Weeks</option>
            <option value="months">Months</option>
        `
    };
    function updateTimeUnitOptions() {
        const source = document.getElementById('source-select').value;
        timeUnitSelect.innerHTML = (source === 'indeed') ? timeOptions.indeed : timeOptions.full;
    }

    function fetchStats() {
        fetch('/get_stats') // This is the old endpoint, dashboard uses /api/dashboard_stats
            .then(res => res.json())
            .then(stats => {
                document.getElementById('stats-container').innerHTML = `<strong>Jobs Scraped in Last 24 Hours:</strong> ${stats.jobs_last_24_hours}`;
            })
            .catch(err => {
                document.getElementById('stats-container').textContent = 'Could not load stats.';
                console.error('Error fetching stats:', err);
            });
    }

    function openTab(status) {
        currentTab = status;
        document.getElementById('resume-creator-content').style.display = 'none';
        document.getElementById('jobs-content').style.display = 'block';
        document.getElementById('stats-container').style.display = 'block';
        document.querySelector('.controls-container').style.display = 'block';

        document.querySelectorAll('.tab-link').forEach(link => link.classList.remove('active'));
        const tabButton = Array.from(document.querySelectorAll('.tab-link')).find(el => el.textContent.toLowerCase().includes(status.replace('_', ' ')));
        if (tabButton) {
            tabButton.classList.add('active');
        }
        fetchJobs(status);
    }

    function openResumeCreatorTab(jobId = null, jobTitle = null, jobDescription = null) {
        currentTab = 'resume_creator';
        document.getElementById('jobs-content').style.display = 'none';
        document.getElementById('stats-container').style.display = 'none';
        document.querySelector('.controls-container').style.display = 'none';
        document.getElementById('resume-creator-content').style.display = 'block';

        document.querySelectorAll('.tab-link').forEach(link => link.classList.remove('active'));
        const resumeTabButton = Array.from(document.querySelectorAll('.tab-link')).find(el => el.textContent === 'Create Resume/CV');
        if (resumeTabButton) {
            resumeTabButton.classList.add('active');
        }

        const jobDescInput = document.getElementById('job-description-input');
        const resumeJobIdInput = document.getElementById('resume-job-id');
        const resumeJobTitleDisplay = document.getElementById('resume-job-title-display');

        if (jobId && jobDescription) {
            resumeJobIdInput.value = jobId;
            jobDescInput.value = jobDescription; // Ensure this is the actual description text
            resumeJobTitleDisplay.textContent = jobTitle ? `For: ${jobTitle}` : `For Job ID: ${jobId}`;
        } else {
            resumeJobIdInput.value = '';
            // Do not clear jobDescInput if user manually pasted something
            // jobDescInput.value = '';
            resumeJobTitleDisplay.textContent = 'None selected. Paste job description below or select a job from the list and click "Generate Resume/CV".';
        }

        document.getElementById('resume-creator-status').textContent = '';
        document.getElementById('pdf-preview-area').style.display = 'none';
        document.getElementById('resume-preview-iframe').src = 'about:blank';
        document.getElementById('cv-preview-iframe').src = 'about:blank';
    }

    function fetchJobs(status) {
        const tbody = document.getElementById('jobs-tbody');
        const spinner = document.getElementById('loading-spinner');
        const jobCountSpan = document.getElementById('job-count');

        spinner.style.display = 'block';
        tbody.innerHTML = '';
        jobCountSpan.textContent = '';

        fetch(`/get_jobs?status=${status}`)
            .then(res => res.json())
            .then(jobs => {
                spinner.style.display = 'none';
                jobCountSpan.textContent = `(${jobs.length} jobs)`;
                if (!jobs || jobs.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8">No jobs in this category.</td></tr>'; // Adjusted colspan
                    return;
                }

                jobs.forEach((job, index) => {
                    const row = document.createElement('tr');
                    row.id = `job-row-${job.id}`;

                    let actionButtons = '';
                    const jobDescriptionEscaped = job.job_description ? job.job_description.replace(/'/g, "\\'").replace(/\n/g, '\\n').replace(/\r/g, '') : '';
                    const jobTitleEscaped = job.title ? job.title.replace(/'/g, "\\'") : 'N/A';

                    if (status === 'inbox' || status === 'want_to_apply') {
                         actionButtons += `<button class="action-btn btn btn-sm btn-info" onclick="openResumeCreatorTab(${job.id}, '${jobTitleEscaped}', '${jobDescriptionEscaped}')">Generate Resume/CV</button>`;
                    }

                    if (status === 'inbox') {
                        actionButtons += `<button class="action-btn btn btn-sm btn-primary" onclick="updateJobStatus(${job.id}, 'want_to_apply')">Bookmark</button>`;
                        actionButtons += `<button class="action-btn btn btn-sm btn-success" onclick="updateJobStatus(${job.id}, 'applied')">Mark Applied</button>`;
                    } else if (status === 'want_to_apply') {
                        actionButtons += `<button class="action-btn btn btn-sm btn-success" onclick="updateJobStatus(${job.id}, 'applied')">Mark Applied</button>`;
                    } else if (status === 'applied' || status === 'interviewing' || status === 'offer' || status === 'rejected') {
                        actionButtons += `
                            <select class="form-control form-control-sm d-inline-block" style="width: auto;" onchange="updateJobStatus(${job.id}, this.value)">
                                <option value="applied" ${job.status === 'applied' ? 'selected' : ''}>Applied</option>
                                <option value="interviewing" ${job.status === 'interviewing' ? 'selected' : ''}>Interviewing</option>
                                <option value="offer" ${job.status === 'offer' ? 'selected' : ''}>Offer</option>
                                <option value="rejected" ${job.status === 'rejected' ? 'selected' : ''}>Rejected</option>
                                <option value="archived" ${job.status === 'archived' ? 'selected' : ''}>Archive</option>
                            </select>
                         `;
                    } else if (status === 'archived') {
                         actionButtons += `<button class="action-btn btn btn-sm btn-warning" onclick="updateJobStatus(${job.id}, 'inbox')">Move to Inbox</button>`;
                    }


                    const sourceBadge = job.source === 'LinkedIn' ? '<span class="badge linkedin">LI</span>' : '<span class="badge indeed">IN</span>';
                    let displayDate = 'N/A';
                    if (job.date) {
                        try {
                            const parsedDate = new Date(job.date);
                            if (!isNaN(parsedDate)) {
                                displayDate = parsedDate.toLocaleDateString();
                            }
                        } catch (e) { /* ignore date parsing errors */ }
                    }
                    let scrapedDate = 'N/A';
                    if (job.date_loaded) {
                        const parsedScrapedDate = new Date(job.date_loaded);
                        if (!isNaN(parsedScrapedDate)) {
                            scrapedDate = parsedScrapedDate.toLocaleString();
                        }
                    }
                    let applicationDateStr = 'N/A';
                    if (job.application_date) {
                        const parsedAppDate = new Date(job.application_date);
                        if (!isNaN(parsedAppDate)) {
                            applicationDateStr = parsedAppDate.toLocaleDateString();
                        }
                    }

                    row.innerHTML = `
                        <td class="index-col">${index + 1}</td>
                        <td>${sourceBadge}</td>
                        <td>${displayDate}</td>
                        <td>${scrapedDate}</td>
                        <td>
                            <a href="${job.job_url || '#'}" target="_blank" title="${job.job_description || ''}">${job.title || 'No Title'}</a>
                            <div class="company-name">${job.company || 'No Company'}</div>
                        </td>
                        <td>${job.location || 'No Location'}</td>
                        <td>${applicationDateStr}</td>
                        <td class="actions">${actionButtons}</td>
                    `;
                    tbody.appendChild(row);
                });
            })
            .catch(err => {
                spinner.style.display = 'none';
                console.error('Error fetching jobs:', err);
                tbody.innerHTML = '<tr><td colspan="8">Error fetching jobs.</td></tr>'; // Adjusted colspan
            });
    }

    function updateJobStatus(jobId, newStatus) {
        fetch(`/update_job_status/${jobId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ status: newStatus })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                const row = document.getElementById(`job-row-${jobId}`);
                if (row && (newStatus === 'archived' || newStatus === 'applied' && currentTab !== 'applied')) { // Remove if status changes tab or archived
                    row.style.opacity = '0';
                    setTimeout(() => fetchJobs(currentTab), 300);
                } else {
                    fetchJobs(currentTab); // Refresh current tab to show updated status or application date
                }
                if (typeof fetchDashboardData === 'function') { // If dashboard.js is loaded and has this function
                    fetchDashboardData(); // Refresh dashboard stats
                }
            } else {
                alert(`Error updating status: ${data.error}`);
            }
        })
        .catch(err => console.error('Error updating job status:', err));
    }

    function startScrape() {
        const managementOption = document.querySelector('input[name="scrape-mode"]:checked').value;
        const source = document.getElementById('source-select').value;
        const timeValue = parseInt(document.getElementById('time-value').value, 10);
        const timeUnit = timeUnitSelect.value;

        let daysToScrape = timeValue; // Default to days
        let timespanSeconds = timeValue * 86400; // Default to days in seconds

        switch (timeUnit) {
            case 'seconds':
                timespanSeconds = timeValue;
                daysToScrape = Math.ceil(timeValue / 86400); // Approximate days for Indeed
                break;
            case 'minutes':
                timespanSeconds = timeValue * 60;
                daysToScrape = Math.ceil(timeValue / (24 * 60)); // Approximate days
                break;
            case 'hours':
                timespanSeconds = timeValue * 3600;
                daysToScrape = Math.ceil(timeValue / 24); // Approximate days
                break;
            case 'weeks':
                daysToScrape = timeValue * 7;
                timespanSeconds = daysToScrape * 86400;
                break;
            case 'months': // Approximate as 30 days per month
                daysToScrape = timeValue * 30;
                timespanSeconds = daysToScrape * 86400;
                break;
        }


        document.getElementById('scrape-button').disabled = true;
        document.getElementById('scrape-status').textContent = 'Status: Starting...';
        statusInterval = setInterval(checkScrapeStatus, 2000);

        fetch('/scrape', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                source: source,
                time_period_str: `${timeValue} ${timeUnit}`, // For logging
                timespan: timespanSeconds, // For LinkedIn
                days: daysToScrape,         // For Indeed
                management_option: managementOption
            })
        })
        .catch(err => {
            document.getElementById('scrape-status').textContent = `Error: ${err.message}`;
            document.getElementById('scrape-button').disabled = false;
            clearInterval(statusInterval);
        });
    }

    function checkScrapeStatus() {
        fetch('/scrape_status')
            .then(res => res.json())
            .then(status => {
                document.getElementById('scrape-status').textContent = `Status: ${status.message}`;
                if (!status.is_running) {
                    clearInterval(statusInterval);
                    document.getElementById('scrape-button').disabled = false;
                    if (status.message.includes('complete')) {
                        openTab('inbox'); // Refresh the inbox
                        fetchStats(); // Refresh the old stats display
                        if (typeof fetchDashboardData === 'function') { // If dashboard is open or its JS loaded
                             // No direct call to fetchDashboardData() here, as it's for the dashboard page.
                             // The dashboard will fetch its own data when loaded.
                        }
                    }
                }
            })
            .catch(() => {
                clearInterval(statusInterval);
                document.getElementById('scrape-button').disabled = false;
            });
    }

    document.getElementById('generate-resume-cv-button').addEventListener('click', function() {
        const jobDesc = document.getElementById('job-description-input').value;
        const jobId = document.getElementById('resume-job-id').value;
        const statusElement = document.getElementById('resume-creator-status');
        const generateButton = this;
        const pdfPreviewArea = document.getElementById('pdf-preview-area');
        const resumeIframe = document.getElementById('resume-preview-iframe');
        const cvIframe = document.getElementById('cv-preview-iframe');

        if (!jobDesc.trim()) {
            statusElement.textContent = 'Please paste a job description first.';
            statusElement.className = 'status-error';
            return;
        }

        statusElement.textContent = 'Generating documents... Please wait.';
        statusElement.className = 'status-info';
        generateButton.disabled = true;
        pdfPreviewArea.style.display = 'none';
        resumeIframe.src = 'about:blank';
        cvIframe.src = 'about:blank';

        const payload = { job_description: jobDesc };
        if (jobId) {
            payload.job_id = parseInt(jobId, 10);
        }

        fetch('/generate_documents', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errData => {
                    let errorMessage = errData.error || `Server responded with status: ${response.status}`;
                    if (errData.details) {
                        errorMessage += ` - ${errData.details}`;
                    }
                    throw new Error(errorMessage);
                }).catch(parsingError => { // Fallback if backend error isn't JSON or parsing fails
                    console.error('Error parsing JSON error response:', parsingError);
                    return response.text().then(textData => {
                        throw new Error(textData || `Server responded with status: ${response.status}`);
                    });
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                resumeIframe.src = data.resume_pdf_url;
                cvIframe.src = data.cover_letter_pdf_url;
                pdfPreviewArea.style.display = 'block';
                statusElement.textContent = 'Documents generated successfully!';
                statusElement.className = 'status-success';
                if (typeof fetchDashboardData === 'function') { // If dashboard.js is loaded (e.g. if this was on dashboard)
                    fetchDashboardData(); // Refresh dashboard stats if resume generated
                }
            } else {
                statusElement.textContent = `Error: ${data.error || 'Unknown error'} - ${data.details || ''}`;
                statusElement.className = 'status-error';
                console.error('Error generating documents:', data);
            }
        })
        .catch(error => {
            statusElement.textContent = `Request failed: ${error.message}`;
            statusElement.className = 'status-error';
            console.error('Fetch error:', error);
        })
        .finally(() => {
            generateButton.disabled = false;
        });
    });

    // Initial setup
    updateTimeUnitOptions();
    fetchStats();
    openTab(currentTab); // Load initial tab

});
</script>
</body>
</html>
```

Please replace/create these files. After restarting your Flask application (`python app.py`) and clearing your browser cache (or using an incognito window), the `/dashboard` route should now load correctly and display the dashboard.

Let me know if you encounter any further issues!
