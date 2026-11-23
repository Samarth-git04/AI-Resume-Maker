import re
import unicodedata


# Known extraction artefacts observed in uploaded resumes.
# Do not remove all hyphens: compounds such as "decision-ready"
# and "end-to-end" are legitimate.
KNOWN_HYPHENATION_REPAIRS = {
    "stake-holders": "stakeholders",
    "stakehold-ers": "stakeholders",
    "stake-holder": "stakeholder",
    "stakehold-er": "stakeholder",
    "effi-ciency": "efficiency",
    "efficien-cy": "efficiency",
    "Ex-ploratory": "Exploratory",
    "ex-ploratory": "exploratory",
    "De-velopment": "Development",
    "de-velopment": "development",
    "atmo-spheric": "atmospheric",
    "configura-tion": "configuration",
    "elimi-nating": "eliminating",
    "appli-cation": "application",
    "work-flows": "workflows",
    "classifi-cation": "classification",
    "visibili-ty": "visibility",
    "develop-ment": "development",
    "implemen-tation": "implementation",
    "manage-ment": "management",
    "analy-sis": "analysis",
    "ana-lytics": "analytics",
    "profes-sional": "professional",
    "quali-fication": "qualification",
    "experi-ence": "experience",
    "communi-cation": "communication",
    "collabo-ration": "collaboration",
    "dash-board": "dashboard",
    "pipe-line": "pipeline",
    "pipe-lines": "pipelines",
    "auto-mated": "automated",
    "auto-mation": "automation",
    "transfor-mation": "transformation",
    "visuali-sation": "visualisation",
    "visuali-zation": "visualization",
    "priori-tised": "prioritised",
    "priori-tized": "prioritized",
    "opti-misation": "optimisation",
    "opti-mization": "optimization",
    "decision-mak-ing": "decision-making",
    "report-ing": "reporting",
    "process-ing": "processing",
    "integra-tion": "integration",
    "relia-bility": "reliability",
    "consis-tent": "consistent",
    "consis-tency": "consistency",
    "perform-ance": "performance",
    "require-ments": "requirements",
    "imple-mented": "implemented",
    "docu-ments": "documents",
    "docu-ment": "document",
    "func-tion": "function",
    "func-tional": "functional",
    "infor-mation": "information",
    "profici-ent": "proficient",
    "statisti-cal": "statistical",
    "transac-tional": "transactional",
    "identi-fied": "identified",
    "identi-fying": "identifying",
    "opportu-nities": "opportunities",
    "opportu-nity": "opportunity",
    "dash-boards": "dashboards",
}

_HYPHEN_CHARS = r"\-‐-‒–"


def _case_like(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()

    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]

    return replacement


def repair_known_hyphenation(text: str) -> str:
    if not isinstance(text, str) or not text:
        return ""

    for broken, corrected in KNOWN_HYPHENATION_REPAIRS.items():
        parts = re.split(r"[-‐-‒–]", broken)

        if len(parts) != 2:
            continue

        pattern = re.compile(
            rf"(?<![\w]){re.escape(parts[0])}[{_HYPHEN_CHARS}]"
            rf"{re.escape(parts[1])}(?![\w])",
            re.IGNORECASE,
        )

        text = pattern.sub(
            lambda match, replacement=corrected:
                _case_like(match.group(0), replacement),
            text,
        )

    return text


def clean_resume_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    text = unicodedata.normalize("NFC", text)

    text = (
        text.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u00ad", "")
    )

    text = re.sub(
        r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]",
        "",
        text,
    )

    text = repair_known_hyphenation(text)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def comparison_text(text: str) -> str:
    return clean_resume_text(text).casefold()


def strip_leading_bullet_markers(text: str) -> str:
    """
    Remove literal bullet glyphs before applying Word's List Bullet style.
    Handles repeated markers such as '• • Combined ...'.
    """

    text = clean_resume_text(text)

    bullet_pattern = re.compile(
        r"^\s*[•●▪◦‣∙·\uf0b7]\s*"
    )

    previous = None

    while text != previous:
        previous = text
        text = bullet_pattern.sub("", text, count=1)

    return text.strip()