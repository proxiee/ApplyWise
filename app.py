import sqlite3
import json
import os
import threading
import time
import copy
import pandas as pd
from flask import Flask, render_template, jsonify, request, send_from_directory, redirect, url_for, flash
from flask_cors import CORS
from datetime import datetime, timedelta, date
import subprocess
import sys
import re
import requests
from flask_login import LoginManager, UserMixin, login_required, current_user

# --- Import Auth Blueprint ---
from auth import auth_bp, init_auth

# --- Import the scraper functions (your existing code) ---
try:
    from scrapers.linkedin_scraper import scrape_linkedin
    from scrapers.indeed_scraper import scrape_indeed
except ImportError as e: # 
    print(f"Error importing scrapers: {e}. Using dummy functions.") # 
    def scrape_linkedin(config, existing_urls): return pd.DataFrame() # 
    def scrape_indeed(config, existing_urls): return pd.DataFrame() # 

# --- Global variable for scraping status ---
scraping_status = {"is_running": False, "message": "Idle"}

# --- Constants ---
RESUME_CREATION_FOLDER = 'resume_cover_creation'

# --- App Initialization ---
app = Flask(__name__)
# IMPORTANT: You must set a secret key for session management
app.config['SECRET_KEY'] = 'a-super-secret-key-that-you-should-change'
CORS(app)

# --- Flask-Login Initialization ---
login_manager = LoginManager()
login_manager.init_app(app)
# If a user tries to access a page that requires login, redirect them to the login page
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'


# --- User Loader for Flask-Login ---
class User(UserMixin):
    def __init__(self, id, email, username): # 
        self.id = id # 
        self.email = email # 
        self.username = username # 

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    conn.close()
    if user_row:
        return User(id=user_row['id'], email=user_row['email'], username=user_row['username'])
    return None

# --- Configuration Loading ---
def load_config(file_name="config.json"):
    try: # 
        with open(file_name) as f: # 
            return json.load(f) # 
    except (FileNotFoundError, json.JSONDecodeError) as e: # 
        print(f"Error loading config file '{file_name}': {e}. Exiting.") # 
        sys.exit(1) # 

config = load_config()

# --- DATABASE INITIALIZATION AND HELPERS ---
def get_db_connection():
    db_path = config.get('app_settings', {}).get('db_path', 'data/jobs.db')
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """Creates/verifies ALL database tables on startup."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- NEW: users table --- 
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """) # 

    # In the initialize_database function, modify the CREATE TABLE for user_resume_data

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_resume_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        name TEXT,
        email TEXT,
        phone TEXT,
        linkedin TEXT,
        github TEXT,
        summary TEXT,
        education TEXT, -- Storing as JSON 
        experience TEXT, -- Storing as JSON 
        projects TEXT, -- Storing as JSON 
        skills TEXT, -- Storing as JSON 
        activities TEXT, -- Storing as JSON 
        custom_sections TEXT, -- <<< ADD THIS LINE
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """)

    # Your existing table initializations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scrape_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scrape_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        source_filter TEXT,
        time_period_scraped TEXT,
        new_jobs_found INTEGER,
        user_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    """) # 
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT, company TEXT, location TEXT, date TEXT,
        job_url TEXT, job_description TEXT, source TEXT,
        status TEXT DEFAULT 'inbox',
        date_loaded DATETIME,
        application_date DATETIME,
        scrape_history_id INTEGER,
        user_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id), 
        FOREIGN KEY (scrape_history_id) REFERENCES scrape_history(id),
        UNIQUE(job_url, user_id)           
    )
    """) # 
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resume_generations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        user_id INTEGER NOT NULL,
        generation_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs(id), 
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """) # 
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cover_letter_generations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER,
        user_id INTEGER NOT NULL,
        generation_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs(id),
         FOREIGN KEY (user_id) REFERENCES users(id) 
    )
    """) # 
    conn.commit()
    conn.close() # 
    print("Database initialized/verified successfully.") # 

    # Ensure resume creation directory exists
    if not os.path.exists(RESUME_CREATION_FOLDER):
        os.makedirs(RESUME_CREATION_FOLDER)

# --- Initialize the Auth Blueprint ---
init_auth(app, User, get_db_connection)
app.register_blueprint(auth_bp)

# --- CORE SCRAPING AND DATABASE LOGIC ---

def commit_jobs_to_db(conn, df, history_id, user_id):
    table_name = config.get('app_settings', {}).get('jobs_tablename', 'jobs')
    print(f"\n--- commit_jobs_to_db called for User ID: {user_id} ---") # 
    if df.empty:
        return 0

    cursor = conn.cursor()
    cursor.execute(f"SELECT job_url FROM {table_name} WHERE user_id = ?", (user_id,)) # 
    existing_urls = {row[0] for row in cursor.fetchall()}

    if 'job_url' not in df.columns:
        return 0

    new_jobs_df = df[~df['job_url'].isin(existing_urls)].copy()
    if new_jobs_df.empty: # 
        return 0

    new_jobs_df['user_id'] = user_id
    new_jobs_df['date_loaded'] = pd.to_datetime('now').strftime("%Y-%m-%d %H:%M:%S")
    new_jobs_df['status'] = 'inbox' # 
    new_jobs_df['scrape_history_id'] = history_id
    new_jobs_df['application_date'] = None

    columns_to_insert = [ # 
        'title', 'company', 'location', 'date', 'job_url', # 
        'job_description', 'source', 'status', 'date_loaded', # 
        'application_date', 'scrape_history_id', 'user_id' # 
    ]

    df_to_insert = new_jobs_df[[col for col in columns_to_insert if col in new_jobs_df.columns]]

    try:
        df_to_insert.to_sql(table_name, conn, if_exists='append', index=False)
        print(f"Successfully inserted {len(df_to_insert)} new jobs into '{table_name}' for user {user_id}.")
    except Exception as e: # 
        print(f"ERROR: Failed to insert jobs into database for user {user_id}: {e}") # 
        import traceback
        traceback.print_exc()
        return 0
    return len(df_to_insert)

def perform_scraping_task(source, time_period_str, timespan_seconds, days_to_scrape, management_option, location, keywords, user_id):
    global scraping_status
    scraping_status['is_running'] = True
    print(f"\n--- Initiating scraping task for source: {source} for User ID: {user_id} ---")
    try:
        conn = get_db_connection()

        if management_option == 'archive':
            scraping_status['message'] = "Archiving old jobs..."
            conn.execute("UPDATE jobs SET status = 'archived' WHERE status = 'inbox' AND user_id = ?", (user_id,))
            conn.commit()
        elif management_option == 'delete':
            scraping_status['message'] = "Deleting old jobs..."
            conn.execute("DELETE FROM jobs WHERE status = 'inbox' AND user_id = ?", (user_id,))
            conn.commit()

        scraping_status['message'] = "Creating scrape history record..."
        history_cursor = conn.cursor()
        history_cursor.execute(
            "INSERT INTO scrape_history (source_filter, time_period_scraped, new_jobs_found, user_id) VALUES (?, ?, ?, ?)",
            (source, time_period_str, 0, user_id)
        )
        history_id = history_cursor.lastrowid
        conn.commit()

        cursor = conn.cursor()
        cursor.execute(f"SELECT job_url FROM jobs WHERE user_id = ?", (user_id,))
        existing_urls = {row[0] for row in cursor.fetchall()}
        print(f"Fetched {len(existing_urls)} existing URLs from DB for user {user_id}.")

        local_config = copy.deepcopy(config)

        # --- FIX: ADD THIS LOGIC BLOCK BACK IN ---
        # For LinkedIn
        if source in ['linkedin', 'all']:
            if 'linkedin_settings' in local_config:
                if 'search_queries' not in local_config['linkedin_settings'] or not local_config['linkedin_settings']['search_queries']:
                    local_config['linkedin_settings']['search_queries'] = [{}]
                if keywords:
                    local_config['linkedin_settings']['search_queries'][0]['keywords'] = keywords
                if location:
                    local_config['linkedin_settings']['search_queries'][0]['location'] = location
                local_config['linkedin_settings']['timespan'] = f"r{timespan_seconds}"
                local_config['linkedin_settings']['days_to_scrape'] = days_to_scrape
                print(f"LinkedIn settings updated for scrape: {local_config['linkedin_settings']}")

        # For Indeed
        if source in ['indeed', 'all']:
            if 'indeed_settings' in local_config and 'search_config' in local_config['indeed_settings']:
                if keywords:
                    local_config['indeed_settings']['search_config']['keywords'] = [k.strip() for k in keywords.split(',') if k.strip()]
                if location:
                    local_config['indeed_settings']['search_config']['city'] = location
                local_config['indeed_settings']['search_config']['max_listing_days'] = days_to_scrape
                print(f"Indeed settings updated for scrape: {local_config['indeed_settings']}")
        # --- END OF FIX ---

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
            num_added = commit_jobs_to_db(conn, final_df, history_id, user_id)
        else:
            print("No jobs found by any scraper to combine and save.")

        conn.execute("UPDATE scrape_history SET new_jobs_found = ? WHERE id = ?", (num_added, history_id))
        conn.commit()

        scraping_status['message'] = f"Scraping complete. Added {num_added} new jobs."
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
@app.route('/')
@login_required
def home():
    return render_template('jobs.html')

def parse_form_data(form):
    """Parses the complex form data into a structured dictionary."""
    data = {'name': form.get('name'), 'email': form.get('email'), 'phone': form.get('phone'),
            'linkedin': form.get('linkedin'), 'github': form.get('github'), 'summary': form.get('summary')}

    skills = {} # 
    skill_keys = [k for k in form if k.startswith('skill_category_')]
    for key in skill_keys:
        index = key.split('_')[-1]
        category = form.get(f'skill_category_{index}')
        value = form.get(f'skill_value_{index}')
        if category:
            skills[category] = value
    data['skills'] = json.dumps(skills)

    for section in ['experience', 'education', 'project', 'activity']:
        items = [] # 
        all_section_keys = [k for k in form if k.startswith(f'{section}_')] # 
        if not all_section_keys:
            indices = []
        else:
            indices = sorted(list(set(key.split('_')[-1] for key in all_section_keys)))

        for index in indices:
            item = {}
            primary_field = f'{section}_title_{index}' if section == 'experience' else f'{section}_name_{index}' # 
            if section == 'education': primary_field = f'{section}_university_{index}'

            if not form.get(primary_field):
                continue

            fields_for_item = [k for k in all_section_keys if k.endswith(f'_{index}')] # 

            for field_key in fields_for_item:
                prefix = f'{section}_'
                field_name = field_key.replace(prefix, '').rsplit('_', 1)[0]

                if field_name in ['points', 'details']: # 
                    points_str = form.get(field_key)
                    item[field_name] = [p.strip() for p in points_str.split('\n') if p.strip()]
                else:
                    item[field_name] = form.get(field_key)

            if any(item.values()): # 
                items.append(item)

        db_key = section # 
        if section == 'project':
            db_key = 'projects' # 
        elif section == 'activity':
            db_key = 'activities' # 
        data[db_key] = json.dumps(items) # 

    # In the parse_form_data function, before the `return data` line

    custom_items = []
    # Find all custom section titles submitted with the form
    custom_section_keys = [k for k in form if k.startswith('custom_title_')]
    if custom_section_keys:
        # Get the unique index numbers from the keys
        indices = sorted(list(set(key.split('_')[-1] for key in custom_section_keys)))

        for index in indices:
            title = form.get(f'custom_title_{index}')
            points_str = form.get(f'custom_points_{index}')
            # Only add the section if it has a title and some content
            if title and points_str:
                points = [p.strip() for p in points_str.split('\n') if p.strip()]
                if points:
                    custom_items.append({'title': title, 'points': points})
    # Save the result as a JSON string
    data['custom_sections'] = json.dumps(custom_items)

    return data

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        try:
            resume_data = parse_form_data(request.form)
            cursor.execute("""
                UPDATE user_resume_data SET
                    name = ?, email = ?, phone = ?, linkedin = ?, github = ?, summary = ?,
                    education = ?, experience = ?, projects = ?, skills = ?, activities = ?,
                    custom_sections = ?, -- <<< ADD THIS
                    last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ?""", (
                resume_data['name'], resume_data['email'], resume_data['phone'],
                resume_data['linkedin'], resume_data['github'], resume_data['summary'],
                resume_data['education'], resume_data['experience'], resume_data['projects'],
                resume_data['skills'], resume_data['activities'],
                resume_data.get('custom_sections', '[]'), # <<< ADD THIS
                current_user.id
            ))
            conn.commit()
            flash('Your profile has been updated successfully!', 'success')
        except Exception as e: # 
            flash(f'An error occurred while updating your profile: {e}', 'danger') # 
        finally:
            conn.close()
        return redirect(url_for('profile'))

    cursor.execute("SELECT * FROM user_resume_data WHERE user_id = ?", (current_user.id,)) # 
    user_data_row = cursor.fetchone()
    conn.close()

    if not user_data_row:
        flash('Could not find your profile data. Please contact support.', 'danger') # 
        return redirect(url_for('home'))

    resume_data = {
    'name': user_data_row['name'],
    'email': user_data_row['email'],
    'phone': user_data_row['phone'],
    'linkedin': user_data_row['linkedin'],
    'github': user_data_row['github'],
    'summary': user_data_row['summary'],
    'education': json.loads(user_data_row['education'] or '[]'),
    'experience': json.loads(user_data_row['experience'] or '[]'),
    'projects': json.loads(user_data_row['projects'] or '[]'),
    'skills': json.loads(user_data_row['skills'] or '{}'),
    'activities': json.loads(user_data_row['activities'] or '[]'),
    'custom_sections': json.loads(user_data_row['custom_sections'] or '[]') # <<< ADD THIS
}

    return render_template('profile.html', data=resume_data)

@app.route('/dashboard')
@login_required
def dashboard_page():
    dash_config = config.get('dashboard_settings', {})
    daily_goal = dash_config.get('daily_application_goal', 10)
    weekly_goal = dash_config.get('weekly_application_goal', 75)
    return render_template('dashboard.html', daily_goal=daily_goal, weekly_goal=weekly_goal) # 

@app.route('/get_jobs')
@login_required
def get_jobs():
    status_filter = request.args.get('status', None)
    jobs_list = [] # 
    conn = get_db_connection()

    if status_filter:
        query = "SELECT * FROM jobs WHERE status = ? AND user_id = ? ORDER BY id DESC" # 
        cursor = conn.execute(query, (status_filter, current_user.id))
    else:
        query = "SELECT * FROM jobs WHERE user_id = ? ORDER BY id DESC" # 
        cursor = conn.execute(query, (current_user.id,)) # 

    rows = cursor.fetchall()
    conn.close()

    for row in rows:
        jobs_list.append(dict(row))

    return jsonify(jobs_list)

@app.route('/update_job_status/<int:job_id>', methods=['POST'])
@login_required
def update_job_status_route(job_id):
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "New status not provided."}), 400

    conn = get_db_connection() # 

    if new_status.lower() == 'applied':
        cursor = conn.cursor()
        cursor.execute("SELECT application_date FROM jobs WHERE id = ? AND user_id = ?", (job_id, current_user.id)) # 
        current_app_date_row = cursor.fetchone()
        if current_app_date_row and current_app_date_row['application_date'] is None: # 
            conn.execute("UPDATE jobs SET status = ?, application_date = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?", (new_status, job_id, current_user.id)) # 
        else:
            conn.execute("UPDATE jobs SET status = ? WHERE id = ? AND user_id = ?", (new_status, job_id, current_user.id)) # 
    else:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ? AND user_id = ?", (new_status, job_id, current_user.id)) # 

    conn.commit() # 
    conn.close()
    return jsonify({"success": f"Job {job_id} status updated to {new_status}."})

@app.route('/scrape', methods=['POST'])
@login_required
def scrape_jobs_route_main():
    if scraping_status['is_running']:
        return jsonify({"error": "A scraping process is already running."}), 409 # 

    data = request.get_json()
    source = data.get('source', 'all')
    time_period_str = data.get('time_period_str', '7 Days') # 
    days = data.get('days', 7)
    management_option = data.get('management_option', 'add')
    location = data.get('location', '')
    keywords = data.get('keywords', '')

    user_id = current_user.id

    thread = threading.Thread(
        target=perform_scraping_task, # 
        args=(source, time_period_str, days * 86400, days, management_option, location, keywords, user_id) # 
    )
    thread.daemon = True
    thread.start()
    return jsonify({"message": "Scraping process initiated for your account."}), 202

@app.route('/scrape_status')
def scrape_status_endpoint():
    return jsonify(scraping_status)

@app.route('/api/dashboard_stats')
@login_required # Make sure this is present
def api_dashboard_stats():
    stats = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = current_user.id # Get the current user's ID

    # This query remains useful
    twenty_four_hours_ago_dt = datetime.now() - timedelta(hours=24)
    twenty_four_hours_ago_str = twenty_four_hours_ago_dt.strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT SUM(new_jobs_found) FROM scrape_history WHERE scrape_timestamp >= ? AND user_id = ?", (twenty_four_hours_ago_str, user_id))
    result = cursor.fetchone()
    stats['jobs_scraped_last_24_hours'] = result[0] if result and result[0] is not None else 0

    applied_statuses = ('applied', 'interviewing', 'offer', 'rejected', 'rejected_after_interview', 'offer_declined')
    status_placeholders = ', '.join(['?'] * len(applied_statuses))

    # This query remains useful for Total Applications
    query_total_applications = f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND user_id = ?"
    cursor.execute(query_total_applications, (*applied_statuses, user_id))
    stats['total_applications'] = cursor.fetchone()[0]

    # --- REMOVED: applications_today calculation ---
    # --- REMOVED: applications_this_week calculation ---

    # This is your "total resume/cv generations" stat. It's already here.
    cursor.execute("SELECT COUNT(*) FROM resume_generations WHERE user_id = ?", (user_id,))
    stats['resumes_created_total'] = cursor.fetchone()[0]

    # This can remain if you want to show "today's" generations separately
    today_start_str = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute("SELECT COUNT(*) FROM resume_generations WHERE generation_timestamp >= ? AND user_id = ?", (today_start_str, user_id))
    stats['resumes_created_today'] = cursor.fetchone()[0]

    # Cover letter stats
    cursor.execute("SELECT COUNT(*) FROM cover_letter_generations WHERE user_id = ?", (user_id,))
    stats['cover_letters_created_total'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM cover_letter_generations WHERE generation_timestamp >= ? AND user_id = ?", (today_start_str, user_id))
    stats['cover_letters_created_today'] = cursor.fetchone()[0]

    # Chart data (These queries should also be filtered by user_id)
    cursor.execute("SELECT status, COUNT(*) as count FROM jobs WHERE user_id = ? GROUP BY status", (user_id,))
    stats['application_status_breakdown'] = {row['status']: row['count'] for row in cursor.fetchall()}

    query_apps_by_source = f"SELECT source, COUNT(*) as count FROM jobs WHERE status IN ({status_placeholders}) AND user_id = ? GROUP BY source"
    cursor.execute(query_apps_by_source, (*applied_statuses, user_id))
    stats['applications_by_source'] = {row['source']: row['count'] for row in cursor.fetchall()}

    applications_per_day = []
    for i in range(6, -1, -1):
        day_date = date.today() - timedelta(days=i)
        day_start_str = datetime.combine(day_date, datetime.min.time()).strftime('%Y-%m-%d %H:%M:%S')
        day_end_str = datetime.combine(day_date, datetime.max.time()).strftime('%Y-%m-%d %H:%M:%S')
        query_apps_per_day = f"SELECT COUNT(*) FROM jobs WHERE status IN ({status_placeholders}) AND application_date >= ? AND application_date <= ? AND user_id = ?"
        cursor.execute(query_apps_per_day, (*applied_statuses, day_start_str, day_end_str, user_id))
        count = cursor.fetchone()[0]
        applications_per_day.append({'date': day_date.strftime('%Y-%m-%d'), 'count': count})
    stats['applications_last_7_days'] = applications_per_day

    conn.close()
    return jsonify(stats)

@app.route('/api/reset_weekly_progress', methods=['POST'])
@login_required
def reset_weekly_progress():
    """
    Resets the weekly application count by setting recent application_date to NULL.
    """
    conn = get_db_connection()
    try:
        # Define the start of the 7-day window
        seven_days_ago_str = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')

        # These are the statuses that count as an "application"
        applied_statuses = ('applied', 'interviewing', 'offer', 'rejected', 'rejected_after_interview', 'offer_declined')
        status_placeholders = ', '.join(['?'] * len(applied_statuses))

        query = f"""
            UPDATE jobs
            SET application_date = NULL
            WHERE user_id = ?
            AND status IN ({status_placeholders})
            AND application_date >= ?
        """

        # Build the parameters tuple
        params = (current_user.id, *applied_statuses, seven_days_ago_str)

        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()

        app.logger.info(f"Reset weekly progress for user_id: {current_user.id}. {cursor.rowcount} rows affected.")

        return jsonify({"success": True, "message": f"{cursor.rowcount} application dates have been reset."})

    except Exception as e:
        conn.rollback()
        app.logger.error(f"Error resetting weekly progress for user_id {current_user.id}: {e}")
        return jsonify({"success": False, "message": "An error occurred while resetting progress."}), 500
    finally:
        conn.close()


@app.route('/api/quote')
def get_motivational_quote():
    try:
        response = requests.get("https://zenquotes.io/api/random", timeout=5)
        response.raise_for_status()
        data = response.json() # 
        if data and isinstance(data, list) and len(data) > 0: # 
            quote = data[0].get('q', 'Keep going!') # 
            author = data[0].get('a', 'Unknown') # 
            return jsonify({"quote": quote, "author": author}) # 
        else:
            return jsonify({"quote": "The journey of a thousand miles begins with a single step.", "author": "Lao Tzu"}) # 
    except requests.exceptions.RequestException as e: # 
        app.logger.error(f"Error fetching quote: {e}") # 
        return jsonify({"quote": "The difference between ordinary and extraordinary is that little extra.", "author": "Jimmy Johnson"}) # 

@app.route('/generate_documents', methods=['POST'])
@login_required
def generate_documents():
    try:
        data = request.get_json()
        job_description = data.get('job_description')
        job_id = data.get('job_id', None)

        if not job_description:
            return jsonify({"error": "Job description is required"}), 400

        user_id_str = str(current_user.id)
        user_generation_folder = os.path.join(RESUME_CREATION_FOLDER, user_id_str)
        if not os.path.exists(user_generation_folder):
            os.makedirs(user_generation_folder)
        
        job_desc_filename = "job_description.txt"
        job_desc_file_path = os.path.join(user_generation_folder, job_desc_filename)

        with open(job_desc_file_path, 'w', encoding='utf-8') as f:
            f.write(job_description)

        resume_script_path = os.path.join(RESUME_CREATION_FOLDER, 'create_resume.py')
        
        cmd = [
            sys.executable, resume_script_path,
            job_desc_file_path,
            '--user-id', user_id_str,
            '--output-dir', user_generation_folder
        ]
        
        app.logger.info(f"Running command: {' '.join(cmd)}")

        process = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding='utf-8', errors='replace'
        )

        if process.returncode != 0:
            app.logger.error(f"Error generating documents. Stderr: {process.stderr}")
            app.logger.error(f"Stdout: {process.stdout}")
            return jsonify({"error": "Failed to generate documents", "details": process.stderr or process.stdout}), 500

        # --- THIS IS THE FIX: Read the exact filenames from the script's output ---
        stdout = process.stdout
        app.logger.info(f"Document generation script stdout: {stdout}")

        resume_pdf_match = re.search(r"Successfully created resume PDF: (.*\.pdf)", stdout)
        cover_letter_pdf_match = re.search(r"Successfully created cover letter PDF: (.*\.pdf)", stdout)

        if not resume_pdf_match or not cover_letter_pdf_match:
            app.logger.error("Could not find generated filenames in script output.")
            return jsonify({"error": "Could not determine generated filenames."}), 500

        resume_filename = os.path.basename(resume_pdf_match.group(1))
        cover_letter_filename = os.path.basename(cover_letter_pdf_match.group(1))
        
        # Log the generation to the database
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO resume_generations (job_id, user_id) VALUES (?, ?)", (job_id, current_user.id))
            conn.execute("INSERT INTO cover_letter_generations (job_id, user_id) VALUES (?, ?)", (job_id, current_user.id))
            conn.commit()
        finally:
            conn.close()

        return jsonify({
            "success": True,
            "resume_pdf_url": f"/serve_document/{user_id_str}/{resume_filename}",
            "cover_letter_pdf_url": f"/serve_document/{user_id_str}/{cover_letter_filename}"
        })

    except Exception as e:
        app.logger.exception("Error in /generate_documents")
        return jsonify({"error": "An unexpected error occurred", "details": str(e)}), 500

@app.route('/serve_document/<user_id>/<path:filename>')
@login_required
def serve_document(user_id, filename):
    if str(current_user.id) != user_id: # 
        return jsonify({"error": "Unauthorized"}), 403

    user_folder = os.path.join(RESUME_CREATION_FOLDER, user_id)
    return send_from_directory(user_folder, filename)

if __name__ == "__main__":
    with app.app_context():
        initialize_database()
    app.run(debug=True, port=5001)