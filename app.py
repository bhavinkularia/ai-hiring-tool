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


# -------- NAME CLEANER --------
def extract_candidate_name(file_name):
    name = file_name.replace(".pdf", "").replace(".docx", "")
    name = name.replace("Resume", "").replace("_", " ").strip()
    return name


# -------- RULE: EXPERIENCE --------
def extract_experience(text):
    matches = re.findall(r'(\d+\.?\d*)\s*(years|year|yrs)', text.lower())
    if matches:
        return max([float(m[0]) for m in matches])
    return 0


# -------- RULE: EDUCATION --------
def extract_education(text):
    degrees = ["m.com", "mba", "b.com", "bba", "b.sc", "m.sc"]
    for d in degrees:
        if d in text.lower():
            return [d.upper()]
    return ["N/A"]


# -------- RULE: JD REQUIREMENTS --------
def extract_jd_rules(jd_text):
    exp_match = re.findall(r'(\d+)\s*[-–]\s*(\d+)\s*years', jd_text.lower())
    if exp_match:
        min_exp = int(exp_match[0][0])
        max_exp = int(exp_match[0][1])
    else:
        min_exp, max_exp = 0, 10

    keywords = ["tally", "gst", "tds", "excel", "accounting"]
    return {
        "min_exp": min_exp,
        "max_exp": max_exp,
        "keywords": keywords
    }


# -------- RULE: MATCH SCORE --------
def calculate_score(profile_text, jd_rules, experience):
    score = 0

    # Experience (40)
    if experience >= jd_rules["min_exp"]:
        score += 40
    else:
        score += int((experience / jd_rules["min_exp"]) * 40) if jd_rules["min_exp"] else 0

    # Keyword match (60)
    matches = 0
    for kw in jd_rules["keywords"]:
        if kw in profile_text.lower():
            matches += 1

    score += int((matches / len(jd_rules["keywords"])) * 60)

    return min(score, 100)


# -------- AI: STRENGTHS + GAPS --------
def get_strengths_gaps(jd_text, resume_text):
    prompt = f"""
You are a hiring manager.

Job Description:
{jd_text}

Resume:
{resume_text}

Give ONLY:

- Strengths (1-3)
- Gaps (1-3)

RULES:
- No generic points
- No repetition
- Keep concise
- Only meaningful insights

Return JSON:

{{
 "strengths": [],
 "gaps": []
}}
"""
    response = client.messages.create(
        model="claude-sonnet-4-0",
        max_tokens=250,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        text = response.content[0].text
        return json.loads(text[text.find("{"):text.rfind("}")+1])
    except:
        return {"strengths": [], "gaps": []}


# -------- EDUCATION FORMAT --------
def format_education(education_list):
    return education_list[0] if education_list else "N/A"


# -------- REPORT --------
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
jd_file = st.file_uploader("Upload Job Description", type=["pdf", "docx"])
resume_files = st.file_uploader("Upload Resumes", type=["pdf", "docx"], accept_multiple_files=True)

top_n = st.slider("Top Candidates", 1, 20, 3)
analyze_clicked = st.button("Analyze")


# -------- PIPELINE --------
if analyze_clicked:
    if not jd_file or not resume_files:
        st.warning("Upload JD and resumes")
    else:
        jd_text = extract_text(jd_file)
        jd_rules = extract_jd_rules(jd_text)

        results = []

        for file in resume_files:
            resume_text = extract_text(file)

            experience = extract_experience(resume_text)
            education = extract_education(resume_text)

            score = calculate_score(resume_text, jd_rules, experience)

            ai_output = get_strengths_gaps(jd_text[:1500], resume_text[:2000])

            results.append({
                "file_name": file.name,
                "score": score,
                "strengths": ai_output.get("strengths", []),
                "gaps": ai_output.get("gaps", []),
                "experience": experience,
                "education": education
            })

        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        top_candidates = sorted_results[:top_n]

        st.success("Analysis complete")

        report = generate_report(top_candidates)

        st.download_button(
            "Download Report",
            report,
            "Top_Candidates_Report.docx"
        )
