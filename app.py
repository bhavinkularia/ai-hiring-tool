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


# -------- CLAUDE SCORING --------
def get_candidate_score(jd_text, resume_text):
    prompt = f"""
You are an expert HR recruiter.

Job Description:
{jd_text}

Candidate Resume:
{resume_text}

Evaluate the candidate and return:
1. Match Score (0-100)
2. Top 3 strengths
3. Top 3 gaps

Respond ONLY in this format:

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
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    return response.content[0].text


# -------- REPORT GENERATION (FIXED) --------
def generate_report(top_candidates):
    doc = Document()
    doc.add_heading('Top Candidates Report', 0)

    for i, candidate in enumerate(top_candidates, 1):
        doc.add_heading(f"{i}. {candidate['name']} (Score: {candidate['score']})", level=2)
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
    st.subheader("Job Description Extracted")
    st.text(jd_text[:1000])


# -------- RESUME UPLOAD --------
resume_files = st.file_uploader(
    "Upload Resumes (PDF or DOCX)",
    type=["pdf", "docx"],
    accept_multiple_files=True
)

# Preview resumes
if resume_files:
    st.subheader("Resume Preview")

    for file in resume_files:
        st.write(f"### {file.name}")
        resume_text = extract_text(file)
        st.text(resume_text[:500])
        st.divider()


# -------- TOP N SELECTOR --------
top_n = st.slider(
    "Select number of top candidates",
    min_value=1,
    max_value=20,
    value=3
)

# -------- ANALYZE BUTTON --------
analyze_clicked = st.button("🔍 Analyze Candidates")


# -------- AI ANALYSIS + RANKING --------
if analyze_clicked:
    if not jd_text or not resume_files:
        st.warning("⚠️ Please upload both Job Description and Resumes")
    else:
        st.subheader(f"🏆 Top {top_n} Candidates")

        results = []

        for file in resume_files:
            resume_text = extract_text(file)
            resume_text = resume_text[:3000]

            with st.spinner(f"Analyzing {file.name}..."):
                analysis = get_candidate_score(jd_text[:2000], resume_text)

            score = extract_score(analysis)

            results.append({
                "name": file.name,
                "score": score,
                "analysis": analysis
            })

        # Sort candidates
        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)

        # Top N
        top_candidates = sorted_results[:top_n]

        # Display
        for i, candidate in enumerate(top_candidates, 1):
            st.write(f"### {i}. {candidate['name']} (Score: {candidate['score']})")
            st.text(candidate["analysis"])
            st.divider()

        # -------- DOWNLOAD REPORT --------
        report_file = generate_report(top_candidates)

        st.download_button(
            label="📄 Download Report",
            data=report_file,
            file_name="Top_Candidates_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
