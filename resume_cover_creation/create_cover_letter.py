import google.generativeai as genai
import json
import os
import sys
import subprocess
import argparse
from dotenv import load_dotenv
from datetime import datetime

# --- Configuration ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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

def build_latex_document(user_data, letter_body_content):
    """
    Builds the entire LaTeX document from scratch, including the header,
    the generated letter body, and the closing commands.
    """
    # --- Part 1: The LaTeX Preamble and Header ---
    # This section is identical to your resume's structure.
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
% Page Style
\pagestyle{fancy}
\fancyhf{}
\fancyfoot{}
\renewcommand{\headrulewidth}{0pt}
\renewcommand{\footrulewidth}{0pt}
% Margins
\addtolength{\oddsidemargin}{-0.5in}
\addtolength{\evensidemargin}{-0.5in}
\addtolength{\textwidth}{1in}
\addtolength{\topmargin}{-.5in}
\addtolength{\textheight}{1.0in}
% URL Style
\urlstyle{same}
\raggedbottom
\raggedright
\setlength{\tabcolsep}{0in}
\pdfgentounicode=1
% Spacing
\setlength{\parindent}{0em}
\setlength{\parskip}{1em}
% Document Start
\begin{document}
"""]
    name = sanitize_latex(user_data.get('name', ''))
    phone = sanitize_latex(user_data.get('phone', ''))
    email = user_data.get('email', '') # No sanitize for hyperlinking
    linkedin = user_data.get('linkedin', '')
    github = user_data.get('github', '')
    linkedin_user = linkedin.split('/')[-1] if 'linkedin.com' in linkedin else linkedin
    github_user = github.split('/')[-1] if 'github.com' in github else github

    latex_parts.append(f"""
% --- HEADER ---
\\begin{{center}}
    \\textbf{{\\Huge \\scshape {{\\fontsize{{15pt}}{{20pt}}\\selectfont {name}}}}} \\\\ \\vspace{{1pt}}
    \\small \\raisebox{{-0.1\\height}}\\faPhone\\ {phone} ~ \\href{{mailto:{email}}}{{\\raisebox{{-0.2\\height}}\\faEnvelope\\  \\underline{{{sanitize_latex(email)}}}}} ~
    \\href{{{linkedin}}}{{\\raisebox{{-0.2\\height}}\\faLinkedin\\ \\underline{{linkedin.com/in/{linkedin_user}}}}} ~
    \\href{{{github}}}{{\\raisebox{{-0.2\\height}}\\faGithub\\ \\underline{{github.com/{github_user}}}}}
\\end{{center}}
\\vspace{{0.5cm}}
""")

    # --- Part 2: The AI-Generated Cover Letter Body ---
    latex_parts.append(letter_body_content)

    # --- Part 3: The Closing of the LaTeX Document ---
    latex_parts.append(r"\end{document}")

    return "\n".join(latex_parts)

def generate_cover_letter_body(model, full_resume_data, job_desc):
    """Generates only the body of a tailored LaTeX cover letter."""
    print("Calling Gemini to write the cover letter body...")
    
    # Context now only includes the most relevant parts for content generation
    tailored_resume_context = {
        "summary": full_resume_data.get("summary"), 
        "experience": full_resume_data.get("experience"), 
        "projects": full_resume_data.get("projects")
    }
    
    prompt = f"""
    You are an expert career advisor writing a compelling cover letter body. Always use text to say numbers like (Fifteen percent) and never use numericals.
    **Task:** Write the body of a cover letter. Your output MUST start with the date and recipient and end with the closing (e.g., "Sincerely,"). DO NOT include the user's header, \\documentclass, \\begin{{document}}, or \\end{{document}}.

    **Instructions:**
    1.  **Start with the Date and Recipient:** Begin with today's date: {datetime.now().strftime('%B %d, %Y')}. Below that, add the recipient's details. If a specific person is not mentioned in the job description, address it to "Hiring Manager".
    2.  **Write a Compelling Body:** If you ever mentioned a number specify the percentage symbol beside it and immediately followed by the impact it created in what part of the success, for example efficiency, development time, user engagement, cost reduction, or revenue.Do not ever mention where the Job is posted, just say as posted on your job board. Create a three to four paragraph body that is perfectly tailored to the job description.
    3.  **Integrate Achievements:** Weave in specific, quantifiable achievements from the "TAILORED RESUME CONTEXT" (especially from the 'experience' and 'projects' sections) as concrete evidence of skills.
    4.  **Quantify and Specify Impact:** Every number write it in text form and add percent impact it created in the efficiency, revenue or anything that is concerned.
    5.  **Mirror Language and Specify Impact:** Reflect the tone, keywords, and priorities found in the job description. Align your phrasing with the company’s voice and highlight achievements that relate directly to their stated needs. End every paragraph with a period(.).
    6.  **End with a Professional Closing:** Conclude with "Sincerely," followed by a signature, and then the user's typed name: {full_resume_data.get('name')}.
    7.  **Output Raw Text/LaTeX:** Your response must ONLY be the text and LaTeX for the letter's content, ready to be placed inside a LaTeX document. Ensure all special characters are properly escaped for LaTeX.

    ---
    **1. TAILORED RESUME CONTEXT (for achievements):**
    ```json
    {json.dumps(tailored_resume_context, indent=2)}
    ```
    ---
    **2. TARGET JOB DESCRIPTION (for keywords and company info):**
    ```
    {job_desc}
    ```
    ---
    Generate only the cover letter body now.
    """
    try:
        response = model.generate_content(prompt)
        # Basic cleaning, assuming the model follows instructions
        cleaned_response = response.text.strip()
        if cleaned_response.startswith("```latex"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        return cleaned_response.strip()
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        return None

def main():
    """Main function to run the cover letter generation process."""
    parser = argparse.ArgumentParser(description="Generate a tailored LaTeX cover letter.")
    parser.add_argument("resume_data_path", type=str, help="Path to the tailored resume JSON file.")
    parser.add_argument("job_description_path", type=str, help="Path to the job description text file.")
    parser.add_argument("--user-id", type=int, required=True, help="ID of the user.")
    parser.add_argument("--output-dir", type=str, required=True, help="Directory to save generated files.")
    args = parser.parse_args()

    print(f"--- Starting Cover Letter Generator for User ID: {args.user_id} ---")

    try:
        with open(args.resume_data_path, 'r', encoding='utf-8') as f:
            full_tailored_resume_data = json.load(f)
        with open(args.job_description_path, 'r', encoding='utf-8') as f:
            job_description = f.read()
    except FileNotFoundError as e:
        print(f"Error: Could not find required file: {e.filename}")
        sys.exit(1)

    # Step 1: Setup API
    model = setup_api()

    # Step 2: Generate ONLY the body content of the letter
    letter_body = generate_cover_letter_body(model, full_tailored_resume_data, job_description)

    if not letter_body:
        print("Halting: AI content generation for cover letter failed.")
        sys.exit(1)
    print("AI has generated the tailored cover letter body.")

    # Step 3: Build the FULL LaTeX document using the generated body
    final_latex_content = build_latex_document(full_tailored_resume_data, letter_body)

    # Step 4: Save the final .tex file
    base_output_name = os.path.basename(args.resume_data_path).replace('_tailored_data.json', '_cover_letter')
    latex_filename = os.path.join(args.output_dir, f"{base_output_name}.tex")

    with open(latex_filename, 'w', encoding='utf-8') as f:
        f.write(final_latex_content)
    print(f"Successfully created tailored LaTeX file: {os.path.basename(latex_filename)}")

    # Step 5: Compile the LaTeX file into a PDF
    print("Compiling PDF from LaTeX...")
    process = None
    for _ in range(2): # Run twice for cross-referencing
        process = subprocess.run(
            ['pdflatex', '-interaction=nonstopmode', os.path.basename(latex_filename)],
            cwd=args.output_dir,
            capture_output=True, text=True, encoding='utf-8'
        )

    pdf_filename = latex_filename.replace('.tex', '.pdf')
    if os.path.exists(pdf_filename):
        print(f"Successfully created cover letter PDF: {os.path.basename(pdf_filename)}")
    else:
        print(f"Error: PDF compilation failed. Check the .log file in {args.output_dir}")
        print("\n--- pdflatex STDOUT ---")
        print(process.stdout if process else "No process output.")
        print("\n--- pdflatex STDERR ---")
        print(process.stderr if process else "No process output.")
        sys.exit(1)

if __name__ == "__main__":
    main()