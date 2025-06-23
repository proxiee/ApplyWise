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
DB_PATH = os.path.join('..', '..', 'data', 'jobs.db') # This is the corrected path
BASE_OUTPUT_NAME = "tailored_resume"

def get_db_connection():
    """Connects to the SQLite database."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_user_data_from_db(user_id):
    """Fetches the user's base resume data from the database."""
    print(f"Fetching resume data for user_id: {user_id}...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_resume_data WHERE user_id = ?", (user_id,))
        data_row = cursor.fetchone()
        conn.close()

        if not data_row:
            print(f"Error: No resume data found for user_id {user_id}.")
            sys.exit(1)

        # Convert JSON strings back to Python objects
        resume_data = {
            'name': data_row['name'],
            'email': data_row['email'],
            'phone': data_row['phone'],
            'linkedin': data_row['linkedin'],
            'github': data_row['github'],
            'summary': data_row['summary'],
            'education': json.loads(data_row['education'] or '[]'),
            'experience': json.loads(data_row['experience'] or '[]'),
            'projects': json.loads(data_row['projects'] or '[]'),
            'skills': json.loads(data_row['skills'] or '{}'),
            'activities': json.loads(data_row['activities'] or '[]')
        }
        print("Successfully fetched and parsed user data.")
        return resume_data
    except Exception as e:
        print(f"Database error while fetching user data: {e}")
        sys.exit(1)

# Keep your existing functions:
# sanitize_latex(text)
# setup_api()
# generate_tailored_content(model, base_resume, job_desc)
# build_latex_from_data(data)
# find_unique_filename(base_name)

# (Paste all those functions here from your original file)
# ...
# The following is a consolidated version of those functions
def sanitize_latex(text):
    if not isinstance(text, str): return text
    return text.replace('&', r'\&').replace('%', r'\%').replace('$', r'\$').replace('#', r'\#').replace('_', r'\_').replace('{', r'\{').replace('}', r'\}').replace('~', r'\textasciitilde{}').replace('^', r'\textasciicircum{}')

def setup_api():
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
    print("Calling Gemini to tailor content for the job...")
    sections_to_tailor = {"summary": base_resume["summary"], "experience": base_resume["experience"], "projects": base_resume["projects"]}
    original_summary_length = len(base_resume.get("summary", ""))
    prompt = f"""
    You are an expert resume writer. Your task is to take a base resume's summary, experience, and projects, and a target job description, then rewrite those sections to be perfectly tailored for the job, ensuring the final resume fits on a single page.
    **Instructions:**
    1.  Rewrite the 'summary' to be a powerful introduction that mirrors the language of the job description. The original summary is {original_summary_length} characters long. The new summary **MUST be very concise, approximately {original_summary_length - 40} to {original_summary_length} characters**, to ensure it fits within 3 lines on the final PDF.
    2.  For each job in 'experience', rewrite the 'points' to use strong action verbs and include quantifiable metrics that align with the job description. Be concise.
    3.  **Re-imagine the 'projects' section to have exactly 3 projects in total.** If an existing project is relevant, heavily rewrite it with keywords and quantifiable numbers from the job description. If a project is not relevant, replace it with a new, plausible project that is a perfect fit. The inclusion of keywords and metrics is mandatory.
    4.  **Prioritize Conciseness for a One-Page Layout:** For all bullet points in 'experience' and 'projects', the new text must not be significantly longer than the original. Brevity is critical to ensure the entire resume fits on a single page.
    5.  You MUST return ONLY a single, valid JSON object containing the updated 'summary', 'experience', and 'projects' sections. Maintain the original JSON structure perfectly.

    **JSON to tailor:**
    ```json
    {json.dumps(sections_to_tailor, indent=2)}
    ```

    **Target Job Description:**
    ```
    {job_desc}
    ```

    Return ONLY the tailored JSON object. """
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
        return None

def build_latex_from_data(data):
    # This function should be exactly the same as your original one
    # ... (omitted for brevity, but make sure it's here)
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
\newcommand{\resumeSubheading}[4]{\vspace{-2pt}\item\begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}\textbf{#1} & #2 \\\textit{\small#3} & \textit{\small #4} \\\end{tabular*}\vspace{-7pt}}
\newcommand{\resumeSubSubheading}[2]{\item\begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}\textit{\small#1} & \textit{\small #2} \\\end{tabular*}\vspace{-7pt}}
\newcommand{\resumeProjectHeading}[2]{\item\begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}\small#1 & #2 \\\end{tabular*}\vspace{-7pt}}
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
        latex_parts.append(r"""
\section{{\fontsize{9pt}{20pt}\selectfont \textbf{SUMMARY}}}
\resumeSubHeadingListStart
""")
        latex_parts.append(f"\\resumeItem{{{sanitize_latex(data['summary'])}}}")
        latex_parts.append(r"""\resumeSubHeadingListEnd
\vspace{-18pt}""")
    if data.get('education'):
        latex_parts.append(r"""
\section{{\fontsize{9pt}{20pt}\selectfont \textbf{EDUCATION}}}
\resumeSubHeadingListStart""")
        for edu in data['education']:
            details_list = []
            for line in edu.get('details', []):
                if ':' in line:
                    parts = line.split(':', 1)
                    details_list.append(f"\\resumeItem{{\\textbf{{{sanitize_latex(parts[0])}:}}{sanitize_latex(parts[1])}}}")
                else:
                    details_list.append(f"\\resumeItem{{{sanitize_latex(line)}}}")
            details_latex = "\\resumeItemListStart\n" + "\n".join(details_list) + "\n\\resumeItemListEnd"
            latex_parts.append(f"\\resumeSubheading{{{sanitize_latex(edu.get('university'))}}}{{\\textbf{{{sanitize_latex(edu.get('location'))}}}}}{{{sanitize_latex(edu.get('degree'))}}}{{{sanitize_latex(edu.get('dates'))}}}\n{details_latex}")
        latex_parts.append(r"""\resumeSubHeadingListEnd
\vspace{-18pt}""")
    if data.get('experience'):
        latex_parts.append(r"""
\section{{\fontsize{9pt}{20pt}\selectfont \textbf{EXPERIENCE}}}
\resumeSubHeadingListStart""")
        for exp in data['experience']:
            points_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(point)}}}" for point in exp.get('points', [])]) + "\n\\resumeItemListEnd"
            latex_parts.append(f"\\resumeSubheading{{{sanitize_latex(exp.get('company'))}}}{{\\textbf{{{sanitize_latex(exp.get('location'))}}}}}{{{sanitize_latex(exp.get('title'))}}}{{{sanitize_latex(exp.get('dates'))}}}\n{points_latex}")
        latex_parts.append(r"""\resumeSubHeadingListEnd
\vspace{-17pt}""")
    if data.get('projects'):
        latex_parts.append(r"""
\section{{\fontsize{9pt}{20pt}\selectfont \textbf{PROJECTS}}}
\resumeSubHeadingListStart""")
        project_parts = []
        for proj in data['projects']:
            points_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(point)}}}" for point in proj.get('points', [])]) + "\n\\resumeItemListEnd"
            project_parts.append(f"\\resumeProjectHeading{{\\textbf{{{sanitize_latex(proj.get('name'))}}}}}{{\\textit{{{sanitize_latex(proj.get('dates'))}}}}}\n{points_latex}")
        latex_parts.append("\\vspace{-6pt}\n".join(project_parts))
        latex_parts.append(r"""\resumeSubHeadingListEnd
\vspace{-17pt}""")
    if data.get('activities'):
        latex_parts.append(r"""
\section{{\fontsize{9pt}{20pt}\selectfont \textbf{ACTIVITIES AND LEADERSHIP}}}
\resumeSubHeadingListStart""")
        for act in data['activities']:
            roles_latex = "\\resumeItemListStart\n" + "\n".join([f"\\resumeItem{{{sanitize_latex(role.get('title'))}}} \\hfill \\textit{{{sanitize_latex(role.get('dates'))}}}" for role in act.get('roles', [])]) + "\n\\resumeItemListEnd"
            latex_parts.append(f"\\resumeSubheading{{{sanitize_latex(act.get('organization'))}}}{{\\textbf{{{sanitize_latex(act.get('location'))}}}}}{{}}{{}}\n\\vspace{{-17pt}}\n{roles_latex}")
        latex_parts.append(r"""\resumeSubHeadingListEnd
\vspace{-18pt}""")
    if data.get('skills'):
        latex_parts.append(r"""
\section{{\fontsize{9pt}{20pt}\selectfont \textbf{SKILLS}}}
\resumeSubHeadingListStart""")
        skills_latex = "\\vspace{-7pt}\n".join([f"\\resumeItem{{\\textbf{{{sanitize_latex(category)}:}} {sanitize_latex(skills)}}}" for category, skills in data['skills'].items()])
        latex_parts.append(skills_latex)
        latex_parts.append(r"""\resumeSubHeadingListEnd
\vspace{-10pt}""")
    latex_parts.append(r"\end{document}")
    return "\n".join(latex_parts)

def find_unique_filename(base_name):
    counter = 0
    while True:
        tex_filename = f"{base_name}_{counter}.tex" if counter > 0 else f"{base_name}.tex"
        if not os.path.exists(tex_filename):
            return tex_filename
        counter += 1

def main():
    parser = argparse.ArgumentParser(description="Generate a tailored resume.")
    parser.add_argument("job_description_path", type=str, help="Path to the job description text file.")
    parser.add_argument("--user-id", type=int, required=True, help="ID of the user to generate the resume for.")
    args = parser.parse_args()

    print(f"--- Starting Resume Tailor for User ID: {args.user_id} ---")
    
    # Step 1: Get user's base resume data from the database
    base_resume_data = get_user_data_from_db(args.user_id)
    
    # Step 2: Tailor content
    print("\n--- Tailoring content for the job ---")
    model = setup_api()
    with open(args.job_description_path, 'r', encoding='utf-8') as f:
        job_description_text = f.read()

    tailored_sections = generate_tailored_content(model, base_resume_data, job_description_text)
    if not tailored_sections:
        print("Exiting due to API error.")
        sys.exit(1)
        
    print("\nAI has generated the tailored content.")
    final_resume_data = base_resume_data.copy()
    final_resume_data.update(tailored_sections)
    
    # Save tailored JSON for the cover letter script to use
    output_json_file = f"{BASE_OUTPUT_NAME}_tailored_data.json"
    with open(output_json_file, 'w', encoding='utf-8') as f:
        # Save the full data so cover letter has access to name, etc.
        json.dump(final_resume_data, f, indent=2) 
    print(f"Saved tailored data for cover letter to '{output_json_file}'")

    # Step 3: Build and Compile PDF
    print("\n--- Compiling PDF and Word Document ---")
    final_latex = build_latex_from_data(final_resume_data)
    
    output_latex_file = find_unique_filename(BASE_OUTPUT_NAME)
    output_pdf_file = output_latex_file.replace('.tex', '.pdf')
    
    with open(output_latex_file, 'w', encoding='utf-8') as f:
        f.write(final_latex)

    process = subprocess.run(['pdflatex', '-interaction=nonstopmode', output_latex_file], capture_output=True, text=True, encoding='utf-8')
    if process.returncode != 0:
         # Run again to resolve references, even if the first run failed, to get a better log
        subprocess.run(['pdflatex', '-interaction=nonstopmode', output_latex_file], capture_output=True, text=True, encoding='utf-8')
        print(f"Error: PDF compilation failed. Check '{output_latex_file.replace('.tex', '.log')}'")
        sys.exit(1)

    # Compile a second time to ensure table of contents/references are correct
    subprocess.run(['pdflatex', '-interaction=nonstopmode', output_latex_file], capture_output=True, text=True, encoding='utf-8')
    print(f"Successfully created {output_pdf_file}")

    # Convert to DOCX
    docx_file = output_pdf_file.replace('.pdf', '.docx')
    print(f"Converting to {docx_file}...")
    try:
        cv = Converter(output_pdf_file)
        cv.convert(docx_file, start=0, end=None)
        cv.close()
        print(f"Successfully created {docx_file}!")
    except Exception as e:
        print(f"Could not convert PDF to DOCX. Error: {e}")
        
    # Step 4: Run the cover letter script
    print("\n--- Proceeding to cover letter generation ---")
    try:
        command = [
            sys.executable, 'create_cover_letter.py',
            output_json_file, # Path to the tailored JSON we just saved
            args.job_description_path,
            '--user-id', str(args.user_id) # Pass user ID along
        ]
        subprocess.run(command, check=True)
    except Exception as e:
        print(f"Error executing cover letter script: {e}")

if __name__ == "__main__":
    main()