import google.generativeai as genai
import json
import os
import subprocess
import sys
from dotenv import load_dotenv
from datetime import datetime
from pdf2docx import Converter # <-- Added for DOCX conversion

# --- CONFIGURATION ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
BASE_RESUME_PATH = "resume_data.json"
LATEX_TEMPLATE_PATH = "template.tex"
JSON_RULES_PATH = "json_command.txt"
ARCHIVE_FOLDER = "json_archive"
if len(sys.argv) < 2:
    print("Usage: python create_resume.py <path_to_job_description.txt>")
    sys.exit(1)
JOB_DESCRIPTION_PATH = sys.argv[1]
BASE_OUTPUT_NAME = "tailored_resume"

def sanitize_latex(text):
    """Sanitizes text to be safe for LaTeX."""
    if not isinstance(text, str):
        return text
    text = text.replace('&', r'\&')
    text = text.replace('%', r'\%')
    text = text.replace('$', r'\$')
    text = text.replace('#', r'\#')
    text = text.replace('_', r'\_')
    text = text.replace('{', r'\{')
    text = text.replace('}', r'\}')
    text = text.replace('~', r'\textasciitilde{}')
    text = text.replace('^', r'\textasciicircum{}')
    return text

def setup_api():
    """Configures the Gemini API and handles missing API key."""
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not found.")
        print("Please ensure you have a .env file with the line: GEMINI_API_KEY=\"your-key\"")
        sys.exit(1)
    
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        sys.exit(1)

def archive_old_json():
    """Moves the existing JSON data file to an archive folder with a timestamp."""
    print("Checking for existing JSON file to archive...")
    if not os.path.exists(ARCHIVE_FOLDER):
        os.makedirs(ARCHIVE_FOLDER)
        print(f"Created archive folder: '{ARCHIVE_FOLDER}'")

    if os.path.exists(BASE_RESUME_PATH):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        archive_path = os.path.join(ARCHIVE_FOLDER, f"resume_data_{timestamp}.json")
        os.rename(BASE_RESUME_PATH, archive_path)
        print(f"Safely archived previous data to '{archive_path}'")
    else:
        print("No existing JSON file found to archive. Skipping.")


def update_json_from_template(model):
    """
    Reads the LaTeX template and a rules file, then asks the AI to parse the
    template and create an updated resume_data.json file.
    """
    print("Calling Gemini to parse template and create new JSON...")
    try:
        with open(LATEX_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            template_content = f.read()
        with open(JSON_RULES_PATH, 'r', encoding='utf-8') as f:
            json_rules = f.read()

        prompt = f"""
        You are a highly precise data extraction tool. Your task is to read the content from a LaTeX file and convert it into a valid JSON object. You must strictly follow the formatting rules provided. Ensure all text content is extracted accurately.

        **Rules for the JSON structure:**
        ---
        {json_rules}
        ---

        **LaTeX file content to parse:**
        ```latex
        {template_content}
        ```

        Your output must be ONLY the valid JSON object, with no other text, comments, or explanations.
        """

        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().lstrip("```json").rstrip("```").strip()
        new_json_data = json.loads(cleaned_response)

        with open(BASE_RESUME_PATH, 'w', encoding='utf-8') as f:
            json.dump(new_json_data, f, indent=2)

        print(f"Successfully created new '{BASE_RESUME_PATH}'.")
        return True

    except FileNotFoundError as e:
        print(f"Error: Could not find required file for JSON update: {e.filename}")
        return False
    except Exception as e:
        print(f"An error occurred during the JSON update process: {e}")
        return False

def generate_tailored_content(model, base_resume, job_desc):
    """Sends a prompt to Gemini and gets tailored resume content back."""
    print("Calling Gemini to tailor content for the job...")

    sections_to_tailor = {
        "summary": base_resume["summary"],
        "experience": base_resume["experience"],
        "projects": base_resume["projects"]
    }

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

    Return ONLY the tailored JSON object.
    """

    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().lstrip("```json").rstrip("```").strip()
        return json.loads(cleaned_response)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
        print("--- Gemini's Raw Response ---")
        print(response.text)
        return None

def build_latex_from_data(data):
    """
    Builds the entire LaTeX document from scratch using the provided data.
    This function IS the template now, ensuring reliability.
    """
    
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
        if counter == 0:
            tex_filename = f"{base_name}.tex"
        else:
            tex_filename = f"{base_name}_{counter}.tex"
        if not os.path.exists(tex_filename):
            return tex_filename, tex_filename.replace('.tex', '.pdf')
        counter += 1

def main():
    """Main function to run the resume generation process."""
    print("--- Starting Resume Tailor ---")
    
    model = setup_api()

    # --- Step 1: Archive old JSON and create new one from template ---
    print("\n--- Step 1 of 3: Archiving old data and syncing from template ---")
    archive_old_json()
    if not update_json_from_template(model):
        print("Halting due to error in JSON update step.")
        sys.exit(1)

    # --- Step 2: Tailor content for the job description ---
    print("\n--- Step 2 of 3: Tailoring content for the job ---")
    try:
        with open(BASE_RESUME_PATH, 'r', encoding='utf-8') as f:
            base_resume_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: A new '{BASE_RESUME_PATH}' was not created. Cannot proceed.")
        sys.exit(1)

    with open(JOB_DESCRIPTION_PATH, 'r', encoding='utf-8') as f:
        job_description_text = f.read()

    # Since there's no interactive prompt anymore, we default to tailoring all sections
    tailored_sections = generate_tailored_content(model, base_resume_data, job_description_text)
    if not tailored_sections:
        print("Exiting due to API error.")
        return
        
    print("\nHere is the tailored content from the AI:")
    print(json.dumps(tailored_sections, indent=2))

    final_resume_data = base_resume_data.copy()
    final_resume_data.update(tailored_sections)

    output_latex_file, output_pdf_file = find_unique_filename(BASE_OUTPUT_NAME)

    # --- BLOCK 1: SAVE THE TAILORED JSON ---
    # Create a unique filename for the tailored data JSON that matches the PDF
    base_output_filename = output_latex_file.replace('.tex', '')
    output_json_file = f"{base_output_filename}_tailored_data.json"

    # Save the tailored sections to the new JSON file
    print(f"Saving tailored content to '{output_json_file}'...")
    with open(output_json_file, 'w', encoding='utf-8') as f:
        json.dump(tailored_sections, f, indent=2)
    print(f"Successfully saved tailored data.")
    # --- END OF BLOCK 1 ---
    
    print("\nBuilding final LaTeX document from tailored data...")
    final_latex = build_latex_from_data(final_resume_data)
    
    # output_latex_file, output_pdf_file = find_unique_filename(BASE_OUTPUT_NAME) # Moved up to before saving JSON

    with open(output_latex_file, 'w', encoding='utf-8') as f:
        f.write(final_latex)

    # --- Step 3: Compile the final PDF ---
    print(f"\n--- Step 3 of 3: Compiling PDF and Word Document ---")
    for i in range(2): 
        process = subprocess.run(['pdflatex', '-interaction=nonstopmode', output_latex_file], capture_output=True, text=True, encoding='utf-8')

    if process.returncode == 0:
        print(f"Successfully created {output_pdf_file}")
        
        # --- NEW STEP: Convert the created PDF to a Word Document ---
        docx_file = output_pdf_file.replace('.pdf', '.docx')
        print(f"Converting to {docx_file}...")
        try:
            cv = Converter(output_pdf_file)
            cv.convert(docx_file, start=0, end=None)
            cv.close()
            print(f"Successfully created {docx_file}!")
        except Exception as e:
            print(f"Could not convert PDF to DOCX. Error: {e}")

        # --- CORRECTED ORDER ---
        # 1. Open the resume preview first so you can see it immediately.
        # print("Opening resume preview...")
        # if sys.platform == "win32":
        #     os.startfile(output_pdf_file)
        # else:
        #     opener = "open" if sys.platform == "darwin" else "xdg-open"
        #     subprocess.call([opener, output_pdf_file])

        # 2. Then, proceed to the next step of generating the cover letter.
        # --- BLOCK 2: RUN THE COVER LETTER SCRIPT ---
        print("\nProceeding to cover letter generation...")
        try:
            # Command to execute: python create_cover_letter.py <path_to_json> <path_to_job_desc>
            command = [
                sys.executable,  # Use the same python interpreter
                'create_cover_letter.py',
                output_json_file,
                JOB_DESCRIPTION_PATH
            ]
            
            # Run the command
            subprocess.run(command, check=True)
            print("Cover letter script executed successfully.")

        except FileNotFoundError:
            print("Warning: 'create_cover_letter.py' not found. Skipping cover letter generation.")
        except subprocess.CalledProcessError as e:
            print(f"Error executing cover letter script: {e}")
        # --- END OF BLOCK 2 ---

    else:
        log_file = os.path.basename(output_latex_file).replace('.tex', '.log')
        print(f"Error: PDF compilation failed. Check the '{log_file}' file for details.")

if __name__ == "__main__":
    main()