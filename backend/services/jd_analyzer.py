import re


TOP_K = 8

TECHNICAL_SKILLS = [
    "python", "sql", "excel", "advanced excel",
    "power bi", "tableau", "machine learning",
    "deep learning", "pytorch", "tensorflow",
    "aws", "azure", "gcp", "google cloud",
    "databricks", "spark", "airflow", "dbt",
    "snowflake", "postgresql", "mysql", "mongodb",
    "etl", "data modelling", "data modeling",
    "statistics", "scikit-learn", "scikit learn",
    "pandas", "numpy", "fastapi", "docker",
    "kubernetes", "git", "linux", "javascript",
    "typescript", "react", "node.js", "faiss",
    "geant4", "langgraph", "supabase",
    "bigquery", "power query", "looker",
    "matplotlib", "plotly", "java", "c++",
]

SOFT_SKILLS = [
    "communication", "teamwork", "collaboration",
    "leadership", "problem solving", "critical thinking",
    "time management", "stakeholder management",
    "interpersonal skills", "attention to detail",
    "adaptability", "presentation skills",
]

QUALIFICATION_TERMS = [
    "bachelor", "bachelor's degree", "master",
    "master's degree", "phd", "doctorate",
    "degree", "diploma", "certification",
    "qualification", "graduate", "postgraduate",
]

SECTION_CATEGORIES = {
    "responsibilities": "responsibilities",
    "key responsibilities": "responsibilities",
    "what you'll do": "responsibilities",
    "what you will do": "responsibilities",
    "requirements": None,
    "required skills": "technical_skills",
    "essential skills": "technical_skills",
    "technical skills": "technical_skills",
    "preferred skills": "technical_skills",
    "qualifications": "qualifications",
    "required qualifications": "qualifications",
    "preferred qualifications": "qualifications",
    "education": "qualifications",
    "experience": "experience",
    "about you": None,
    "about the role": None,
}

REQUIRED_PATTERNS = [
    r"\brequired\b",
    r"\bmust have\b",
    r"\bmandatory\b",
    r"\bessential\b",
    r"\bminimum\b",
    r"\bneed to\b",
]

PREFERRED_PATTERNS = [
    r"\bpreferred\b",
    r"\bpreferably\b",
    r"\bdesirable\b",
    r"\badvantageous\b",
    r"\bnice to have\b",
    r"\bwould be an advantage\b",
]

NOT_REQUIRED_PATTERNS = [
    r"\bnot required\b",
    r"\bnot essential\b",
    r"\bnot necessary\b",
]


def clean_text(text):
    text = str(text or "").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _priority(text, inherited="unspecified"):
    lowered = text.lower()

    if any(re.search(pattern, lowered) for pattern in NOT_REQUIRED_PATTERNS):
        return "not_required"

    if any(re.search(pattern, lowered) for pattern in PREFERRED_PATTERNS):
        return "preferred"

    if any(re.search(pattern, lowered) for pattern in REQUIRED_PATTERNS):
        return "required"

    return inherited


def _categories(text, section_category=None):
    lowered = text.lower()
    categories = set()

    if any(
        re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", lowered)
        for skill in TECHNICAL_SKILLS
    ):
        categories.add("technical_skills")

    if any(skill in lowered for skill in SOFT_SKILLS):
        categories.add("soft_skills")

    if any(term in lowered for term in QUALIFICATION_TERMS):
        categories.add("qualifications")

    if re.search(
        r"\b(develop|design|build|create|maintain|analyse|analyze|"
        r"monitor|implement|automate|manage|visualise|visualize|"
        r"report|evaluate|investigate|coordinate|deliver|support|"
        r"improve|deploy|prepare|present)\b",
        lowered,
    ):
        categories.add("responsibilities")

    if (
        re.search(r"\b\d+\+?\s+years?\b", lowered)
        or "experience" in lowered
    ):
        categories.add("experience")

    if section_category:
        categories.add(section_category)

    return sorted(categories)


def _split_sentences(line):
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+|;\s*", line)
        if len(item.strip().split()) >= 3
    ]


def extract_requirements(job_description):
    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    requirements = []
    current_category = None
    current_priority = "unspecified"

    for raw_line in job_description.splitlines():
        line = clean_text(raw_line)

        if not line:
            continue

        heading = line.lower().rstrip(":").strip()

        if heading in SECTION_CATEGORIES:
            current_category = SECTION_CATEGORIES[heading]
            current_priority = (
                "required"
                if heading.startswith("required") or heading == "essential skills"
                else "preferred"
                if heading.startswith("preferred")
                else "unspecified"
            )
            continue

        line = re.sub(r"^[\s•●▪◦‣*\-]+", "", line).strip()

        if not line:
            continue

        for sentence in _split_sentences(line):
            categories = _categories(sentence, current_category)

            if not categories:
                continue

            requirements.append({
                "requirement_id": f"R{len(requirements) + 1:03d}",
                "text": sentence,
                "categories": categories,
                "priority": _priority(sentence, current_priority),
            })

    # Remove near-identical duplicate lines while preserving order.
    unique = []
    seen = set()

    for item in requirements:
        key = re.sub(r"\W+", " ", item["text"].lower()).strip()

        if key in seen:
            continue

        seen.add(key)
        item["requirement_id"] = f"R{len(unique) + 1:03d}"
        unique.append(item)

    return unique