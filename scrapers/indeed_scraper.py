import subprocess
import pandas as pd
import yaml
import os
import time as tm
import json

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
    column_mapping = {
        'title': 'title', 'company': 'company', 'location': 'location',
        'date': 'date', 'link': 'job_url', 'blurb': 'job_description'
    }
    df.rename(columns=column_mapping, inplace=True)
    df['source'] = 'Indeed'
    placeholder_columns = {
        'applied': 0, 'hidden': 0, 'interview': 0, 'rejected': 0,
        'cover_letter': '', 'resume': ''
    }
    for col, default_value in placeholder_columns.items():
        if col not in df.columns:
            df[col] = default_value
    required_cols = ['title', 'company', 'location', 'date', 'job_url', 'job_description', 'source']
    for col in required_cols:
        if col not in df.columns:
            df[col] = ''
    final_cols = [col for col in required_cols + list(placeholder_columns.keys()) if col in df.columns]
    return df[final_cols]


def scrape_indeed(config, existing_urls=set()):
    """
    Main function to scrape Indeed using the JobFunnel command-line tool.
    """
    print("--- Starting Indeed Scraper (JobFunnel) ---")
    start_time = tm.perf_counter()

    cfg = config['indeed_settings']
    output_csv_path = cfg['master_csv_file']

    # --- NEW STRATEGY: Cleanse the JSON files before every run ---
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

    print("Indeed: Running JobFunnel process...")
    try:
        # We must also run the subprocess with UTF-8 encoding to handle all characters
        subprocess.run(
            ['funnel', 'load', '-s', temp_yaml_path],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        print("Indeed: JobFunnel process completed successfully.")
    except FileNotFoundError:
        print("\nERROR: The 'funnel' command was not found.")
        os.remove(temp_yaml_path)
        return pd.DataFrame()
    except subprocess.CalledProcessError as e:
        print(f"Indeed: An error occurred while running JobFunnel.")
        print(f"STDERR: {e.stderr}")
        os.remove(temp_yaml_path)
        return pd.DataFrame()

    os.remove(temp_yaml_path)

    if not os.path.exists(output_csv_path):
        print("Indeed: Output CSV file not found. No jobs were scraped.")
        return pd.DataFrame()

    df = pd.read_csv(output_csv_path)
    print(f"Indeed: Found {len(df)} total jobs in the CSV file.")
    print(f"Indeed CSV columns: {df.columns.tolist()}")

    if 'link' not in df.columns:
        print("ERROR: The CSV file from JobFunnel does not contain the expected 'link' column.")
        return pd.DataFrame()

    df_new = df[~df['link'].isin(existing_urls)].copy()
    print(f"Indeed: Found {len(df_new)} new jobs to add.")

    if df_new.empty:
        print("Indeed: No new jobs to add to the database.")
        return pd.DataFrame()

    df_standardized = standardize_indeed_data(df_new, config)
    end_time = tm.perf_counter()
    print(f"--- Indeed scraping finished in {end_time - start_time:.2f} seconds ---")
    return df_standardized