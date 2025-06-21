from flask import Flask, render_template, jsonify
import sqlite3
import json
import os
# pdfminer and openai are not used in the main display routes, but kept for your other functions
from pdfminer.high_level import extract_text
import openai
from flask_cors import CORS

def load_config(file_name="config.json"):
    with open(file_name) as f:
        return json.load(f)

config = load_config()
app = Flask(__name__)
CORS(app)
app.config['TEMPLATES_AUTO_RELOAD'] = True


@app.route('/')
def home():
    return render_template('jobs.html')


@app.route('/get_all_jobs')
def get_all_jobs():
    jobs_list = []
    conn = None
    try:
        conn = sqlite3.connect(config["app_settings"]["db_path"])
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # --- THE FINAL, CORRECTED SQL QUERY ---
        # This now selects rows where hidden is 0 OR IS NULL, which will
        # correctly include the LinkedIn jobs from your database.
        query = f"""
            SELECT rowid as id, * FROM {config['app_settings']['jobs_tablename']} 
            WHERE hidden = 0 OR hidden IS NULL 
            ORDER BY rowid DESC
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()

        for row in rows:
            job_dict = dict(row)
            for key, value in job_dict.items():
                if value is None:
                    job_dict[key] = ''
            jobs_list.append(job_dict)

        return jsonify(jobs_list)

    except Exception as e:
        print(f"!!!!!! AN ERROR OCCURRED IN get_all_jobs: {e} !!!!!!")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

# --- PASTE THE REST OF YOUR ORIGINAL FLASK ROUTES HERE ---
# Make sure to change "WHERE id = ?" to "WHERE rowid = ?" in all of them
# for consistency. Example:
@app.route('/hide_job/<int:job_id>', methods=['POST'])
def hide_job(job_id):
    conn = sqlite3.connect(config["app_settings"]["db_path"])
    cursor = conn.cursor()
    # Use rowid to update for consistency
    query = f"UPDATE {config['app_settings']['jobs_tablename']} SET hidden = 1 WHERE rowid = ?"
    cursor.execute(query, (job_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": "Job marked as hidden"}), 200

# (Paste your other routes like mark_applied, job_details, etc. here)


def verify_db_schema():
    # This function remains useful for first-time setup
    db_path = config["app_settings"]["db_path"]
    table_name = config["app_settings"]["jobs_tablename"]
    if not os.path.exists(db_path):
        print("Database not found, please run run_scrapers.py first.")
        return
    # ... rest of function is fine ...


if __name__ == "__main__":
    verify_db_schema() # This can stay
    app.run(debug=True, port=5001)