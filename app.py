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
        return None


# -------- SCORE EXTRACTION --------
def extract_score(text):
    try:
        for line in text.split("\n"):
            if "Score" in line:
                return int(line.split(":")[1].replace("%", "").strip())
    except:
        return 0


# -------- STEP 1: PROFILE EXTRACTION --------
def extract_candidate_profile(resume_text):
    prompt = f"""
Extract structured candidate data.

Resume:
{resume_text}

Return ONLY JSON:

{{
  "education": [],
  "skills": [],
  "experience_years": "",
  "confidence": "High/Medium/Low"
}}

IMPORTANT:
- Infer missing info if possible
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    parsed = safe_json_load(response.content[0].text)

    if parsed:
        return parsed, False  # no issue
    else:
        return {"raw": resume_text}, True  # parsing issue


# -------- STEP 2: SCORING --------
def get_candidate_score(jd_text, profile):
    prompt = f"""
You are an expert recruiter.

Job Description:
{jd_text}

Candidate Profile:
{profile}

Evaluate how well candidate matches JD.

Return ONLY:

Score: <percentage between 0-100>

Confidence: <High/Medium/Low>

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


# -------- REVIEW FLAG --------
def get_review_flag(profile_issue, analysis_text):
    if profile_issue:
        return "YES (Parsing Issue)"

    if "Confidence: Low" in analysis_text:
        return "YES (Low Confidence)"

    if "not enough information" in analysis_text.lower():
        return "YES (Incomplete Data)"

    return "NO"


# -------- REPORT GENERATION --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):
        doc.add_heading(
            f"{i}. {candidate['name']} | Match: {candidate['score']}% | Review: {candidate['review']}",
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

                # Step 1
                profile, profile_issue = extract_candidate_profile(resume_text)

                # Step 2
                analysis = get_candidate_score(jd_text[:2000], profile)

                score = extract_score(analysis)

                # Step 3: Review flag
                review_flag = get_review_flag(profile_issue, analysis)

                results.append({
                    "name": file.name,
                    "score": score,
                    "analysis": analysis,
                    "review": review_flag
                })

            # Sort
            sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)

            # Buffer shortlist (VERY IMPORTANT)
            buffer = int(top_n * 2.5)
            top_candidates = sorted_results[:buffer]

        st.success("✅ Analysis complete")

        # -------- DOWNLOAD --------
        report_file = generate_report(top_candidates)

        st.download_button(
            label="📄 Download Report",
            data=report_file,
            file_name="Top_Candidates_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
