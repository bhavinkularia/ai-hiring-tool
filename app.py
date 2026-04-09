import streamlit as st
from docx import Document
import pdfplumber
import anthropic
import os
from io import BytesIO

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


# -------- STEP 1: EDUCATION DETECTION (REASONING) --------
def detect_education(resume_text):
    prompt = f"""
You are an expert recruiter.

Your task is to identify the candidate's education EVEN IF NOT EXPLICITLY WRITTEN.

Resume:
{resume_text}

Instructions:
- Look for indirect signals:
  - email domains (e.g. iimranchi.ac.in → MBA)
  - institute names (IIM → MBA, IIT → Engineer)
  - internships, batch patterns
  - any contextual clues

IMPORTANT RULE:
If candidate is from ANY IIM, assume MBA unless strongly contradicted.

Think step-by-step.

Return ONLY:

Education: <your conclusion>
Confidence: <High/Medium/Low>
Reasoning: <short explanation>
"""

    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


# -------- STEP 2: SCORING --------
def get_candidate_score(jd_text, resume_text, education_info):
    prompt = f"""
You are an expert recruiter.

Job Description:
{jd_text}

Candidate Resume:
{resume_text}

Detected Education:
{education_info}

IMPORTANT:
- TRUST inferred education above missing text
- DO NOT assume "no MBA" if inferred MBA exists

Evaluate candidate.

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

                # STEP 1: Education reasoning
                education_info = detect_education(resume_text)

                # STEP 2: Scoring
                analysis = get_candidate_score(
                    jd_text[:2000],
                    resume_text,
                    education_info
                )

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
