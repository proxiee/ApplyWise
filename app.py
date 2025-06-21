from flask import Flask, render_template, jsonify
import pandas as pd
import sqlite3
import json
import openai
from pdfminer.high_level import extract_text
from flask_cors import CORS
import os

def load_config(file_name="config.json"):
    with open(file_name) as f:
        return json.load(f)

config = load_config()
app = Flask(__name__)
CORS(app)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# --- All your existing helper functions and routes go here ---
# (read_pdf, home, job, get_all_jobs, job_details, hide_job, mark_applied, etc.)
# The only change needed is in `verify_db_schema` and potentially the template rendering.

@app.route('/')
def home():
    # The template can now use the 'source' column to display a badge
    # e.g., {% if job.source == 'LinkedIn' %} <span class="badge-linkedin">L</span> {% endif %}
    return render_template('jobs.html') 

@app.route('/get_all_jobs')
def get_all_jobs():
    conn = sqlite3.connect(config["app_settings"]["db_path"])
    # Get only non-hidden jobs
    query = f"SELECT * FROM {config['app_settings']['jobs_tablename']} WHERE hidden = 0"
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df = df.sort_values(by='date', ascending=False)
    # Convert dataframe to a list of dictionaries for JSON response
    jobs = df.to_dict('records')
    return jsonify(jobs)

# --- PASTE ALL OTHER FLASK ROUTES FROM YOUR app.py HERE ---
# e.g. @app.route('/job_details/<int:job_id>') ...
# No changes are needed for the routes that update by job_id.

# <--- Start of pasted routes --->
def read_pdf(file_path):
    try:
        text = extract_text(file_path)
        return text
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return None
    except Exception as e:
        print(f"An error occurred while reading the PDF: {e}")
        return None

@app.route('/job_details/<int:job_id>')
def job_details(job_id):
    conn = sqlite3.connect(config["app_settings"]["db_path"])
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM {config['app_settings']['jobs_tablename']} WHERE id = ?", (job_id,))
    job_tuple = cursor.fetchone()
    
    if job_tuple is not None:
        column_names = [column[0] for column in cursor.description]
        job = dict(zip(column_names, job_tuple))
        conn.close()
        return jsonify(job)
    else:
        conn.close()
        return jsonify({"error": "Job not found"}), 404
        
# ... and so on for hide_job, mark_applied, mark_interview, mark_rejected, get_cover_letter, get_resume...
# All these routes should be pasted here without modification, they will work correctly.
# Ensure their DB path points to config["app_settings"]["db_path"]

# <--- End of pasted routes --->

def verify_db_schema():
    """
    Checks if the database and table exist, and adds any missing columns.
    This is essential for the unified schema.
    """
    db_path = config["app_settings"]["db_path"]
    table_name = config["app_settings"]["jobs_tablename"]
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
    if cursor.fetchone() is None:
        print(f"Table '{table_name}' not found. It will be created when you run run_scrapers.py.")
        conn.close()
        return

    # Check for all required columns and add them if they are missing
    cursor.execute(f"PRAGMA table_info({table_name})")
    table_info = cursor.fetchall()
    existing_columns = [column[1] for column in table_info]
    
    required_columns = {
        "cover_letter": "TEXT",
        "resume": "TEXT",
        "source": "TEXT" # The new, essential column
    }

    for col, col_type in required_columns.items():
        if col not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}")
            print(f"Added '{col}' column to '{table_name}' table.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    verify_db_schema() # Verify the DB schema before running the app
    app.run(debug=True, port=5001)