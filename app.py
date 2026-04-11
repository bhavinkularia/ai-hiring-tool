import streamlit as st
from docx import Document
import pdfplumber
import anthropic
import os
from io import BytesIO
import json

# -------- CONFIG --------
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

st.title("AI Screener Assistant")

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
    return str(education_list[0])


# -------- JD SUMMARY (LOW TOKEN, HIGH IMPACT) --------
def extract_jd_summary(jd_text):
    prompt = f"""
Summarize JD into hiring signals.

Return JSON:

{{
  "core_requirements": [],
  "tools": [],
  "compliance": [],
  "experience_range": ""
}}

Max 5 items each. Keep concise.

JD:
{jd_text}
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=200,
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
  "education": [],
  "skills": [],
  "experience_years": ""
}}

Keep it concise.
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


# -------- SMART SCORING --------
def get_candidate_score(jd_summary, profile):
    prompt = f"""
You are a hiring manager selecting the best candidate.

Job Requirements:
{jd_summary}

Candidate:
{profile}

Evaluate in 3 steps:

1. Fit Check (meets requirement or not)
2. Strength Analysis (what stands out)
3. Gap Analysis (ONLY meaningful gaps)

IMPORTANT:
- Avoid generic gaps
- Do NOT repeat same gaps for all candidates
- If requirement is met → do NOT call it a gap
- Prefer relative insights (e.g., "limited depth", "basic exposure")
- Think like you must choose ONE best candidate

Return JSON:

{{
  "score": 0-100,
  "strengths": [],
  "gaps": []
}}
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


# -------- REPORT --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):

        name = extract_candidate_name(candidate['file_name'])

        # Title
        p = doc.add_paragraph()
        run = p.add_run(f"{i}. {name} | Match: {candidate['score']}%")
        run.bold = True

        # File name
        doc.add_paragraph(f"File Name : {candidate['file_name']}")

        # Info
        doc.add_paragraph(
            f"Experience: {candidate['experience']} years | "
            f"Education: {format_education(candidate['education'])}"
        )

        # Table
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'

        table.rows[0].cells[0].text = "Strengths"
        table.rows[0].cells[1].text = "Gaps"

        strengths = candidate.get("strengths", [])
        gaps = candidate.get("gaps", [])

        max_len = max(len(strengths), len(gaps), 1)

        for j in range(max_len):
            row = table.add_row().cells
            row[0].text = strengths[j] if j < len(strengths) else ""
            row[1].text = gaps[j] if j < len(gaps) else ""

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
        with st.spinner("Analyzing..."):

            jd_text = extract_text(jd_file)
            jd_summary = extract_jd_summary(jd_text)

            results = []

            for file in resume_files:
                resume_text = extract_text(file)[:2500]

                profile = extract_candidate_profile(resume_text)
                analysis = get_candidate_score(jd_summary, profile)

                results.append({
                    "file_name": file.name,
                    "score": analysis.get("score", 0),
                    "strengths": analysis.get("strengths", []),
                    "gaps": analysis.get("gaps", []),
                    "experience": profile.get("experience_years", "N/A"),
                    "education": profile.get("education", [])
                })

            # Stable ranking (no LLM failure)
            sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)

            top_candidates = sorted_results[:top_n]

        st.success("Analysis complete")

        report = generate_report(top_candidates)

        st.download_button(
            "Download Report",
            report,
            "Top_Candidates_Report.docx"
        )
