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

IMPORTANT:
- Infer missing info
- Keep education ordered highest first
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)


# -------- SCORING --------
def get_candidate_score(jd_text, profile):
    prompt = f"""
You are an expert recruiter.

Job Description:
{jd_text}

Candidate Profile:
{profile}

Return ONLY JSON:

{{
  "score": 0-100,
  "strengths": [],
  "gaps": []
}}

RULES:
- 1 to 3 strengths MAX (only if meaningful)
- 1 to 3 gaps MAX (only if real gaps exist)
- Avoid duplication
- Each point ≤ 10 words
- No filler content
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    return safe_json_load(response.content[0].text)

def compute_rule_based_score(jd_text, profile):
    jd_text = jd_text.lower()

    candidate_skills = [s.lower() for s in profile.get("skills", [])]
    experience = profile.get("experience_years", "")

    # ---- SKILL MATCH ----
    matched_skills = sum(1 for skill in candidate_skills if skill in jd_text)
    total_skills = len(candidate_skills) if candidate_skills else 1
    skill_score = (matched_skills / total_skills) * 50

    # ---- EXPERIENCE MATCH ----
    exp_score = 0
    try:
        exp_num = float(experience.split()[0])
        if exp_num >= 5:
            exp_score = 30
        elif exp_num >= 2:
            exp_score = 20
        elif exp_num > 0:
            exp_score = 10
    except:
        exp_score = 0

    # ---- EDUCATION MATCH ----
    education = profile.get("education", [])
    edu_score = 0

    if education:
        edu_text = str(education[0]).lower()
        if any(x in edu_text for x in ["btech", "be", "engineering"]):
            edu_score = 20
        elif any(x in edu_text for x in ["bcom", "bba", "mba"]):
            edu_score = 15

    final_score = int(skill_score + exp_score + edu_score)

    return {
        "score": min(final_score, 100)
    }
# -------- REPORT GENERATION --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):

        name = extract_candidate_name(candidate['file_name'])

        # -------- TITLE --------
        p = doc.add_paragraph()
        run = p.add_run(f"{i}. {name} | Match: {candidate['score']}%")
        run.bold = True

        # -------- FILE NAME --------
        doc.add_paragraph(f"File Name : {candidate['file_name']}")

        # -------- EXPERIENCE + EDUCATION --------
        doc.add_paragraph(
            f"Experience: {candidate['experience']} years | "
            f"Education: {format_education(candidate['education'])}"
        )

        # -------- TABLE --------
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
                rule_score = compute_rule_based_score(jd_text[:2000], profile)
                analysis = get_candidate_score(jd_text[:2000], profile)

                # override LLM score with rule-based score
                analysis["score"] = rule_score["score"]

                results.append({
                    "file_name": file.name,
                    "score": analysis.get("score", 0),
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
