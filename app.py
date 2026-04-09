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


# -------- SCORE EXTRACTION --------
def extract_score(text):
    try:
        for line in text.split("\n"):
            if "Score" in line:
                return int(line.split(":")[1].strip())
    except:
        return 0


# -------- SAFE JSON PARSER --------
def safe_json_load(raw_text):
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        json_str = raw_text[start:end]
        return json.loads(json_str)
    except:
        return None


# -------- STEP 1: PROFILE EXTRACTION --------
def extract_candidate_profile(resume_text):
    prompt = f"""
Extract structured candidate data from this resume.

Return ONLY JSON.

Resume:
{resume_text}

Format:
{{
  "education": [],
  "current_status": "",
  "skills": [],
  "experience_years": "",
  "domain": "",
  "inferences": []
}}

IMPORTANT:
- Infer missing info using context (email, institute, etc.)
- Do NOT return anything except JSON
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw_output = response.content[0].text
    parsed = safe_json_load(raw_output)

    if parsed:
        return parsed
    else:
        return {"fallback": resume_text}


# -------- STEP 2: SCORING --------
def get_candidate_score(jd_text, data):
    prompt = f"""
You are an expert recruiter.

Job Description:
{jd_text}

Candidate Data:
{data}

Evaluate the candidate.

IMPORTANT:
- If structured data is weak, infer from available info
- NEVER say "no candidate info"

Return ONLY:

Score: <number>

Strengths:
- ...
- ...
- ...

Gaps:
- ...
- ...
- ...
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


# -------- REPORT GENERATION --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):
        doc.add_heading(
            f"{i}. {candidate['name']} (Score: {candidate['score']})",
            level=2
        )
        doc.add_paragraph(candidate["analysis"])

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


# -------- AI PIPELINE --------
if analyze_clicked:
    if not jd_text or not resume_files:
        st.warning("⚠️ Please upload both Job Description and Resumes")
    else:
        with st.spinner("Analyzing candidates..."):
            results = []

            for file in resume_files:
                resume_text = extract_text(file)[:3000]

                # STEP 1: Extract profile (safe)
                profile = extract_candidate_profile(resume_text)

                # STEP 2: Score (with fallback)
                analysis = get_candidate_score(jd_text[:2000], profile)
                score = extract_score(analysis)

                results.append({
                    "name": file.name,
                    "score": score,
                    "analysis": analysis
                })

            # Sort + select top N
            sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
            top_candidates = sorted_results[:top_n]

        st.success("✅ Analysis complete")

        # -------- DOWNLOAD ONLY --------
        report_file = generate_report(top_candidates)

        st.download_button(
            label="📄 Download Report",
            data=report_file,
            file_name="Top_Candidates_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
