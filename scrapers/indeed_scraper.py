import subprocess
import pandas as pd
import yaml
import os
import time as tm
import json
import traceback # Added for more detailed error logging

def cleanse_jobfunnel_json_files(config):
    """
    Checks for the existence of block and duplicate lists.
    It ensures they are valid JSON files before JobFunnel runs,
    overwriting them with a clean slate if they are corrupted or invalid.
    """
    block_file = config['indeed_settings']['block_list_file']
    dupe_file = config['indeed_settings']['duplicates_list_file']

    for file_path in [block_file, dupe_file]:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            # Try to open and load the file.
            # We must specify utf-8 encoding to prevent the UnicodeDecodeError.
            with open(file_path, 'r', encoding='utf-8') as f:
                json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # If file is not found, or is empty/corrupted (not valid JSON),
            # create/overwrite it with a valid empty JSON object.
            print(f"Indeed: Cleansing and initializing file: {file_path}")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('{}')

def standardize_indeed_data(df, config):
    """
    Renames columns and adds missing ones to match the main database schema.
    """
    print("\nIndeed: Inside standardize_indeed_data")
    print(f"Indeed: DataFrame columns BEFORE renaming: {df.columns.tolist()}")

    column_mapping = {
        'title': 'title',
        'company': 'company',
        'location': 'location',
        'date': 'date', # This might need further date parsing if format differs
        'link': 'job_url',
        'blurb': 'job_description',
    }
    df.rename(columns=column_mapping, inplace=True)

    # Add 'source' column
    df['source'] = 'Indeed'

    # List of columns expected by app.py's commit_jobs_to_db
    # Based on jobs.db schema: title, company, location, date, job_url, job_description, source
    required_cols_for_db = [
        'title', 'company', 'location', 'date', 'job_url', 'job_description', 'source'
    ]

    for col in required_cols_for_db:
        if col not in df.columns:
            df[col] = None # Or an appropriate default value like '' for TEXT fields
            print(f"Indeed: Added missing column '{col}' with None values.")

    # Select and reorder columns to match the expected input for commit_jobs_to_db
    final_cols = [col for col in required_cols_for_db if col in df.columns]
    df_final = df[final_cols]

    print(f"Indeed: DataFrame columns AFTER renaming and selection: {df_final.columns.tolist()}")
    print(f"Indeed: Standardized DataFrame head:\n{df_final.head()}")
    return df_final


def scrape_indeed(config, existing_urls=set()):
    """
    Main function to scrape Indeed using the JobFunnel command-line tool.
    Returns a Pandas DataFrame of new jobs.
    """
    print("\n--- Starting Indeed Scraper (JobFunnel) ---")
    start_time = tm.perf_counter()

    cfg = config['indeed_settings']
    output_csv_path = cfg['master_csv_file']

    os.makedirs(os.path.dirname(output_csv_path), exist_ok=True)

    cleanse_jobfunnel_json_files(config)

    jobfunnel_config = {
        'master_csv_file': output_csv_path, 'cache_folder': cfg['cache_folder'],
        'log_file': cfg['log_file'], 'block_list_file': cfg['block_list_file'],
        'duplicates_list_file': cfg['duplicates_list_file'],
        'search': cfg['search_config'], 'delay': cfg['delay_config']
    }

    temp_yaml_path = 'temp_indeed_settings.yaml'
    with open(temp_yaml_path, 'w') as f:
        yaml.dump(jobfunnel_config, f)

    df_standardized = pd.DataFrame() # Initialize with an empty DataFrame to ensure a return value

    print("Indeed: Running JobFunnel process...")
    try:
        # IMPORTANT CHANGE: Removed check=True to prevent CalledProcessError on non-zero exit
        # We will handle the return code manually.
        process_result = subprocess.run(
            ['funnel', 'load', '-s', temp_yaml_path],
            capture_output=True, text=True, encoding='utf-8'
        )
        print(f"Indeed: JobFunnel process finished with return code: {process_result.returncode}")
        print(f"Indeed: JobFunnel stdout:\n{process_result.stdout}")
        if process_result.stderr:
            print(f"Indeed: JobFunnel stderr:\n{process_result.stderr}")

        if process_result.returncode != 0:
            print(f"Indeed: WARNING - JobFunnel exited with non-zero code {process_result.returncode}. This might indicate a soft error, no jobs found based on filters, or a captcha. Attempting to read CSV anyway.")

        # --- Attempt to read CSV and process, regardless of JobFunnel's return code ---
        if os.path.exists(output_csv_path):
            try:
                df = pd.read_csv(output_csv_path, encoding='utf-8')
                print(f"Indeed: Successfully read CSV from '{output_csv_path}'. Total rows: {len(df)}")
                print(f"Indeed: Raw CSV columns: {df.columns.tolist()}")
                print(f"Indeed: Raw CSV head:\n{df.head()}")

                if 'link' not in df.columns:
                    print("ERROR: The CSV file from JobFunnel does not contain the expected 'link' column. Cannot process Indeed jobs.")
                    return pd.DataFrame() # Return empty if critical column missing

                # Filter out jobs that are already in the database
                print(f"Indeed: Number of existing URLs passed from app.py: {len(existing_urls)}")
                if existing_urls:
                    print(f"Indeed: Sample existing URLs: {list(existing_urls)[:5]}")
                
                df_new = df[~df['link'].isin(existing_urls)].copy()
                print(f"Indeed: Found {len(df_new)} new jobs (not in existing_urls) from CSV.")
                if not df_new.empty:
                    print(f"Indeed: New jobs (from CSV) head before standardization:\n{df_new.head()}")

                if df_new.empty:
                    print("Indeed: No new jobs to add to the database after filtering against existing URLs.")
                else:
                    df_standardized = standardize_indeed_data(df_new, config)

            except pd.errors.EmptyDataError:
                print(f"Indeed: CSV file '{output_csv_path}' is empty or contains no data. No jobs to process.")
            except Exception as e:
                print(f"Indeed: Error processing output CSV: {e}")
                traceback.print_exc() # Print full traceback for more details
        else:
            print(f"Indeed: Output CSV file '{output_csv_path}' not found after JobFunnel run. No jobs were scraped.")

    except FileNotFoundError:
        print("\nFATAL ERROR: The 'funnel' command was not found. Please ensure JobFunnel is installed and in your PATH.")
        # If 'funnel' command itself is not found, we cannot proceed with Indeed scraping
    except Exception as e: # Catch any other unexpected errors during the subprocess call or initial file handling
        print(f"Indeed: An unexpected error occurred during JobFunnel execution or initial file handling: {e}")
        traceback.print_exc()

    finally:
        # This finally block will always run to ensure cleanup
        if os.path.exists(temp_yaml_path):
            os.remove(temp_yaml_path)
            print(f"Indeed: Cleaned up temporary YAML file: {temp_yaml_path}")
        # Ensure CSV is cleaned up regardless of whether it was processed or not,
        # but only if it exists.
        if os.path.exists(output_csv_path):
            os.remove(output_csv_path)
            print(f"Indeed: Cleaned up temporary CSV file: {output_csv_path}")

    end_time = tm.perf_counter()
    print(f"--- Indeed scraping finished in {end_time - start_time:.2f} seconds ---")
    return df_standardized # Return the DataFrame (could be empty if no jobs or error)