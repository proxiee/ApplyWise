import psycopg2
import psycopg2.extras # Import DictCursor
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
except ImportError as e:
    print(f"Error importing scrapers: {e}. Using dummy functions.")
    def scrape_linkedin(config, existing_urls): return pd.DataFrame()
    def scrape_indeed(config, existing_urls): return pd.DataFrame()

# --- Global variable for scraping status ---
scraping_status = {"is_running": False, "message": "Idle"}

# --- Constants ---
RESUME_CREATION_FOLDER = 'resume_cover_creation'

# --- App Initialization ---
app = Flask(__name__)
# IMPORTANT: You must set a secret key for session management
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-super-secret-key-that-you-should-change')
CORS(app)

# --- Flask-Login Initialization ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'


# --- User Loader for Flask-Login ---
class User(UserMixin):
    def __init__(self, id, email, username):
        self.id = id
        self.email = email
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Use %s for PostgreSQL parameter style
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user_row = cursor.fetchone()
    conn.close()
    if user_row:
        # Access columns by key since we're using DictCursor
        return User(id=user_row['id'], email=user_row['email'], username=user_row['username'])
    return None

# --- Configuration Loading ---
def load_config(file_name="config.json"):
    try:
        with open(file_name) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading config file '{file_name}': {e}. Exiting.")
        sys.exit(1)

config = load_config()

# --- DATABASE INITIALIZATION AND HELPERS (MODIFIED FOR POSTGRESQL) ---
def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    # Get the database connection URL from environment variables
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("No DATABASE_URL set for the connection")
    
    # Connect to the database
    conn = psycopg2.connect(db_url)
    # Use DictCursor to get dictionary-like rows
    conn.cursor_factory = psycopg2.extras.DictCursor
    return conn

def initialize_database():
    """Creates/verifies ALL database tables on startup for PostgreSQL."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # --- Users table (PostgreSQL syntax) ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --- User Resume Data table (PostgreSQL syntax) ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_resume_data (
        id SERIAL PRIMARY KEY,
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
        custom_sections TEXT,
        last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)

    # --- Scrape History table (PostgreSQL syntax) ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scrape_history (
        id SERIAL PRIMARY KEY,
        scrape_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        source_filter TEXT,
        time_period_scraped TEXT,
        new_jobs_found INTEGER,
        user_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)

    # --- Jobs table (PostgreSQL syntax) ---
    cursor.execute("""
      CREATE TABLE IF NOT EXISTS jobs (
        id SERIAL PRIMARY KEY,
        title TEXT, company TEXT, location TEXT, date TEXT,
        job_url TEXT, job_description TEXT, source TEXT,
        status TEXT DEFAULT 'inbox',
        date_loaded TIMESTAMPTZ,
        application_date TIMESTAMPTZ,
        scrape_history_id INTEGER,
        user_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY (scrape_history_id) REFERENCES scrape_history(id),
        UNIQUE(job_url, user_id)
    )
    """)
    
    # --- Resume Generations table (PostgreSQL syntax) ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resume_generations (
        id SERIAL PRIMARY KEY,
        job_id INTEGER,
        user_id INTEGER NOT NULL,
        generation_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    # --- Cover Letter Generations table (PostgreSQL syntax) ---
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cover_letter_generations (
        id SERIAL PRIMARY KEY,
        job_id INTEGER,
        user_id INTEGER NOT NULL,
        generation_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Database initialized/verified successfully.")

    # Ensure resume creation directory exists (Vercel has a /tmp directory for this)
    # Note: This folder is not persistent across deployments.
    if not os.path.exists(RESUME_CREATION_FOLDER):
        os.makedirs(RESUME_CREATION_FOLDER)


# --- Initialize the Auth Blueprint ---
# Pass the correct get_db_connection function
init_auth(app, User, get_db_connection)
app.register_blueprint(auth_bp)

# --- CORE SCRAPING AND DATABASE LOGIC (MODIFIED FOR POSTGRESQL) ---

def commit_jobs_to_db(conn, df, history_id, user_id):
    table_name = 'jobs'
    print(f"\n--- commit_jobs_to_db called for User ID: {user_id} ---")
    if df.empty:
        return 0

    cursor = conn.cursor()
    cursor.execute(f"SELECT job_url FROM {table_name} WHERE user_id = %s", (user_id,))
    # Fetch all results from the cursor
    existing_urls = {row['job_url'] for row in cursor.fetchall()}

    if 'job_url' not in df.columns:
        return 0

    new_jobs_df = df[~df['job_url'].isin(existing_urls)].copy()
    if new_jobs_df.empty:
        return 0

    new_jobs_df['user_id'] = user_id
    new_jobs_df['date_loaded'] = pd.to_datetime('now').strftime("%Y-%m-%d %H:%M:%S")
    new_jobs_df['status'] = 'inbox'
    new_jobs_df['scrape_history_id'] = history_id
    new_jobs_df['application_date'] = None

    columns_to_insert = [
        'title', 'company', 'location', 'date', 'job_url',
        'job_description', 'source', 'status', 'date_loaded',
        'application_date', 'scrape_history_id', 'user_id'
    ]
    df_to_insert = new_jobs_df[[col for col in columns_to_insert if col in new_jobs_df.columns]]

    # Use psycopg2 to_sql method is not direct, so we'll use execute_values for efficiency
    from psycopg2.extras import execute_values
    
    tuples = [tuple(x) for x in df_to_insert.to_numpy()]
    cols = ','.join(list(df_to_insert.columns))
    
    # Create the INSERT query with %s placeholders
    query  = f"INSERT INTO {table_name} ({cols}) VALUES %s"
    
    try:
        execute_values(cursor, query, tuples)
        conn.commit()
        print(f"Successfully inserted {len(df_to_insert)} new jobs into '{table_name}' for user {user_id}.")
        return len(df_to_insert)
    except Exception as e:
        print(f"ERROR: Failed to insert jobs into database for user {user_id}: {e}")
        conn.rollback() # Rollback the transaction on error
        return 0
    finally:
        cursor.close()

# The perform_scraping_task and other logic remains largely the same,
# but all database interactions must be updated for PostgreSQL syntax.
# I will make the necessary changes below.

def perform_scraping_task(source, time_period_str, timespan_seconds, days_to_scrape, management_option, location, keywords, user_id):
    global scraping_status
    scraping_status['is_running'] = True
    print(f"\n--- Initiating scraping task for source: {source} for User ID: {user_id} ---")
    
    conn = None # Initialize conn to None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if management_option == 'archive':
            scraping_status['message'] = "Archiving old jobs..."
            cursor.execute("UPDATE jobs SET status = 'archived' WHERE status = 'inbox' AND user_id = %s", (user_id,))
        elif management_option == 'delete':
            scraping_status['message'] = "Deleting old jobs..."
            cursor.execute("DELETE FROM jobs WHERE status = 'inbox' AND user_id = %s", (user_id,))
        conn.commit()

        scraping_status['message'] = "Creating scrape history record..."
        cursor.execute(
            "INSERT INTO scrape_history (source_filter, time_period_scraped, new_jobs_found, user_id) VALUES (%s, %s, %s, %s) RETURNING id",
            (source, time_period_str, 0, user_id)
        )
        history_id = cursor.fetchone()['id']
        conn.commit()

        cursor.execute("SELECT job_url FROM jobs WHERE user_id = %s", (user_id,))
        existing_urls = {row['job_url'] for row in cursor.fetchall()}
        print(f"Fetched {len(existing_urls)} existing URLs from DB for user {user_id}.")
        
        # ... (The rest of your scraping logic remains the same) ...
        # Make sure the commit_jobs_to_db is called with the active connection
        # For brevity, I'm omitting the scraper setup code as it doesn't change
        
        all_new_jobs_df_list = []
        local_config = copy.deepcopy(config) # Assuming config is loaded correctly

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
            # Pass the open connection to the function
            num_added = commit_jobs_to_db(conn, final_df, history_id, user_id)
        else:
            print("No jobs found by any scraper to combine and save.")

        cursor.execute("UPDATE scrape_history SET new_jobs_found = %s WHERE id = %s", (num_added, history_id))
        conn.commit()

        scraping_status['message'] = f"Scraping complete. Added {num_added} new jobs."
        time.sleep(3)

    except Exception as e:
        scraping_status['message'] = f"An error occurred: {e}"
        print(f"An unexpected error occurred during scraping: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback() # Rollback on error
        time.sleep(5)

    finally:
        if conn:
            cursor.close()
            conn.close()
        scraping_status['is_running'] = False
        scraping_status['message'] = "Idle"
        print("Scraping task finished (idle).")
        
# --- FLASK ROUTES (MODIFIED FOR POSTGRESQL) ---
# Your routes like `home`, `parse_form_data` don't need changes.
# The routes that interact with the database need their queries updated.

@app.route('/')
@login_required
def home():
    return render_template('jobs.html')

# parse_form_data does not interact with the DB, so it's unchanged.
# ... your parse_form_data function ...

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        try:
            resume_data = parse_form_data(request.form) # Assume this function exists
            cursor.execute("""
                UPDATE user_resume_data SET
                    name = %s, email = %s, phone = %s, linkedin = %s, github = %s, summary = %s,
                    education = %s, experience = %s, projects = %s, skills = %s, activities = %s,
                    custom_sections = %s,
                    last_updated = CURRENT_TIMESTAMP
                WHERE user_id = %s""", (
                resume_data['name'], resume_data['email'], resume_data['phone'],
                resume_data['linkedin'], resume_data['github'], resume_data['summary'],
                resume_data['education'], resume_data['experience'], resume_data['projects'],
                resume_data['skills'], resume_data['activities'],
                resume_data.get('custom_sections', '[]'),
                current_user.id
            ))
            conn.commit()
            flash('Your profile has been updated successfully!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'An error occurred while updating your profile: {e}', 'danger')
        finally:
            cursor.close()
            conn.close()
        return redirect(url_for('profile'))

    cursor.execute("SELECT * FROM user_resume_data WHERE user_id = %s", (current_user.id,))
    user_data_row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user_data_row:
        flash('Could not find your profile data. Please contact support.', 'danger')
        return redirect(url_for('home'))

    # Your logic to parse and render the profile page remains the same
    resume_data = {key: val for key, val in user_data_row.items()}
    # Make sure to json.loads for fields that are stored as JSON strings
    for field in ['education', 'experience', 'projects', 'skills', 'activities', 'custom_sections']:
        if resume_data[field]:
            resume_data[field] = json.loads(resume_data[field])
        else:
            # Provide default structures if field is None
            resume_data[field] = [] if field != 'skills' else {}

    return render_template('profile.html', data=resume_data)

@app.route('/get_jobs')
@login_required
def get_jobs():
    status_filter = request.args.get('status', None)
    conn = get_db_connection()
    cursor = conn.cursor()

    if status_filter:
        query = "SELECT * FROM jobs WHERE status = %s AND user_id = %s ORDER BY id DESC"
        cursor.execute(query, (status_filter, current_user.id))
    else:
        query = "SELECT * FROM jobs WHERE user_id = %s ORDER BY id DESC"
        cursor.execute(query, (current_user.id,))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # Convert DictRow objects to standard dicts for JSON serialization
    jobs_list = [dict(row) for row in rows]
    return jsonify(jobs_list)
    
@app.route('/update_job_status/<int:job_id>', methods=['POST'])
@login_required
def update_job_status_route(job_id):
    data = request.get_json()
    new_status = data.get('status')
    if not new_status:
        return jsonify({"error": "New status not provided."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    if new_status.lower() == 'applied':
        # Check if application_date is already set
        cursor.execute("SELECT application_date FROM jobs WHERE id = %s AND user_id = %s", (job_id, current_user.id))
        current_app_date_row = cursor.fetchone()
        if current_app_date_row and current_app_date_row['application_date'] is None:
            # Use CURRENT_TIMESTAMP for PostgreSQL
            cursor.execute("UPDATE jobs SET status = %s, application_date = CURRENT_TIMESTAMP WHERE id = %s AND user_id = %s", (new_status, job_id, current_user.id))
        else:
            cursor.execute("UPDATE jobs SET status = %s WHERE id = %s AND user_id = %s", (new_status, job_id, current_user.id))
    else:
        cursor.execute("UPDATE jobs SET status = %s WHERE id = %s AND user_id = %s", (new_status, job_id, current_user.id))

    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": f"Job {job_id} status updated to {new_status}."})

# ... Your `scrape_jobs_route_main`, `scrape_status_endpoint` are fine ...
# The route below needs query updates.

@app.route('/api/dashboard_stats')
@login_required
def api_dashboard_stats():
    stats = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    user_id = current_user.id

    twenty_four_hours_ago_dt = datetime.now() - timedelta(hours=24)
    cursor.execute("SELECT SUM(new_jobs_found) FROM scrape_history WHERE scrape_timestamp >= %s AND user_id = %s", (twenty_four_hours_ago_dt, user_id))
    result = cursor.fetchone()
    stats['jobs_scraped_last_24_hours'] = result[0] if result and result[0] is not None else 0

    applied_statuses = ('applied', 'interviewing', 'offer', 'rejected', 'rejected_after_interview', 'offer_declined')
    
    # Use a tuple directly for the IN clause
    query_total_applications = "SELECT COUNT(*) FROM jobs WHERE status IN %s AND user_id = %s"
    cursor.execute(query_total_applications, (applied_statuses, user_id))
    stats['total_applications'] = cursor.fetchone()[0]

    today_start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cursor.execute("SELECT COUNT(*) FROM resume_generations WHERE generation_timestamp >= %s AND user_id = %s", (today_start_dt, user_id))
    stats['resumes_created_today'] = cursor.fetchone()[0]
    
    # ... other stats queries need similar updates from ? to %s
    
    cursor.close()
    conn.close()
    return jsonify(stats)
    
# ... The rest of your routes should be checked for SQL syntax ...

# --- Main execution ---
if __name__ == "__main__":
    # The 'with app.app_context()' is good practice
    with app.app_context():
        # Make sure environment variables are loaded if you use a .env file locally
        # from dotenv import load_dotenv
        # load_dotenv()
        initialize_database()
    app.run(debug=True, port=5001)

# This is a placeholder for your existing parse_form_data function.
# It does not need changes, but is included here for completeness.
def parse_form_data(form):
    """Parses the complex form data into a structured dictionary."""
    data = {'name': form.get('name'), 'email': form.get('email'), 'phone': form.get('phone'),
            'linkedin': form.get('linkedin'), 'github': form.get('github'), 'summary': form.get('summary')}

    skills = {}
    skill_keys = [k for k in form if k.startswith('skill_category_')]
    for key in skill_keys:
        index = key.split('_')[-1]
        category = form.get(f'skill_category_{index}')
        value = form.get(f'skill_value_{index}')
        if category:
            skills[category] = value
    data['skills'] = json.dumps(skills)

    for section in ['experience', 'education', 'project', 'activity']:
        items = []
        all_section_keys = [k for k in form if k.startswith(f'{section}_')]
        if not all_section_keys:
            indices = []
        else:
            indices = sorted(list(set(key.split('_')[-1] for key in all_section_keys)))

        for index in indices:
            item = {}
            primary_field = f'{section}_title_{index}' if section == 'experience' else f'{section}_name_{index}'
            if section == 'education': primary_field = f'{section}_university_{index}'

            if not form.get(primary_field):
                continue

            fields_for_item = [k for k in all_section_keys if k.endswith(f'_{index}')]

            for field_key in fields_for_item:
                prefix = f'{section}_'
                field_name = field_key.replace(prefix, '').rsplit('_', 1)[0]

                if field_name in ['points', 'details']:
                    points_str = form.get(field_key)
                    item[field_name] = [p.strip() for p in points_str.split('\n') if p.strip()]
                else:
                    item[field_name] = form.get(field_key)

            if any(item.values()):
                items.append(item)

        db_key = section
        if section == 'project':
            db_key = 'projects'
        elif section == 'activity':
            db_key = 'activities'
        data[db_key] = json.dumps(items)

    custom_items = []
    custom_section_keys = [k for k in form if k.startswith('custom_title_')]
    if custom_section_keys:
        indices = sorted(list(set(key.split('_')[-1] for key in custom_section_keys)))
        for index in indices:
            title = form.get(f'custom_title_{index}')
            points_str = form.get(f'custom_points_{index}')
            if title and points_str:
                points = [p.strip() for p in points_str.split('\n') if p.strip()]
                if points:
                    custom_items.append({'title': title, 'points': points})
    data['custom_sections'] = json.dumps(custom_items)

    return data
