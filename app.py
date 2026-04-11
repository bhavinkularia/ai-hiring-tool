import streamlit as st
from docx import Document
import pdfplumber
import anthropic
import os
from io import BytesIO
import json
from docx.shared import Pt
from docx.enum.text import WD_COLOR_INDEX

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

st.title("AI Hiring Assistant - V3")

# ---------- UTIL ----------
def extract_text(file):
    if file.name.endswith(".pdf"):
        text = ""
        with pdfplumber.open(file) as pdf:
            for p in pdf.pages:
                text += p.extract_text() or ""
        return text
    else:
        doc = Document(file)
        return "\n".join(p.text for p in doc.paragraphs)

def safe_json_load(text):
    try:
        return json.loads(text[text.find("{"):text.rfind("}")+1])
    except:
        return {}

def extract_name(file_name):
    return file_name.replace(".pdf","").replace(".docx","").replace("Resume","").replace("_"," ").strip()

# ---------- JD ----------
def extract_jd(jd_text):
    prompt = f"""
Extract structured hiring requirements.

Return JSON:
{{
 "experience_min": number,
 "experience_max": number,
 "skills": [],
 "tools": [],
 "compliance": []
}}

JD:
{jd_text}
"""
    res = client.messages.create(model="claude-sonnet-4-0", max_tokens=400,
        messages=[{"role":"user","content":prompt}])
    return safe_json_load(res.content[0].text)

# ---------- PROFILE ----------
def extract_profile(text):
    prompt = f"""
Extract candidate profile.

Return JSON:
{{
 "education": [],
 "experience_years": number,
 "skills": []
}}
{text}
"""
    res = client.messages.create(model="claude-sonnet-4-0", max_tokens=400,
        messages=[{"role":"user","content":prompt}])
    return safe_json_load(res.content[0].text)

# ---------- RULE ----------
def exp_rule(jd, profile):
    try:
        e = float(profile.get("experience_years",0))
        if e < jd["experience_min"]:
            return "BELOW"
        elif e <= jd["experience_max"]:
            return "MEETS"
        else:
            return "EXCEEDS"
    except:
        return "UNKNOWN"

# ---------- EVALUATION ----------
def evaluate(jd, profile, exp_status):
    prompt = f"""
You are a hiring manager.

JD:
{jd}

Candidate:
{profile}

Experience Status: {exp_status} (FACT)

Rules:
- DO NOT contradict experience status
- Evaluate across: experience, tools, compliance, role fit
- Avoid generic gaps
- Keep 1-3 strengths, 1-3 gaps

Return JSON:
{{
 "score": number,
 "strengths": [],
 "gaps": []
}}
"""
    res = client.messages.create(model="claude-sonnet-4-0", max_tokens=500,
        messages=[{"role":"user","content":prompt}])
    return safe_json_load(res.content[0].text)

# ---------- COMPARISON ----------
def compare_all(candidates):
    prompt = f"""
You are a hiring decision expert.

Candidates:
{candidates}

Tasks:
1. Rank candidates (NO SAME SCORE)
2. Adjust scores relatively
3. Make strengths UNIQUE
4. Make gaps DIFFERENT (no repetition)
5. Add verdict: Hire / Consider / Reject

Return JSON list:
[
 {{
  "file_name":"",
  "score":0,
  "strengths":[],
  "gaps":[],
  "verdict":""
 }}
]
"""
    res = client.messages.create(model="claude-sonnet-4-0", max_tokens=800,
        messages=[{"role":"user","content":prompt}])
    return safe_json_load(res.content[0].text)

# ---------- REPORT ----------
def generate_report(candidates):
    doc = Document()
    doc.add_heading("Top Candidates Report",0)

    for i,c in enumerate(candidates,1):
        name = extract_name(c["file_name"])

        p = doc.add_paragraph()
        r1 = p.add_run(f"{i}. {name} | ")
        r1.bold = True
        r1.font.size = Pt(14)

        r2 = p.add_run(f"Match: {c['score']}%")
        r2.bold = True
        r2.font.size = Pt(14)
        r2.font.highlight_color = WD_COLOR_INDEX.YELLOW

        doc.add_paragraph(f"File Name : {c['file_name']}")
        doc.add_paragraph(f"Verdict: {c['verdict']}")

        table = doc.add_table(rows=1, cols=2)
        table.rows[0].cells[0].text = "Strengths"
        table.rows[0].cells[1].text = "Gaps"

        max_len = max(len(c["strengths"]), len(c["gaps"]),1)

        for j in range(max_len):
            row = table.add_row().cells
            row[0].text = c["strengths"][j] if j < len(c["strengths"]) else ""
            row[1].text = c["gaps"][j] if j < len(c["gaps"]) else ""

        doc.add_paragraph("")

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ---------- UI ----------
jd_file = st.file_uploader("Upload JD")
resumes = st.file_uploader("Upload Resumes", accept_multiple_files=True)

if st.button("Analyze"):
    jd_text = extract_text(jd_file)
    jd = extract_jd(jd_text)

    results = []

    for f in resumes:
        text = extract_text(f)
        profile = extract_profile(text)
        exp_status = exp_rule(jd, profile)
        analysis = evaluate(jd, profile, exp_status)

        results.append({
            "file_name": f.name,
            "score": analysis.get("score",50),
            "strengths": analysis.get("strengths",[]),
            "gaps": analysis.get("gaps",[])
        })

    final = compare_all(results)

    report = generate_report(final)

    st.download_button("Download Report", report, "Final_Report.docx")
