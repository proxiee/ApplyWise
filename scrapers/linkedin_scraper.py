import requests
import json
import pandas as pd
from bs4 import BeautifulSoup
import time as tm
from itertools import groupby
from datetime import datetime, timedelta, time
from urllib.parse import quote
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException

# All helper functions from your main.py are kept here:
# get_with_retry, transform, transform_job, safe_detect,
# remove_irrelevant_jobs, remove_duplicates, convert_date_format, job_exists

def get_with_retry(url, config, retries=3, delay=1):
    # Get the URL with retries and delay
    for i in range(retries):
        try:
            if len(config['app_settings']['proxies']) > 0:
                r = requests.get(url, headers=config['app_settings']['headers'], proxies=config['app_settings']['proxies'], timeout=5)
            else:
                r = requests.get(url, headers=config['app_settings']['headers'], timeout=5)
            return BeautifulSoup(r.content, 'html.parser')
        except requests.exceptions.Timeout:
            print(f"Timeout occurred for URL: {url}, retrying in {delay}s...")
            tm.sleep(delay)
        except Exception as e:
            print(f"An error occurred while retrieving the URL: {url}, error: {e}")
    return None

def transform(soup):
    # Parsing the job card info (title, company, location, date, job_url) from the beautiful soup object
    joblist = []
    try:
        divs = soup.find_all('div', class_='base-search-card__info')
    except:
        print("Empty page, no jobs found")
        return joblist
    for item in divs:
        title = item.find('h3').text.strip()
        company = item.find('a', class_='hidden-nested-link')
        location = item.find('span', class_='job-search-card__location')
        parent_div = item.parent
        entity_urn = parent_div['data-entity-urn']
        job_posting_id = entity_urn.split(':')[-1]
        job_url = 'https://www.linkedin.com/jobs/view/'+job_posting_id+'/'

        date_tag_new = item.find('time', class_ = 'job-search-card__listdate--new')
        date_tag = item.find('time', class_='job-search-card__listdate')
        date = date_tag['datetime'] if date_tag else date_tag_new['datetime'] if date_tag_new else ''
        
        job = {
            'title': title,
            'company': company.text.strip().replace('\n', ' ') if company else '',
            'location': location.text.strip() if location else '',
            'date': date,
            'job_url': job_url,
            'job_description': '',
            'source': 'LinkedIn' # Add the source
        }
        joblist.append(job)
    return joblist

def transform_job(soup):
    div = soup.find('div', class_='description__text description__text--rich')
    if div:
        for element in div.find_all(['span', 'a']):
            element.decompose()
        for ul in div.find_all('ul'):
            for li in ul.find_all('li'):
                li.insert(0, '-')
        text = div.get_text(separator='\n').strip()
        text = text.replace('\n\n', '').replace('::marker', '-').replace('-\n', '- ').replace('Show less', '').replace('Show more', '')
        return text
    else:
        return "Could not find Job Description"

def safe_detect(text):
    try:
        return detect(text)
    except LangDetectException:
        return 'en'

def remove_irrelevant_jobs(joblist, config):
    cfg = config['linkedin_settings']
    new_joblist = [job for job in joblist if not any(word.lower() in job['job_description'].lower() for word in cfg['desc_exclude'])]
    new_joblist = [job for job in new_joblist if not any(word.lower() in job['title'].lower() for word in cfg['title_exclude'])] if len(cfg['title_exclude']) > 0 else new_joblist
    new_joblist = [job for job in new_joblist if any(word.lower() in job['title'].lower() for word in cfg['title_include'])] if len(cfg['title_include']) > 0 else new_joblist
    new_joblist = [job for job in new_joblist if safe_detect(job['job_description']) in cfg['languages']] if len(cfg['languages']) > 0 else new_joblist
    new_joblist = [job for job in new_joblist if not any(word.lower() in job['company'].lower() for word in cfg['company_exclude'])] if len(cfg['company_exclude']) > 0 else new_joblist
    return new_joblist

def remove_duplicates(joblist):
    joblist.sort(key=lambda x: (x['title'], x['company']))
    return [next(g) for k, g in groupby(joblist, key=lambda x: (x['title'], x['company']))]

def convert_date_format(date_string):
    try:
        return datetime.strptime(date_string, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None

def get_jobcards(config):
    all_jobs = []
    cfg = config['linkedin_settings']
    for query in cfg['search_queries']:
        keywords = quote(query['keywords'])
        location = quote(query['location'])
        for i in range(0, cfg['pages_to_scrape']):
            url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keywords}&location={location}&f_WT={query['f_WT']}&geoId=&f_TPR={cfg['timespan']}&start={25*i}"
            soup = get_with_retry(url, config)
            if soup:
                jobs = transform(soup)
                all_jobs.extend(jobs)
                print(f"LinkedIn: Scraped {len(jobs)} jobs from page: {url}")
    
    print(f"LinkedIn: Total job cards scraped: {len(all_jobs)}")
    all_jobs = remove_duplicates(all_jobs)
    print(f"LinkedIn: Total jobs after removing duplicates: {len(all_jobs)}")
    return all_jobs

def scrape_linkedin(config, existing_urls=set()):
    """
    Main function to scrape LinkedIn jobs.
    It returns a list of job dictionaries, ready to be committed to the database.
    """
    print("--- Starting LinkedIn Scraper ---")
    start_time = tm.perf_counter()
    
    # Scrape job cards from search results
    all_jobs = get_jobcards(config)
    
    # Filter out jobs that are already in the database
    new_jobs_to_fetch = [job for job in all_jobs if job['job_url'] not in existing_urls]
    print(f"LinkedIn: Found {len(new_jobs_to_fetch)} new job cards to process.")

    final_job_list = []
    if not new_jobs_to_fetch:
        print("LinkedIn: No new jobs to add.")
        return pd.DataFrame()

    for job in new_jobs_to_fetch:
        job_date = convert_date_format(job['date'])
        if not job_date or job_date < (datetime.now() - timedelta(days=config['linkedin_settings']['days_to_scrape'])).date():
            continue
            
        print(f"LinkedIn: Fetching description for: {job['title']} at {job['company']}")
        desc_soup = get_with_retry(job['job_url'], config)
        if desc_soup:
            job['job_description'] = transform_job(desc_soup)
            final_job_list.append(job)

    # Final filtering based on the full description
    if not final_job_list:
        print("LinkedIn: No jobs remained after fetching descriptions.")
        return pd.DataFrame()
        
    jobs_to_add = remove_irrelevant_jobs(final_job_list, config)
    print(f"LinkedIn: Total jobs to add after final filtering: {len(jobs_to_add)}")

    df = pd.DataFrame(jobs_to_add)

    end_time = tm.perf_counter()
    print(f"--- LinkedIn scraping finished in {end_time - start_time:.2f} seconds ---")
    
    return df