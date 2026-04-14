import streamlit as st
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import pdfplumber
import re
import json
from io import BytesIO
from collections import OrderedDict

# ================================================================
#  CONFIG
# ================================================================

WEIGHTS = {"skills": 0.40, "experience": 0.40, "education": 0.20}

EDUCATION_RANK = {
    "phd": 5, "ph.d": 5, "doctorate": 5, "doctoral": 5,
    "master": 4, "mba": 4, "m.sc": 4, "msc": 4, "m.tech": 4, "mtech": 4,
    "m.e": 4, "me ": 4, "m.s": 4, "pg diploma": 4, "post graduate": 4,
    "postgraduate": 4,
    "bachelor": 3, "b.sc": 3, "bsc": 3, "b.tech": 3, "btech": 3,
    "b.e": 3, "be ": 3, "b.a": 3, "ba ": 3, "b.com": 3, "bcom": 3,
    "b.ca": 3, "bca": 3, "undergraduate": 3,
    "diploma": 2, "polytechnic": 2,
    "12th": 1, "hsc": 1, "intermediate": 1,
    "10th": 0, "ssc": 0, "matriculation": 0,
}

EDUCATION_LABEL = {
    5: "PhD / Doctorate",
    4: "Master's / PG Diploma",
    3: "Bachelor's Degree",
    2: "Diploma",
    1: "12th / HSC",
    0: "10th / SSC",
}

STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could", "this",
    "that", "these", "those", "it", "its", "we", "you", "they", "he",
    "she", "our", "your", "their", "as", "if", "so", "not", "no", "nor",
    "such", "than", "then", "when", "where", "who", "which", "how",
    "about", "above", "after", "also", "any", "both", "each", "few",
    "more", "most", "other", "same", "some", "up", "into", "through",
    "during", "including", "while", "per", "between", "etc", "well",
    "good", "strong", "excellent", "ability", "experience", "knowledge",
    "skill", "skills", "work", "working", "years", "year", "month",
    "role", "team", "candidate", "position", "job", "company",
}

# Common tech / domain skill tokens to boost extraction quality
SKILL_INDICATORS = {
    "python", "java", "sql", "javascript", "typescript", "react", "node",
    "angular", "vue", "aws", "azure", "gcp", "docker", "kubernetes",
    "machine learning", "deep learning", "nlp", "data science",
    "data analysis", "power bi", "tableau", "excel", "tensorflow",
    "pytorch", "scikit", "pandas", "numpy", "flask", "django", "fastapi",
    "spring", "microservices", "rest", "api", "git", "linux", "agile",
    "scrum", "devops", "ci/cd", "spark", "hadoop", "airflow", "kafka",
    "selenium", "jira", "confluence", "figma", "photoshop", "illustrator",
    "sap", "salesforce", "erp", "crm", "html", "css", "c++", "c#",
    "ruby", "go", "rust", "swift", "kotlin", "php", "matlab", "r ",
    "communication", "leadership", "management", "presentation",
    "negotiation", "problem solving", "analytical", "critical thinking",
    "project management", "stakeholder", "cross-functional",
}


# ================================================================
#  TEXT EXTRACTION
# ================================================================

def extract_text(file) -> str:
    if file.name.lower().endswith(".pdf"):
        text = ""
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        return text
    else:
        doc = Document(file)
        return "\n".join(p.text for p in doc.paragraphs)


# ================================================================
#  NAME EXTRACTION
# ================================================================

def extract_name(text: str, file_name: str) -> str:
    """
    Tries to extract name from the top lines of the resume.
    Falls back to cleaning the filename.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()][:8]
    for line in lines:
        # A name line: 2-4 words, mostly letters, no digits, not a known header
        words = line.split()
        if (2 <= len(words) <= 4
                and all(re.match(r"^[A-Za-z.'\-]+$", w) for w in words)
                and not any(kw in line.lower() for kw in [
                    "resume", "curriculum", "vitae", "profile", "objective",
                    "summary", "email", "phone", "address", "linkedin"
                ])):
            return line.title()

    # Fallback: clean filename
    name = re.sub(r"\.(pdf|docx)$", "", file_name, flags=re.IGNORECASE)
    name = re.sub(r"[_\-]", " ", name)
    name = re.sub(r"(resume|cv|curriculum|vitae)", "", name, flags=re.IGNORECASE)
    return name.strip().title() or "Unknown"


# ================================================================
#  JD PARSING
# ================================================================

def extract_jd_skills(jd_text: str) -> list[str]:
    """
    Extract skill keywords from the JD.
    Strategy:
      1. Pull multi-word skill phrases from SKILL_INDICATORS found in JD.
      2. Pull meaningful single tokens (length >= 3, not stop words).
    Returns a de-duped ordered list.
    """
    jd_lower = jd_text.lower()
    found = []

    # Multi-word first (order matters: longer phrases before sub-tokens)
    sorted_indicators = sorted(SKILL_INDICATORS, key=len, reverse=True)
    for phrase in sorted_indicators:
        if phrase in jd_lower:
            found.append(phrase.strip())

    # Single-word tokens from JD not already covered
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#./\-]{2,}", jd_lower)
    for tok in tokens:
        tok = tok.strip(".-/")
        if (tok not in STOP_WORDS
                and len(tok) >= 3
                and tok not in found
                and not tok.isdigit()):
            found.append(tok)

    # De-dup preserving order
    seen = set()
    skills = []
    for s in found:
        if s not in seen:
            seen.add(s)
            skills.append(s)

    return skills


def extract_required_experience(jd_text: str) -> float:
    """
    Parses statements like '5+ years', 'minimum 3 years', '2-4 years' from JD.
    Returns the minimum required years as a float.
    """
    patterns = [
        r"(\d+)\s*\+\s*years?",
        r"minimum\s+of\s+(\d+)\s+years?",
        r"minimum\s+(\d+)\s+years?",
        r"at\s+least\s+(\d+)\s+years?",
        r"(\d+)\s*[-–]\s*\d+\s+years?",   # range: take lower bound
        r"(\d+)\s+years?\s+of\s+experience",
        r"experience\s+of\s+(\d+)\s+years?",
        r"(\d+)\s+years?",
    ]
    jd_lower = jd_text.lower()
    for pat in patterns:
        m = re.search(pat, jd_lower)
        if m:
            return float(m.group(1))
    return 3.0   # sensible default when not stated


def extract_required_education(jd_text: str) -> int:
    """
    Returns the EDUCATION_RANK level required by the JD.
    Defaults to Bachelor's (3) if not stated.
    """
    jd_lower = jd_text.lower()
    best = 0
    for keyword, rank in sorted(EDUCATION_RANK.items(), key=lambda x: -x[1]):
        if keyword in jd_lower:
            if rank > best:
                best = rank
    return best if best > 0 else 3


# ================================================================
#  RESUME PARSING
# ================================================================

def extract_candidate_skills(resume_text: str) -> list[str]:
    """Returns all SKILL_INDICATORS tokens found in the resume."""
    resume_lower = resume_text.lower()
    found = []
    seen = set()
    for phrase in sorted(SKILL_INDICATORS, key=len, reverse=True):
        if phrase in resume_lower and phrase not in seen:
            found.append(phrase.strip())
            seen.add(phrase.strip())
    return found


def extract_experience_years(resume_text: str) -> float:
    """
    Extracts total experience from the resume.
    Tries three strategies:
      1. Explicit 'X years of experience' statement.
      2. Count distinct date ranges (YYYY–YYYY or Month YYYY – Month YYYY).
      3. Span from earliest to latest year found.
    """
    text = resume_text.lower()

    # Strategy 1: explicit declaration
    explicit_patterns = [
        r"(\d+\.?\d*)\s*\+?\s*years?\s+of\s+(?:total\s+)?experience",
        r"total\s+experience[:\s]+(\d+\.?\d*)\s*years?",
        r"(\d+\.?\d*)\s*years?\s+(?:total\s+)?(?:work|professional|industry)\s+experience",
        r"experience[:\s]+(\d+\.?\d*)\s*years?",
    ]
    for pat in explicit_patterns:
        m = re.search(pat, text)
        if m:
            return float(m.group(1))

    # Strategy 2: sum date ranges
    # Pattern: YYYY - YYYY  or  YYYY – YYYY  or  YYYY to YYYY
    range_pat = r"((?:19|20)\d{2})\s*[-–to]+\s*((?:19|20)\d{2}|present|current|now|date)"
    current_year = 2025
    total = 0.0
    ranges = re.findall(range_pat, text)
    if ranges:
        for start_s, end_s in ranges:
            start = int(start_s)
            end = current_year if re.match(r"[a-z]", end_s.strip()) else int(end_s)
            if 1970 <= start <= current_year and start <= end:
                total += (end - start)
        if total > 0:
            return min(round(total, 1), 40.0)  # cap sanity

    # Strategy 3: span
    years = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", resume_text)
             if 1970 <= int(y) <= current_year]
    if len(years) >= 2:
        return float(max(years) - min(years))

    return 0.0


def extract_education(resume_text: str) -> tuple[int, str]:
    """
    Returns (rank, label) of the highest education found.
    """
    text = resume_text.lower()
    best_rank = -1
    for keyword, rank in sorted(EDUCATION_RANK.items(), key=lambda x: -x[1]):
        if keyword in text:
            if rank > best_rank:
                best_rank = rank
    if best_rank == -1:
        return (0, "Not Found")
    return (best_rank, EDUCATION_LABEL.get(best_rank, "Other"))


# ================================================================
#  SCORING
# ================================================================

def score_skills(candidate_skills: list[str], jd_skills: list[str]) -> tuple[float, list[str], list[str]]:
    """
    Returns (score_0_to_1, matched_skills, missing_skills).
    Only JD skills that appear in the resume are considered matched.
    """
    if not jd_skills:
        return 1.0, [], []

    # Focus scoring only on JD skills (not all resume skills)
    jd_set = set(jd_skills)
    candidate_set = set(candidate_skills)

    matched = sorted(jd_set & candidate_set)
    missing = sorted(jd_set - candidate_set)

    score = len(matched) / len(jd_set)
    return score, matched, missing


def score_experience(candidate_years: float, required_years: float) -> float:
    if required_years <= 0:
        return 1.0
    return min(candidate_years / required_years, 1.0)


def score_education(candidate_rank: int, required_rank: int) -> float:
    if required_rank <= 0:
        return 1.0
    if candidate_rank >= required_rank:
        return 1.0
    # Partial credit: one level below = 0.6, two levels = 0.3, more = 0
    diff = required_rank - candidate_rank
    if diff == 1:
        return 0.6
    elif diff == 2:
        return 0.3
    return 0.0


def build_strengths_gaps(
    matched_skills: list[str],
    missing_skills: list[str],
    candidate_years: float,
    required_years: float,
    candidate_edu_rank: int,
    required_edu_rank: int,
    candidate_edu_label: str,
) -> tuple[list[str], list[str]]:
    """
    Builds at most 3 unique strengths and 3 unique gaps.
    """
    strengths = []
    gaps = []

    # ---- SKILLS ----
    if matched_skills:
        top = matched_skills[:4]
        strengths.append(f"Matches key skills: {', '.join(top)}")
    if missing_skills:
        top_m = missing_skills[:4]
        gaps.append(f"Missing JD skills: {', '.join(top_m)}")

    # ---- EXPERIENCE ----
    if required_years > 0:
        if candidate_years >= required_years * 1.25:
            strengths.append(
                f"Exceeds experience requirement ({candidate_years:.1f} yrs vs {required_years:.0f} required)"
            )
        elif candidate_years >= required_years:
            strengths.append(
                f"Meets experience requirement ({candidate_years:.1f} yrs)"
            )
        else:
            gaps.append(
                f"Below required experience ({candidate_years:.1f} yrs vs {required_years:.0f} needed)"
            )

    # ---- EDUCATION ----
    if candidate_edu_rank > required_edu_rank:
        strengths.append(f"Education exceeds requirement ({candidate_edu_label})")
    elif candidate_edu_rank == required_edu_rank:
        strengths.append(f"Education meets requirement ({candidate_edu_label})")
    elif candidate_edu_rank < required_edu_rank:
        req_label = EDUCATION_LABEL.get(required_edu_rank, "required level")
        gaps.append(f"Education below requirement (has {candidate_edu_label}, needs {req_label})")

    # Deduplicate and cap at 3 each
    seen_s, seen_g = set(), set()
    final_s, final_g = [], []
    for s in strengths:
        key = s.lower()
        if key not in seen_s and len(final_s) < 3:
            seen_s.add(key)
            final_s.append(s)
    for g in gaps:
        key = g.lower()
        if key not in seen_g and len(final_g) < 3:
            seen_g.add(key)
            final_g.append(g)

    return final_s, final_g


# ================================================================
#  FULL CANDIDATE ANALYSIS
# ================================================================

def analyze_candidate(resume_text: str, file_name: str, jd_skills: list[str],
                       required_years: float, required_edu_rank: int) -> dict:
    name = extract_name(resume_text, file_name)
    candidate_skills = extract_candidate_skills(resume_text)
    candidate_years = extract_experience_years(resume_text)
    candidate_edu_rank, candidate_edu_label = extract_education(resume_text)

    skill_score, matched, missing = score_skills(candidate_skills, jd_skills)
    exp_score = score_experience(candidate_years, required_years)
    edu_score = score_education(candidate_edu_rank, required_edu_rank)

    final_score = round(
        (skill_score * WEIGHTS["skills"]
         + exp_score * WEIGHTS["experience"]
         + edu_score * WEIGHTS["education"]) * 100
    )

    strengths, gaps = build_strengths_gaps(
        matched, missing,
        candidate_years, required_years,
        candidate_edu_rank, required_edu_rank,
        candidate_edu_label,
    )

    return {
        "file_name": file_name,
        "name": name,
        "score": final_score,
        "experience_years": candidate_years,
        "education_label": candidate_edu_label,
        "education_rank": candidate_edu_rank,
        "strengths": strengths,
        "gaps": gaps,
        "matched_skills": matched,
        "missing_skills": missing,
    }


# ================================================================
#  REPORT GENERATION
# ================================================================

def generate_report(top_candidates: list[dict], required_years: float,
                    required_edu_rank: int) -> BytesIO:
    doc = Document()

    # Title
    title = doc.add_heading("Top Candidates Report", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Summary line
    req_edu_label = EDUCATION_LABEL.get(required_edu_rank, "Not specified")
    doc.add_paragraph(
        f"Scoring weights — Skills: 40% | Experience: 40% | Education: 20%   |   "
        f"Required experience: {required_years:.0f} yrs   |   "
        f"Required education: {req_edu_label}"
    ).italic = True

    doc.add_paragraph("")

    for i, c in enumerate(top_candidates, 1):
        # Candidate heading
        p = doc.add_paragraph()
        run = p.add_run(f"{i}. {c['name']}  —  Match Score: {c['score']}%")
        run.bold = True
        run.font.size = Pt(12)

        # Meta row
        exp_display = (f"{c['experience_years']:.1f} yrs"
                       if c['experience_years'] > 0 else "Not found")
        doc.add_paragraph(
            f"File: {c['file_name']}   |   "
            f"Experience: {exp_display}   |   "
            f"Highest Education: {c['education_label']}"
        )

        # Strengths / Gaps table
        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        hdr[0].text = "✔ Strengths"
        hdr[1].text = "✘ Gaps"
        for cell in hdr:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.bold = True

        strengths = c.get("strengths", [])
        gaps = c.get("gaps", [])
        max_len = max(len(strengths), len(gaps), 1)

        for j in range(max_len):
            row = table.add_row().cells
            row[0].text = strengths[j] if j < len(strengths) else ""
            row[1].text = gaps[j] if j < len(gaps) else ""

        doc.add_paragraph("")   # spacer

    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


# ================================================================
#  STREAMLIT UI
# ================================================================

st.set_page_config(page_title="AI Hiring Assistant", page_icon="🧑‍💼")
st.title("🧑‍💼 Rule-Based Hiring Assistant")
st.caption(
    "Deterministic scoring — same inputs always produce the same score. "
    "Weights: Skills 40% · Experience 40% · Education 20%"
)

# JD Upload
jd_file = st.file_uploader("Upload Job Description (PDF or DOCX)", type=["pdf", "docx"])
jd_text = ""
if jd_file:
    jd_text = extract_text(jd_file)
    st.success("✅ Job Description uploaded")

    with st.expander("🔍 Parsed JD signals"):
        jd_skills = extract_jd_skills(jd_text)
        req_years = extract_required_experience(jd_text)
        req_edu = extract_required_education(jd_text)
        st.write(f"**Required experience:** {req_years:.0f} years")
        st.write(f"**Required education:** {EDUCATION_LABEL.get(req_edu, 'Not specified')}")
        st.write(f"**Extracted skill keywords ({len(jd_skills)}):** {', '.join(jd_skills[:30])}"
                 + (" …" if len(jd_skills) > 30 else ""))

# Resume Upload
resume_files = st.file_uploader(
    "Upload Resumes (PDF or DOCX)",
    type=["pdf", "docx"],
    accept_multiple_files=True,
)
if resume_files:
    st.success(f"✅ {len(resume_files)} resume(s) uploaded")

top_n = st.slider("Number of top candidates to include in report", 1, 20, 3)

if st.button("🔍 Analyze Candidates"):
    if not jd_text or not resume_files:
        st.warning("⚠️ Please upload both a Job Description and at least one Resume.")
    else:
        jd_skills = extract_jd_skills(jd_text)
        req_years = extract_required_experience(jd_text)
        req_edu = extract_required_education(jd_text)

        results = []
        progress = st.progress(0)
        for idx, file in enumerate(resume_files):
            resume_text = extract_text(file)
            result = analyze_candidate(
                resume_text, file.name, jd_skills, req_years, req_edu
            )
            results.append(result)
            progress.progress((idx + 1) / len(resume_files))

        sorted_results = sorted(results, key=lambda x: x["score"], reverse=True)
        top_candidates = sorted_results[:top_n]

        st.success("✅ Analysis complete")

        # On-screen table
        st.subheader("📊 Candidate Rankings")
        for i, c in enumerate(sorted_results, 1):
            tag = "🏆" if i <= top_n else "  "
            st.write(
                f"{tag} **#{i} {c['name']}** — Score: `{c['score']}%` | "
                f"Exp: `{c['experience_years']:.1f} yrs` | "
                f"Edu: `{c['education_label']}`"
            )

        # Download
        report = generate_report(top_candidates, req_years, req_edu)
        st.download_button(
            label="📄 Download Top Candidates Report (.docx)",
            data=report,
            file_name="Top_Candidates_Report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
