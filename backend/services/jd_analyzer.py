import re
import spacy

from spacy.matcher import PhraseMatcher


TOP_K = 5

MODEL_NAME = "en_core_web_sm"

nlp = spacy.load(MODEL_NAME)

skill_matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

TECHNICAL_SKILLS = [
    "python", "sql", "excel", "advanced excel",
    "power bi", "tableau", "machine learning",
    "deep learning", "pytorch", "tensorflow",
    "aws", "azure", "gcp", "databricks",
    "spark", "airflow", "dbt", "snowflake",
    "postgresql", "mysql", "mongodb",
    "etl", "data modelling", "data modeling",
    "statistics", "scikit-learn", "scikit learn",
    "pandas", "numpy", "fastapi", "docker",
    "kubernetes", "git", "linux"
]

SOFT_SKILLS = [
    "communication", "teamwork", "collaboration",
    "leadership", "problem solving",
    "critical thinking", "time management",
    "stakeholder management", "interpersonal skills",
    "attention to detail", "adaptability"
]

QUALIFICATION_TERMS = [
    "bachelor", "bachelor's degree",
    "master", "master's degree",
    "phd", "doctorate", "degree",
    "diploma", "certification",
    "qualification", "graduate",
    "postgraduate"
]

RESPONSIBILITY_VERBS = {
    "develop", "design", "build", "create",
    "maintain", "analyse", "analyze",
    "monitor", "implement", "automate",
    "optimise", "optimize", "manage",
    "visualise", "visualize", "report",
    "evaluate", "investigate", "coordinate",
    "deliver", "support", "improve",
    "deploy", "analyse", "prepare"
}

EXPERIENCE_TERMS = {
    "experience", "experienced",
    "background", "years"
}

SECTION_CONFIG = {
    "requirements": {
        "category": None,
        "priority": "unspecified"
    },
    "required skills": {
        "category": "technical_skills",
        "priority": "required"
    },
    "essential skills": {
        "category": "technical_skills",
        "priority": "required"
    },
    "technical skills": {
        "category": "technical_skills",
        "priority": "unspecified"
    },
    "responsibilities": {
        "category": "responsibilities",
        "priority": "unspecified"
    },
    "key responsibilities": {
        "category": "responsibilities",
        "priority": "unspecified"
    },
    "what you'll do": {
        "category": "responsibilities",
        "priority": "unspecified"
    },
    "qualifications": {
        "category": "qualifications",
        "priority": "unspecified"
    },
    "required qualifications": {
        "category": "qualifications",
        "priority": "required"
    },
    "preferred qualifications": {
        "category": "qualifications",
        "priority": "preferred"
    },
    "education": {
        "category": "qualifications",
        "priority": "unspecified"
    },
    "experience": {
        "category": "experience",
        "priority": "unspecified"
    },
    "preferred skills": {
        "category": "technical_skills",
        "priority": "preferred"
    }
}

for skill in TECHNICAL_SKILLS:
    skill_matcher.add(skill, [nlp.make_doc(skill)])


def clean_text(text: str) -> str:

    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def detect_section(line: str):
    heading = line.strip().lower().rstrip(":").strip()
    return SECTION_CONFIG.get(heading)


def get_priority(text: str, inherited_priority="unspecified") -> str:
    text_lower = text.lower()

    not_required_patterns = [
        r"\bnot required\b",
        r"\bnot essential\b",
        r"\bnot necessary\b",
        r"\bno requirement\b"
    ]

    preferred_patterns = [
        r"\bpreferred\b",
        r"\bpreferably\b",
        r"\bdesirable\b",
        r"\badvantageous\b",
        r"\bnice to have\b",
        r"\bwould be an advantage\b"
    ]

    required_patterns = [
        r"\brequired\b",
        r"\bmust have\b",
        r"\bmandatory\b",
        r"\bessential\b",
        r"\bminimum\b",
        r"\bneed to\b",
        r"\bshould have\b"
    ]

    if any(re.search(p, text_lower) for p in not_required_patterns):
        return "not_required"

    if any(re.search(p, text_lower) for p in preferred_patterns):
        return "preferred"

    if any(re.search(p, text_lower) for p in required_patterns):
        return "required"

    return inherited_priority


def classify_requirement(text: str, section=None) -> list:

    doc = nlp(text)

    categories = set()

    if skill_matcher(doc):
        categories.add("technical_skills")

    if any(
        token.lemma_.lower() in RESPONSIBILITY_VERBS
        for token in doc
    ):
        categories.add("responsibilities")

    if any(
        term in text.lower()
        for term in QUALIFICATION_TERMS
    ):
        categories.add("qualifications")

    if any(
        token.lemma_.lower() in EXPERIENCE_TERMS
        for token in doc
    ) or re.search(r"\b\d+\+?\s+years?\b", text.lower()):
        categories.add("experience")

    if any(
        skill in text.lower()
        for skill in SOFT_SKILLS
    ):
        categories.add("soft_skills")

    if section:
        categories.add(section)

    return sorted(categories)


def split_requirements(job_description: str) -> list:
    requirements = []
    current_section = {
        "category": None,
        "priority": "unspecified"
    }

    lines = job_description.splitlines()

    for line in lines:
        line = clean_text(line)

        if not line:
            continue

        section = detect_section(line)

        if section is not None:
            current_section = section
            continue

        line = re.sub(
            r"^[\s•●▪◦\-*]+",
            "",
            line
        ).strip()

        if not line:
            continue

        doc = nlp(line)

        for sentence in doc.sents:
            text = sentence.text.strip()

            if len(text.split()) < 3:
                continue

            categories = classify_requirement(
                text,
                current_section["category"]
            )

            if not categories:
                continue

            requirements.append({
                "requirement_id": f"R{len(requirements) + 1:03d}",
                "text": text,
                "categories": categories,
                "priority": get_priority(
                    text,
                    current_section["priority"]
                )
            })

    return requirements


def extract_requirements(job_description: str) -> list:

    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    return split_requirements(job_description)