import streamlit as st
from docx import Document
import pdfplumber
import anthropic
import os
from io import BytesIO
import json
import re

# -------- CONFIG --------
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

st.title("AI Hiring Assistant")

# -------- TEXT EXTRACTION --------
def extract_text(file):
    if file.name.endswith(".pdf"):
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
        return text
    else:
        doc = Document(file)
        return "\n".join([para.text for para in doc.paragraphs])


# -------- SAFE JSON PARSER --------
def safe_json_load(text):
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])
    except:
        return {}


# -------- NAME CLEANER --------
def extract_candidate_name(file_name):
    name = file_name.replace(".pdf", "").replace(".docx", "")
    name = name.replace("Resume", "").replace("_", " ").strip()
    return name


# -------- EDUCATION FORMATTER --------
def format_education(education_list):
    if not education_list:
        return "N/A"

    edu = education_list[0]

    if isinstance(edu, dict):
        degree = edu.get("degree", "")
        college = edu.get("institution", "")
        year = edu.get("year", "")
        grade = edu.get("grade", "")

        parts = [degree, college, year]
        base = ", ".join([p for p in parts if p])

        if grade:
            base += f", Grade: {grade}"

        return base

    return str(edu)


# -------- RULE BASED SCORE (NEW) --------
def calculate_rule_score(jd_text, resume_text):
    jd_text = jd_text.lower()
    resume_text = resume_text.lower()

    # Extract keywords from JD (simple but deterministic)
    keywords = ["tally", "gst", "tds", "excel", "accounting", "reconciliation", "invoice"]

    # Experience extraction
    exp_match = re.findall(r'(\d+\.?\d*)\s*(years|year|yrs)', resume_text)
    experience = float(exp_match[0][0]) if exp_match else 0

    score = 0

    # Experience weight (40)
    if experience >= 2:
        score += 40
    elif experience > 0:
        score += int((experience / 2) * 40)

    # Keyword match (60)
    matches = sum(1 for kw in keywords if kw in resume_text)
    score += int((matches / len(keywords)) * 60)

    return min(score, 100)


# -------- PROFILE EXTRACTION --------
def extract_candidate_profile(resume_text):
    prompt = f"""
Extract structured candidate data.

Resume:
{resume_text}

Return ONLY JSON:

{{
  "name": "",
  "education": [],
  "skills": [],
  "experience_years": ""
}}
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


# -------- SCORING (AI ONLY FOR INSIGHTS NOW) --------
def get_candidate_score(jd_text, profile):
    prompt = f"""
You are an expert recruiter.

Job Description:
{jd_text}

Candidate Profile:
{profile}

Return ONLY JSON:

{{
  "strengths": [],
  "gaps": []
}}

RULES:
- 1 to 3 strengths MAX
- 1 to 3 gaps MAX
- Avoid duplication
- Keep concise
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


# -------- REPORT GENERATION --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):

        name = extract_candidate_name(candidate['file_name'])

        p = doc.add_paragraph()
        run = p.add_run(f"{i}. {name} | Match: {candidate['score']}%")
        run.bold = True

        doc.add_paragraph(f"File Name : {candidate['file_name']}")

        doc.add_paragraph(
            f"Experience: {candidate['experience']} years | "
            f"Education: {format_education(candidate['education'])}"
        )

        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'

        table.rows[0].cells[0].text = "Strengths"
        table.rows[0].cells[1].text = "Gaps"

        strengths = candidate.get('strengths', [])
        gaps = candidate.get('gaps', [])

        max_len = max(len(strengths), len(gaps), 1)

        for j in range(max_len):
            row_cells = table.add_row().cells
            row_cells[0].text = strengths[j] if j < len(strengths) else ""
            row_cells[1].text = gaps[j] if j < len(gaps) else ""

        doc.add_paragraph("")

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)

    return buffer


# -------- JD UPLOAD --------
jd_file = st.file_uploader(
    "Upload Job Description (PDF or DOCX)",
    type=["pdf", "docx"]
)

jd_text = ""
if jd_file:
    jd_text = extract_text(jd_file)
    st.success("✅ Job Description uploaded")


# -------- RESUME UPLOAD --------
resume_files = st.file_uploader(
    "Upload Resumes (PDF or DOCX)",
    type=["pdf", "docx"],
    accept_multiple_files=True
)

if resume_files:
    st.success(f"✅ {len(resume_files)} resumes uploaded")


# -------- TOP N SELECTOR --------
top_n = st.slider(
    "Select number of top candidates",
    min_value=1,
    max_value=20,
    value=3
)

# -------- ANALYZE BUTTON --------
analyze_clicked = st.button("🔍 Analyze Candidates")


# -------- PIPELINE --------
if analyze_clicked:
    if not jd_text or not resume_files:
        st.warning("⚠️ Please upload both Job Description and Resumes")
    else:
        with st.spinner("Analyzing candidates..."):
            results = []

            for file in resume_files:
                resume_text = extract_text(file)[:3000]

                profile = extract_candidate_profile(resume_text)

                # AI only for strengths/gaps
                analysis = get_candidate_score(jd_text[:2000], profile)

                # RULE-based score (NEW)
                score = calculate_rule_score(jd_text, resume_text)

                results.append({
                    "file_name": file.name,
                    "score": score,
                    "strengths": analysis.get("strengths", []),
                    "gaps": analysis.get("gaps", []),
                    "experience": profile.get("experience_years", "N/A"),
                    "education": profile.get("education", [])
                })

            sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)

            buffer_n = int(top_n * 2.5)
            top_candidates = sorted_results[:buffer_n]

        st.success("✅ Analysis complete")

        report_file = generate_report(top_candidates)

        st.download_button(
            label="📄 Download Report",
            data=report_file,
            file_name="Top_Candidates_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
