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
    """
    Generates tailored resume content, respecting user-provided data.
    If a field is empty, the AI generates content. If it's filled, the AI uses the existing content.
    """
    print("Calling Gemini to intelligently tailor resume content...")
    sections_to_tailor = {
        "summary": base_resume.get("summary", ""),
        "experience": base_resume.get("experience", []),
        "projects": base_resume.get("projects", [])
    }

    # The prompt is updated to give the AI conditional instructions.
    prompt = f"""
    You are an expert resume writer and a meticulous JSON editor. Your task is to intelligently process a resume's JSON data based on a job description. You must follow these rules precisely:

    **Instructions:**

    1.  **Handle the 'summary'**:
        * **If the 'summary' field is NOT empty**: Refine the existing summary. Enhance it with keywords from the job description while keeping its original tone. The length should remain similar.
        * **If the 'summary' field IS empty**: Write a compelling new summary from scratch, tailored perfectly to the job description using details from the experience and projects.

    2.  **Handle the 'experience' array**:
        * Iterate through each object in the 'experience' array.
        * For each object, check its 'points' array.
        * **If the 'points' array is NOT empty**: You MUST keep the existing bullet points exactly as they are. Do not change them.
        * **If the 'points' array IS empty**: You MUST generate 3-4 strong, concise bullet points using action verbs and metrics that align the job title with the target job description.

    3.  **Handle the 'projects' array to ensure a total of THREE**:
        * Your primary goal is to return a 'projects' array containing exactly 3 projects.
        * **First, preserve the user's projects**: Identify all complete projects in the provided `projects` array. A project is complete if its `name` and `points` are not empty. You MUST keep these user-provided projects in the final output. You may lightly refine their `points` to better align with the job description, but the core project must remain.
        * **Then, count the user's projects and generate the remainder**: After preserving the user's projects, count them. If the count is less than 3, you MUST generate new, highly-relevant projects to make up the difference.
            * If the user provided 2 projects, you generate 1 new one.
            * If the user provided 1 project, you generate 2 new ones.
            * If the user provided 0 projects, you generate 3 new ones.
        * **Format for NEW projects**: Each newly generated project must have a plausible 'name', 'dates' (e.g., "Month Year - Month Year" within the last 3 years), and a detailed 'points' array showcasing skills from the job description.

    4.  **Output Requirements**:
        * You MUST return ONLY a single, valid JSON object containing the 'summary', 'experience', and 'projects' keys.
        * Preserve the exact structure and all original keys for every object. For 'experience', this means 'company', 'location', 'title', and 'dates' must be returned untouched for every entry.

    **JSON to tailor:**
    ```json
    {json.dumps(sections_to_tailor, indent=2)}
    ```

    **Target Job Description:**
    ```
    {job_desc}
    ```

    Return ONLY the tailored and complete JSON object, following all instructions.
    """
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
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
    # This simple merge now works because the AI was instructed to respect existing user data.
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