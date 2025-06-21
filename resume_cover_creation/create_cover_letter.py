import google.generativeai as genai
import json
import os
import sys
import subprocess
from dotenv import load_dotenv
from datetime import datetime

# --- CONFIGURATION ---
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Use the .tex file as the base template
BASE_LETTER_TEMPLATE_PATH = "cover_letter.tex"

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

def generate_tailored_cover_letter_latex(model, base_letter_content, resume_data, job_desc):
    """Sends a prompt to Gemini to tailor the cover letter and return full LaTeX."""
    print("Calling Gemini to rewrite the LaTeX cover letter...")

    prompt = f"""
    You are an expert career advisor and LaTeX document editor. Your task is to take a base LaTeX cover letter template, a tailored resume, and a job description, and generate a new, complete, tailored LaTeX file as your output.

    **Key Instructions:**
    1.  **Analyze all inputs:** Read the base LaTeX template, the tailored resume data (for achievements), and the job description (for company info, keywords, and tone).
    2.  **Replace Header Information:**
        * In the LaTeX template, find the recipient's details (name, company, location) and replace them with the correct information from the job description. If no specific person is named, use "Hiring Manager".
        
    3.  **Completely Rewrite the Body:**
        * Add the percentage sign (%) where ever necessary for as seen in the resume.
        * Each paragraph should be grammatically correct and well-structured (Include full-stops at the end and make sure to be gramatically correct).
        * Do not sepcify where the job is posted.
        * Locate the body of the letter (the text between the greeting and the closing).
        * Discard the original body text.
        * Write a new, compelling body that is perfectly tailored for the job.
        * **Crucially, you MUST integrate the key achievements from the provided "TAILORED RESUME DATA" (especially from the 'projects' and 'experience' sections) as evidence of your skills.** This creates a cohesive application.
        * The new body must be of a similar length to the original to ensure the cover letter remains a single page.
    4.  **Output a Complete LaTeX File:** Your response MUST be ONLY the full, final, and valid LaTeX code for the cover letter, ready for compilation. Do not include any other text, comments, or explanations, and do not wrap it in markdown backticks.

    ---
    **1. BASE LATEX COVER LETTER TEMPLATE:**
    ```latex
    {base_letter_content}
    ```
    ---
    **2. TAILORED RESUME DATA (for context and achievements):**
    ```json
    {json.dumps(resume_data, indent=2)}
    ```
    ---
    **3. TARGET JOB DESCRIPTION (for keywords and company info):**
    ```
    {job_desc}
    ```
    ---

    Now, generate the complete and tailored LaTeX source code.
    """

    try:
        response = model.generate_content(prompt)
        # The response should be the raw LaTeX code
        return response.text.strip()
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        print("--- Gemini's Raw Response ---")
        # Check if response object exists before trying to access .text
        if 'response' in locals() and hasattr(response, 'text'):
            print(response.text)
        return None

def main():
    """Main function to run the cover letter generation process."""
    print("--- Starting Cover Letter Generator (LaTeX Mode) ---")
    if len(sys.argv) != 3:
        print("Usage: python create_cover_letter.py <path_to_resume_data.json> <path_to_job_description.txt>")
        sys.exit(1)

    resume_data_path = sys.argv[1]
    job_desc_path = sys.argv[2]
    
    # --- Step 1: Load all necessary data ---
    print("Loading source files...")
    try:
        with open(resume_data_path, 'r', encoding='utf-8') as f:
            resume_data = json.load(f)
        with open(job_desc_path, 'r', encoding='utf-8') as f:
            job_description = f.read()
        with open(BASE_LETTER_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            base_cover_letter_content = f.read()
    except FileNotFoundError as e:
        print(f"Error: Could not find required file: {e.filename}")
        sys.exit(1)

     # --- ADD THIS BLOCK TO HANDLE THE DATE REPLACEMENT ---
    # Get today's date in the correct format
    todays_date = datetime.now().strftime('%B %d, %Y')
    # Replace the placeholder in the template with today's date
    base_cover_letter_content = base_cover_letter_content.replace('{{TODAYS_DATE}}', todays_date)
    print(f"Set cover letter date to: {todays_date}")
    # --- END OF BLOCK ---

    model = setup_api()

    # --- Step 2: Generate the tailored cover letter LaTeX content ---
    final_latex_content = generate_tailored_cover_letter_latex(model, base_cover_letter_content, resume_data, job_description)

    if not final_latex_content:
        print("Halting due to error in AI generation step.")
        sys.exit(1)
        
    print("\nAI has generated the tailored LaTeX content.")

    # --- Step 3: Save and compile the final PDF ---
    base_output_name = os.path.basename(resume_data_path).replace('_tailored_data.json', '_cover_letter')
    
    latex_filename = f"{base_output_name}.tex"
    pdf_filename = f"{base_output_name}.pdf"
    
    with open(latex_filename, 'w', encoding='utf-8') as f:
        f.write(final_latex_content)
    print(f"Successfully created tailored LaTeX file: {latex_filename}")

    print("Compiling PDF from LaTeX...")
    # Run twice to ensure all references are correct
    for i in range(2): 
        process = subprocess.run(['pdflatex', '-interaction=nonstopmode', latex_filename], capture_output=True, text=True, encoding='utf-8')

    if process.returncode == 0:
        print(f"Successfully created PDF version: {pdf_filename}")

         # --- ADD THIS BLOCK TO OPEN THE PDF PREVIEW ---
        # print("Opening preview...")
        # try:
        #     if sys.platform == "win32":
        #         os.startfile(pdf_filename)
        #     else:
        #         opener = "open" if sys.platform == "darwin" else "xdg-open"
        #         subprocess.run([opener, pdf_filename], check=True)
        # except Exception as e:
        #     print(f"Could not open PDF preview. Please open '{pdf_filename}' manually. Error: {e}")
        # --- END OF BLOCK ---

        # Clean up auxiliary files
        for ext in ['.aux', '.log']:
            try:
                os.remove(base_output_name + ext)
            except OSError:
                pass
    else:
        log_file = f"{base_output_name}.log"
        print(f"Error: PDF compilation failed. Check '{log_file}' for details.")
        print("--- Compiler Output ---")
        print(process.stdout)
        print(process.stderr)


if __name__ == "__main__":
    main()
