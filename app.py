import sqlite3
import json
import os
import threading
import time
import copy
import pandas as pd
from flask import Flask, render_template, jsonify, request, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import subprocess
import sys
import re

# Import the scraper functions directly
from scrapers.linkedin_scraper import scrape_linkedin
from scrapers.indeed_scraper import scrape_indeed

# --- Global variable for scraping status ---
scraping_status = {
    "is_running": False,
    "message": "Idle"
}

# --- Constants ---
RESUME_CREATION_FOLDER = 'resume_cover_creation'

def load_config(file_name="config.json"):
    with open(file_name) as f:
        return json.load(f)

config = load_config()
app = Flask(__name__)

# --- DATABASE INITIALIZATION AND HELPERS ---

def get_db_connection():
    db_path = config['app_settings']['db_path']
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return sqlite3.connect(db_path, check_same_thread=False)

def initialize_database():
    """Creates/verifies the database schema on startup."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scrape_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scrape_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source_filter TEXT,
            time_period_scraped TEXT,
            new_jobs_found INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, company TEXT, location TEXT, date TEXT,
            job_url TEXT UNIQUE, job_description TEXT, source TEXT, status TEXT DEFAULT 'inbox',
            date_loaded DATETIME, scrape_history_id INTEGER,
            FOREIGN KEY (scrape_history_id) REFERENCES scrape_history(id)
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
    table_name = config['app_settings']['jobs_tablename']
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
    
    columns_to_insert = ['title', 'company', 'location', 'date', 'job_url', 
                         'job_description', 'source', 'status', 'date_loaded', 'scrape_history_id']
    
    # Ensure only columns that exist in the DataFrame are used
    final_columns = [col for col in columns_to_insert if col in new_jobs_df.columns]
    
    new_jobs_df[final_columns].to_sql(table_name, conn, if_exists='append', index=False)
    return len(new_jobs_df)

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
        cursor.execute(f"SELECT job_url FROM jobs")
        existing_urls = {row[0] for row in cursor.fetchall()}
        
        local_config = copy.deepcopy(config)
        local_config['linkedin_settings']['timespan'] = f"r{timespan_seconds}"
        local_config['linkedin_settings']['days_to_scrape'] = days_to_scrape
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
    
    scraping_status['is_running'] = False
    scraping_status['message'] = "Idle"

# --- FLASK ROUTES ---

@app.route('/')
def home():
    return render_template('jobs.html')

@app.route('/get_jobs')
def get_jobs():
    status = request.args.get('status', 'inbox')
    jobs_list = []
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = "SELECT rowid as id, * FROM jobs WHERE status = ? ORDER BY id DESC"
    cursor.execute(query, (status,))
    rows = cursor.fetchall()
    for row in rows:
        jobs_list.append(dict(row))
    conn.close()
    return jsonify(jobs_list)

@app.route('/update_job_status/<int:job_id>', methods=['POST'])
def update_job_status(job_id):
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "New status not provided."}), 400
    conn = get_db_connection()
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
    conn.commit()
    conn.close()
    return jsonify({"success": f"Job {job_id} status updated to {new_status}."})

@app.route('/scrape', methods=['POST'])
def scrape():
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
def get_stats():
    stats = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    twenty_four_hours_ago = datetime.now() - timedelta(hours=24)
    query = "SELECT SUM(new_jobs_found) FROM scrape_history WHERE scrape_timestamp >= ?"
    cursor.execute(query, (twenty_four_hours_ago,))
    result = cursor.fetchone()[0]
    stats['jobs_last_24_hours'] = result if result is not None else 0
    conn.close()
    return jsonify(stats)


@app.route('/generate_documents', methods=['POST'])
def generate_documents():
    try:
        data = request.get_json()
        job_description = data.get('job_description')

        if not job_description:
            return jsonify({"error": "Job description is required"}), 400

        job_desc_file_path = os.path.join(RESUME_CREATION_FOLDER, 'job_description.txt')

        with open(job_desc_file_path, 'w', encoding='utf-8') as f:
            f.write(job_description)

        # Command to run: python create_resume.py job_description.txt
        # CWD will be RESUME_CREATION_FOLDER
        cmd = [sys.executable, 'create_resume.py', 'job_description.txt']
        
        app.logger.info(f"Running command: {' '.join(cmd)} in CWD: {RESUME_CREATION_FOLDER}")

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=RESUME_CREATION_FOLDER,
            encoding='utf-8' # Ensure consistent encoding
        )

        if process.returncode != 0:
            app.logger.error(f"Error generating documents. Return code: {process.returncode}")
            app.logger.error(f"Stderr: {process.stderr}")
            app.logger.error(f"Stdout: {process.stdout}") # Log stdout as well for more context
            return jsonify({
                "error": "Failed to generate documents",
                "details": process.stderr if process.stderr else "Unknown error, check logs."
            }), 500

        app.logger.info(f"Document generation script stdout: {process.stdout}")
        
        resume_pdf_filename = None
        # Adjusted regex to be more flexible with output messages.
        # Example: "Successfully created tailored_resume_1.pdf and tailored_resume_1_cover_letter.pdf"
        # Or: "Successfully created tailored_resume.pdf" (if only resume is mentioned first)
        match = re.search(r"Successfully created (tailored_resume(?:_\d+)?\.pdf)", process.stdout)
        if match:
            resume_pdf_filename = match.group(1)
        
        if not resume_pdf_filename:
            app.logger.error(f"Could not determine resume PDF filename from script output: {process.stdout}")
            return jsonify({
                "error": "Could not determine resume PDF filename from script output.",
                "details": process.stdout # Send stdout for debugging on client side if needed
            }), 500

        # Derive cover letter filename: e.g., tailored_resume_1.pdf -> tailored_resume_1_cover_letter.pdf
        cover_letter_pdf_filename = resume_pdf_filename.replace('.pdf', '_cover_letter.pdf')
        
        # Verify that the generated files actually exist before returning success
        expected_resume_path = os.path.join(RESUME_CREATION_FOLDER, resume_pdf_filename)
        expected_cover_letter_path = os.path.join(RESUME_CREATION_FOLDER, cover_letter_pdf_filename)

        if not os.path.exists(expected_resume_path):
            app.logger.error(f"Generated resume PDF not found at: {expected_resume_path}")
            return jsonify({"error": "Resume PDF file not found after generation.", "details": resume_pdf_filename}), 500
        
        # Cover letter might be optional depending on the script, so we don't strictly require it to exist
        # unless the script output explicitly states it was created.
        # For now, we assume if resume is made, cover letter should also be.

        return jsonify({
            "success": True,
            "resume_pdf_url": f"/serve_pdf/{resume_pdf_filename}",
            "cover_letter_pdf_url": f"/serve_pdf/{cover_letter_pdf_filename}"
        })

    except Exception as e:
        app.logger.exception("Error in /generate_documents") # This will log the full traceback
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500


@app.route('/serve_pdf/<path:filename>')
def serve_pdf(filename):
    # Security: Ensure filename is safe and only serves from the intended directory
    # os.path.normpath helps prevent directory traversal, but send_from_directory is generally safe.
    safe_filename = os.path.normpath(filename)
    if os.path.isabs(safe_filename) or safe_filename.startswith(".."): # Basic check
        return jsonify({"error": "Invalid filename"}), 400
    app.logger.info(f"Serving PDF: {safe_filename} from {RESUME_CREATION_FOLDER}")
    return send_from_directory(RESUME_CREATION_FOLDER, safe_filename, as_attachment=False)


if __name__ == "__main__":
    initialize_database()
    app.run(debug=True, port=5001)
