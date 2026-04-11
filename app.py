import streamlit as st
from docx import Document
import pdfplumber
import anthropic
import os
from io import BytesIO
import json
from docx.shared import Pt
from docx.enum.text import WD_COLOR_INDEX

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


# -------- SAFE JSON --------
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


# -------- EDUCATION FORMAT --------
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


# -------- JD STRUCTURING --------
def extract_jd_requirements(jd_text):
    prompt = f"""
Extract structured hiring requirements.

Return ONLY JSON:

{{
  "experience_required": "",
  "skills_required": [],
  "tools_required": [],
  "compliance_required": [],
  "soft_skills": []
}}

JD:
{jd_text}
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


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


# -------- RULE ENGINE --------
def evaluate_experience_rule(jd_structured, profile):
    jd_range = jd_structured.get("experience_required", "")

    try:
        # Basic parsing
        numbers = [int(s) for s in jd_range.split() if s.isdigit()]
        if len(numbers) >= 2:
            min_exp, max_exp = numbers[0], numbers[1]
        else:
            return "UNKNOWN"

        candidate_exp = float(profile.get("experience_years", 0))

        if candidate_exp < min_exp:
            return "BELOW"
        elif min_exp <= candidate_exp <= max_exp:
            return "MEETS"
        else:
            return "EXCEEDS"

    except:
        return "UNKNOWN"


# -------- SCORING --------
def get_candidate_score(jd_structured, profile, exp_status):
    prompt = f"""
You are a senior hiring manager.

Job Requirements:
{jd_structured}

Candidate Profile:
{profile}

Experience Status (FACT):
{exp_status}

EVALUATION LOGIC:

1. Absolute Fit (vs JD)
- DO NOT mark as gap if requirement is met

2. Relative Strength
- Compare strength level vs typical candidates

RULES:
- If MEETS → say "meets requirement but limited depth"
- If EXCEEDS → treat as strength
- If BELOW → mark as gap
- Avoid generic repetition
- 1–3 strengths, 1–3 gaps max
- Each point ≤ 10 words

Return ONLY JSON:

{{
  "score": 0-100,
  "strengths": [],
  "gaps": []
}}
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


# -------- REPORT --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):

        name = extract_candidate_name(candidate['file_name'])

        # TITLE
        p = doc.add_paragraph()
        run1 = p.add_run(f"{i}. {name} | ")
        run1.bold = True
        run1.font.size = Pt(14)

        run2 = p.add_run(f"Match: {candidate['score']}%")
        run2.bold = True
        run2.font.size = Pt(14)
        run2.font.highlight_color = WD_COLOR_INDEX.YELLOW

        # FILE NAME
        doc.add_paragraph(f"File Name : {candidate['file_name']}")

        # INFO
        doc.add_paragraph(
            f"Experience: {candidate['experience']} years | "
            f"Education: {format_education(candidate['education'])}"
        )

        # TABLE
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'

        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = "Strengths"
        hdr_cells[1].text = "Gaps"

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


# -------- UI --------
jd_file = st.file_uploader("Upload JD", type=["pdf", "docx"])
resume_files = st.file_uploader("Upload Resumes", type=["pdf", "docx"], accept_multiple_files=True)
top_n = st.slider("Top Candidates", 1, 20, 3)
analyze_clicked = st.button("Analyze")

# -------- PIPELINE --------
if analyze_clicked:
    if not jd_file or not resume_files:
        st.warning("Upload JD and resumes")
    else:
        jd_text = extract_text(jd_file)
        jd_structured = extract_jd_requirements(jd_text)

        results = []

        for file in resume_files:
            resume_text = extract_text(file)[:3000]

            profile = extract_candidate_profile(resume_text)

            exp_status = evaluate_experience_rule(jd_structured, profile)

            analysis = get_candidate_score(jd_structured, profile, exp_status)

            results.append({
                "file_name": file.name,
                "score": analysis.get("score", 0),
                "strengths": analysis.get("strengths", []),
                "gaps": analysis.get("gaps", []),
                "experience": profile.get("experience_years", "N/A"),
                "education": profile.get("education", [])
            })

        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        top_candidates = sorted_results[:int(top_n * 2.5)]

        report = generate_report(top_candidates)

        st.download_button(
            "Download Report",
            data=report,
            file_name="Top_Candidates_Report.docx"
        )
