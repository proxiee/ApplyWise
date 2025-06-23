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
# This is the corrected, robust path
BASE_LETTER_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "cover_letter.tex")

def setup_api():
    """Configures the Gemini API and handles missing API key."""
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not found in .env file.")
        sys.exit(1)
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        return genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")
        sys.exit(1)

def generate_tailored_cover_letter_latex(model, base_letter_content, full_resume_data, job_desc):
    """Generates a tailored LaTeX cover letter by calling the Gemini API."""
    print("Calling Gemini to rewrite the LaTeX cover letter...")

    tailored_resume_context = {
        "summary": full_resume_data.get("summary"),
        "experience": full_resume_data.get("experience"),
        "projects": full_resume_data.get("projects")
    }

    prompt = f"""
    You are an expert career advisor and LaTeX document editor. Your task is to take a base LaTeX cover letter template, a JSON object of tailored resume data, and a job description, and generate a new, complete, tailored LaTeX file as your output.

    **Key Instructions:**
    1.  **Analyze all inputs:** Read the base LaTeX template, the tailored resume data, and the job description.
    2.  **Use My Info:** The user's name is '{full_resume_data.get("name")}' and their email is '{full_resume_data.get("email")}'. Ensure these are correctly placed in the header of the LaTeX file if placeholders exist.
    3.  **Update Date:** Replace the '{{{{TODAYS_DATE}}}}' placeholder with today's date: {datetime.now().strftime('%B %d, %Y')}.
    4.  **Update Recipient:** In the template, find recipient placeholders and replace them with information from the job description. If no specific person is named, use "Hiring Manager".
    5.  **Completely Rewrite the Body:** Discard the original body text. Write a new, compelling body that is perfectly tailored for the job. **Crucially, you MUST integrate the key achievements from the provided "TAILORED RESUME CONTEXT" (from the 'projects' and 'experience' sections) as evidence of the user's skills.**
    6.  **Output a Complete LaTeX File:** Your response MUST be ONLY the full, final, and valid LaTeX code for the cover letter, ready for compilation. Do not include comments or markdown.

    ---
    **1. BASE LATEX COVER LETTER TEMPLATE:**
    ```latex
    {base_letter_content}
    ```
    ---
    **2. TAILORED RESUME CONTEXT (for achievements):**
    ```json
    {json.dumps(tailored_resume_context, indent=2)}
    ```
    ---
    **3. TARGET JOB DESCRIPTION (for keywords and company info):**
    ```
    {job_desc}
    ```
    ---
    Generate the complete and tailored LaTeX source code now."""

    try:
        response = model.generate_content(prompt)
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
    # --- THIS IS THE FIX: Add the --user-id argument ---
    parser.add_argument("--user-id", type=int, required=True, help="ID of the user to generate the cover letter for.")
    args = parser.parse_args()

    print(f"--- Starting Cover Letter Generator for User ID: {args.user_id} ---")

    try:
        with open(args.resume_data_path, 'r', encoding='utf-8') as f:
            full_tailored_resume_data = json.load(f)
        with open(args.job_description_path, 'r', encoding='utf-8') as f:
            job_description = f.read()
        with open(BASE_LETTER_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            base_cover_letter_content = f.read()
    except FileNotFoundError as e:
        print(f"Error: Could not find required file: {e.filename}")
        sys.exit(1)

    model = setup_api()
    final_latex_content = generate_tailored_cover_letter_latex(model, base_cover_letter_content, full_tailored_resume_data, job_description)

    if not final_latex_content:
        print("Halting due to error in AI generation step.")
        sys.exit(1)
        
    print("AI has generated the tailored LaTeX content.")

    base_output_name = os.path.basename(args.resume_data_path).replace('_tailored_data.json', '_cover_letter')
    latex_filename = f"{base_output_name}.tex"
    pdf_filename = f"{base_output_name}.pdf"
    
    with open(latex_filename, 'w', encoding='utf-8') as f:
        f.write(final_latex_content)
    print(f"Successfully created tailored LaTeX file: {latex_filename}")

    print("Compiling PDF from LaTeX...")
    for i in range(2): 
        process = subprocess.run(
            ['pdflatex', '-interaction=nonstopmode', latex_filename],
            capture_output=True, text=True, encoding='utf-8'
        )

    if process.returncode == 0:
        print(f"Successfully created PDF version: {pdf_filename}")
    else:
        log_file = f"{base_output_name}.log"
        print(f"Error: PDF compilation failed. Check '{log_file}' for details.")


if __name__ == "__main__":
    main()