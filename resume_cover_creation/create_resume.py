import google.generativeai as genai
import json
import os
import subprocess
import sys
import sqlite3
import argparse
from dotenv import load_dotenv
from pdf2docx import Converter

# --- Configuration ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'jobs.db')
BASE_OUTPUT_NAME = "tailored_resume"

def get_db_connection():
    """Connects to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_user_data_from_db(user_id):
    """Fetches the user's base resume data from the database."""
    print(f"Fetching resume data for user_id: {user_id}...")
    try:
        conn = get_db_connection()
        data_row = conn.execute("SELECT * FROM user_resume_data WHERE user_id = ?", (user_id,)).fetchone()
        conn.close()

        if not data_row:
            print(f"Error: No resume data found for user_id {user_id}.")
            sys.exit(1)

        resume_data = {}
        # Iterate over all columns in the fetched row
        for key in data_row.keys():
            # These are the columns expected to contain JSON data
            if key in ['education', 'experience', 'projects', 'skills', 'activities', 'custom_sections']:
                try:
                    # Use a default that makes sense for the key
                    default_value = '[]' if key != 'skills' else '{}'
                    resume_data[key] = json.loads(data_row[key] or default_value)
                except (json.JSONDecodeError, TypeError):
                    # If loading fails, assign a safe default
                    resume_data[key] = [] if key != 'skills' else {}
            else:
                resume_data[key] = data_row[key]
        print("Successfully fetched and parsed user data.")
        return resume_data
    except Exception as e:
        print(f"Database error while fetching user data: {e}")
        sys.exit(1)

def sanitize_latex(text):
    """Sanitizes text to be safe for LaTeX."""
    if not isinstance(text, str): return text
    return text.replace('&', r'\&').replace('%', r'\%').replace('$', r'\$').replace('#', r'\#').replace('_', r'\_').replace('{', r'\{').replace('}', r'\}').replace('~', r'\textasciitilde{}').replace('^', r'\textasciicircum{}')

def setup_api():
    """Configures the Gemini API."""
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not found.")
        sys.exit(1)
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        sys.exit(1)

def generate_tailored_content(model, base_resume, job_desc):
    """Generates tailored resume content."""
    print("Calling Gemini to tailor resume content...")
    sections_to_tailor = {
        "summary": base_resume.get("summary", ""),
        "experience": base_resume.get("experience", []),
        "projects": base_resume.get("projects", [])
    }
    original_summary_length = len(base_resume.get("summary", ""))
    
    prompt = f"""
    You are an expert resume writer and JSON editor. Your task is to take a base resume's summary, experience, and projects, and a target job description, then rewrite specific parts of those sections.

    **Instructions:**
    1.  **Rewrite 'summary'**: Create a new, powerful 'summary' that mirrors the language of the job description. It must be concise, between {original_summary_length - 40} and {original_summary_length} characters.
    
    2.  **Rewrite 'experience' Bullet Points**: For each object in the 'experience' array, you MUST keep the existing 'company', 'location', 'title', and 'dates' keys and their original values. Your ONLY task is to rewrite the 'points' array to use strong action verbs and metrics aligned with the job description.
    
    3.  **Rewrite 'projects'**: Re-imagine the 'projects' section. The final output must have exactly 3 projects.
        - If an existing project is relevant, keep its 'name' but make up dates along with months in the format "Month Year - Month Year" between the last three years(between 2025 to 2022 at most) for projects, the advanced one on the top to the botoom, and heavily rewrite its 'points' with keywords and metrics from the job description.
        - If a project is not relevant, replace it with a new, plausible project that is a perfect fit, including a 'name', 'dates', and tailored 'points'.

    4.  **Preserve Structure and Keys**: You MUST return ONLY a single, valid JSON object. It is critical that you maintain the original JSON structure perfectly. For 'experience' and 'projects', all original keys (like company, location, dates, etc.) must be present in your final output.
    
    5.  **Conciseness is Key**: Ensure all rewritten bullet points are concise to help the resume fit on a single page.

    **JSON to tailor:**
    ```json
    {json.dumps(sections_to_tailor, indent=2)}
    ```

    **Target Job Description:**
    ```
    {job_desc}
    ```

    Return ONLY the tailored and complete JSON object.
    """
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
        # Add this line to see what the AI is returning on an error
        print("--- Gemini's Raw Response ---")
        try:
            print(response.text)
        except NameError:
            print("Response object not available.")
        print("-----------------------------")
        return None

def build_latex_from_data(data):
    """Builds the entire LaTeX document from scratch using the provided data."""
    latex_parts = [r"""
\documentclass[letterpaper,11pt]{article}
\usepackage{latexsym}
\usepackage[empty]{fullpage}
\usepackage{titlesec}
\usepackage{marvosym}
\usepackage[usenames,dvipsnames]{color}
\usepackage{verbatim}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\usepackage{fancyhdr}
\usepackage[english]{babel}
\usepackage{tabularx}
\usepackage{fontawesome5}
\usepackage{multicol}
\setlength{\multicolsep}{-3.0pt}
\setlength{\columnsep}{-1.0pt}
\input{glyphtounicode}
\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}
\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}
\titleformat{\section}{
  \vspace{-4pt}\scshape\raggedright\large
}{}{0em}{}[\color{black}\titlerule \vspace{-5pt}]
\pdfgentounicode=1
\newcommand{\resumeItem}[1]{\item\small{{#1 \vspace{-3pt}}}}
\newcommand{\resumeSubheading}[4]{\vspace{-2pt}\item\begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}\textbf{#1} & #2 \\ \textit{\small#3} & \textit{\small #4} \\ \end{tabular*}\vspace{-7pt}}
\newcommand{\resumeSubSubheading}[2]{\item\begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}\textit{\small#1} & \textit{\small #2} \\ \end{tabular*}\vspace{-7pt}}
\newcommand{\resumeProjectHeading}[2]{\item\begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}\small#1 & #2 \\ \end{tabular*}\vspace{-7pt}}
\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}
\renewcommand\labelitemii{$\vcenter{\hbox{\tiny$\bullet$}}$}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
\begin{document}
"""]
    name = sanitize_latex(data.get('name', ''))
    phone = sanitize_latex(data.get('phone', ''))
    email = data.get('email', '')
    linkedin = data.get('linkedin', '')
    github = data.get('github', '')
    linkedin_user = linkedin.split('/')[-1] if 'linkedin.com' in linkedin else linkedin
    github_user = github.split('/')[-1] if 'github.com' in github else github
    
    latex_parts.append(f"""
\\begin{{center}}
    \\textbf{{\\Huge \\scshape {{\\fontsize{{15pt}}{{20pt}}\\selectfont {name}}}}} \\\\ \\vspace{{1pt}}
    \\small \\raisebox{{-0.1\\height}}\\faPhone\\ {phone} ~ \\href{{mailto:{email}}}{{\\raisebox{{-0.2\\height}}\\faEnvelope\\  \\underline{{{email}}}}} ~ 
    \\href{{{linkedin}}}{{\\raisebox{{-0.2\\height}}\\faLinkedin\\ \\underline{{linkedin.com/in/{linkedin_user}}}}} ~ 
    \\href{{{github}}}{{\\raisebox{{-0.2\\height}}\\faGithub\\ \\underline{{github.com/{github_user}}}}}
    \\vspace{{-8pt}}
\\end{{center}}
""")
    if data.get('summary'):
        latex_parts.extend([r"""\section{{\fontsize{9pt}{20pt}\selectfont \textbf{SUMMARY}}}\resumeSubHeadingListStart""", f"\\resumeItem{{{sanitize_latex(data['summary'])}}}", r"""\resumeSubHeadingListEnd\vspace{-18pt}"""])
    if data.get('education'):
        latex_parts.append(r"""\section{{\fontsize{9pt}{20pt}\selectfont \textbf{EDUCATION}}}\resumeSubHeadingListStart""")
        for edu in data.get('education', []):
            details_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(line)}}}" for line in edu.get('details', [])]) + "\n\\resumeItemListEnd"
            latex_parts.append(f"\\resumeSubheading{{{sanitize_latex(edu.get('university'))}}}{{\\textbf{{{sanitize_latex(edu.get('location'))}}}}}{{{sanitize_latex(edu.get('degree'))}}}{{{sanitize_latex(edu.get('dates'))}}}\n{details_latex}")
        latex_parts.append(r"""\resumeSubHeadingListEnd\vspace{-18pt}""")
    if data.get('experience'):
        latex_parts.append(r"""\section{{\fontsize{9pt}{20pt}\selectfont \textbf{EXPERIENCE}}}\resumeSubHeadingListStart""")
        for exp in data.get('experience', []):
            points_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(point)}}}" for point in exp.get('points', [])]) + "\n\\resumeItemListEnd"
            latex_parts.append(f"\\resumeSubheading{{{sanitize_latex(exp.get('company'))}}}{{\\textbf{{{sanitize_latex(exp.get('location'))}}}}}{{{sanitize_latex(exp.get('title'))}}}{{{sanitize_latex(exp.get('dates'))}}}\n{points_latex}")
        latex_parts.append(r"""\resumeSubHeadingListEnd\vspace{-17pt}""")
    if data.get('projects'):
        latex_parts.append(r"""\section{{\fontsize{9pt}{20pt}\selectfont \textbf{PROJECTS}}}\resumeSubHeadingListStart""")
        project_parts = []
        for proj in data.get('projects', []):
            points_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(point)}}}" for point in proj.get('points', [])]) + "\n\\resumeItemListEnd"
            project_parts.append(f"\\resumeProjectHeading{{\\textbf{{{sanitize_latex(proj.get('name'))}}}}}{{\\textit{{{sanitize_latex(proj.get('dates'))}}}}}\n{points_latex}")
        latex_parts.append("\\vspace{-6pt}\n".join(project_parts))
        latex_parts.append(r"""\resumeSubHeadingListEnd\vspace{-17pt}""")
    if data.get('skills'):
        latex_parts.append(r"""\section{{\fontsize{9pt}{20pt}\selectfont \textbf{SKILLS}}}\resumeSubHeadingListStart""")
        skills_latex = "\\vspace{-7pt}\n".join([f"\\resumeItem{{\\textbf{{{sanitize_latex(category)}:}} {sanitize_latex(skills)}}}" for category, skills in data.get('skills', {}).items()])
        latex_parts.append(skills_latex)
        latex_parts.append(r"""\resumeSubHeadingListEnd\vspace{-10pt}""")
    
    # NEW: Logic to add custom sections to the LaTeX document
    if data.get('custom_sections'):
        for section in data.get('custom_sections', []):
            if section.get('title') and section.get('points'):
                section_title = sanitize_latex(section.get('title', '')).upper()
                latex_parts.append(f"""\\section{{{{\\fontsize{{9pt}}{{20pt}}\\selectfont \\textbf{{{section_title}}}}}}}""")
                points_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(point)}}}\n\\vspace{{-8pt}}"for point in section.get('points', [])]) + "\n\\resumeItemListEnd"
                latex_parts.append(points_latex)
                latex_parts.append(r"""\vspace{-8pt}""")

    latex_parts.append(r"\end{document}")
    return "\n".join(latex_parts)

def find_unique_filename(base_path_and_name):
    """Finds a unique filename by appending a counter."""
    counter = 0
    while True:
        tex_filename = f"{base_path_and_name}_{counter}.tex" if counter > 0 else f"{base_path_and_name}.tex"
        if not os.path.exists(tex_filename):
            return tex_filename
        counter += 1

def main():
    """Main function to run the resume generation process."""
    parser = argparse.ArgumentParser(description="Generate a tailored resume.")
    parser.add_argument("job_description_path", type=str, help="Path to the job description text file.")
    parser.add_argument("--user-id", type=int, required=True, help="ID of the user.")
    parser.add_argument("--output-dir", type=str, required=True, help="Directory to save generated files.")
    args = parser.parse_args()

    print(f"--- Starting Resume Tailor for User ID: {args.user_id} ---")
    base_resume_data = get_user_data_from_db(args.user_id)
    
    model = setup_api()
    with open(args.job_description_path, 'r', encoding='utf-8') as f:
        job_description_text = f.read()

    tailored_sections = generate_tailored_content(model, base_resume_data, job_description_text)
    if not tailored_sections:
        print("Halting: AI content generation for resume failed.")
        sys.exit(1)
        
    print("AI has generated the tailored content for the resume.")
    final_resume_data = {**base_resume_data, **tailored_sections}
    
    output_json_file = os.path.join(args.output_dir, f"{BASE_OUTPUT_NAME}_tailored_data.json")
    with open(output_json_file, 'w', encoding='utf-8') as f:
        json.dump(final_resume_data, f, indent=2)
    print(f"Saved tailored data to '{os.path.basename(output_json_file)}'")

    final_latex = build_latex_from_data(final_resume_data)
    
    output_latex_base = os.path.join(args.output_dir, BASE_OUTPUT_NAME)
    output_latex_file = find_unique_filename(output_latex_base)
    
    with open(output_latex_file, 'w', encoding='utf-8') as f:
        f.write(final_latex)

    for _ in range(2):
        process = subprocess.run(['pdflatex', '-interaction=nonstopmode', os.path.basename(output_latex_file)], cwd=args.output_dir, capture_output=True, text=True, encoding='utf-8')
    
    final_pdf_path = os.path.join(args.output_dir, os.path.basename(output_latex_file).replace('.tex', '.pdf'))
    
    if not os.path.exists(final_pdf_path):
        print(f"Error: Resume PDF compilation failed. Check log in {args.output_dir}")
        sys.exit(1)
        
    print(f"Successfully created resume PDF: {os.path.basename(final_pdf_path)}")
    
    try:
        cv = Converter(final_pdf_path)
        cv.convert(final_pdf_path.replace('.pdf', '.docx'), start=0, end=None)
        cv.close()
        print(f"Successfully converted resume to DOCX.")
    except Exception as e:
        print(f"Could not convert resume to DOCX. Error: {e}")
        
    print("\n--- Proceeding to cover letter generation ---")
    try:
        cover_letter_script_path = os.path.join(os.path.dirname(__file__), 'create_cover_letter.py')
        command = [
            sys.executable,
            cover_letter_script_path,
            output_json_file,
            args.job_description_path,
            '--user-id', str(args.user_id),
            '--output-dir', args.output_dir
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
        print("--- Cover Letter Script STDOUT ---")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("\n" + "="*60)
        print("--- FATAL ERROR: THE COVER LETTER SCRIPT FAILED TO RUN ---")
        print(f"--- Return Code: {e.returncode}")
        print("\n--- STDOUT from cover letter script ---")
        print(e.stdout)
        print("\n--- STDERR from cover letter script (THIS IS THE ERROR) ---")
        print(e.stderr)
        print("="*60 + "\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
