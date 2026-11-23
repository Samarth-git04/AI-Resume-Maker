import json
import logging
import re

from backend.services.llm_service import generate_response
from backend.services.resume_text import clean_resume_text


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are an expert resume writer and evidence-constrained editor.

You receive:
- A job description and extracted requirements.
- The candidate's complete source resume.
- Stable source paragraph IDs.
- Relevance evidence from semantic and lexical retrieval.

The source resume is the only source of candidate facts.

Never invent:
- Employers, job titles, dates or duration of employment.
- Degrees, institutions, qualifications or certifications.
- Skills, tools, programming languages or technologies.
- Responsibilities, achievements, metrics or outcomes.

Your task is to create a tailored resume plan.

1. PROFESSIONAL SUMMARY
Write a concise summary targeted to the job description.
Use only facts supported by source paragraph IDs.
Do not infer experience duration or seniority.
Return the source IDs used.

2. PROJECT SELECTION
Select the most relevant projects for this job.
You may select between zero and all supplied projects.
Do not select a project merely to fill a fixed number.
Use the exact project title source ID.
Do not invent project titles.

3. EXPERIENCE AND PROJECT CONTENT
For every supplied editable paragraph, return exactly one decision.
Use:
- keep: preserve its meaning and wording.
- rewrite: improve clarity and relevance without changing facts.
- remove: omit content that adds little value for this job.

Do not remove an entire employment role if it contains useful evidence.
Do not merge separate source paragraphs.
Do not create a new bullet without a source paragraph.

4. ACHIEVEMENTS
Select up to three relevant achievements.
Use only supplied achievement IDs.
Do not force three selections if fewer are relevant.
Preserve employer names and numerical claims.

5. SKILLS
Select skills that are explicitly supported by the resume.
Do not add job-description skills that the candidate has not demonstrated.

6. NUMBERS AND DATES
Preserve source numbers exactly.
Do not introduce new numbers, percentages, dates, durations or quantities.

7. SOURCE PROVENANCE
Every generated summary, selected project, selected achievement and
rewritten paragraph must reference one or more valid source paragraph IDs.

Return only one JSON object with this structure:

{
  "professional_summary": {
    "text": "Summary text",
    "source_ids": ["P1", "P2"]
  },
  "selected_project_ids": ["P10"],
  "selected_achievement_ids": ["P5"],
  "paragraph_decisions": {
    "P6": {
      "action": "rewrite",
      "text": "Rewritten paragraph",
      "source_ids": ["P6"]
    }
  },
  "selected_skills": [
    {
      "text": "Python",
      "source_ids": ["P8"]
    }
  ],
  "changes_summary": [
    "Prioritised experience relevant to the target role."
  ]
}

The paragraph_decisions object MUST contain every ID in editable_ids
exactly once. Do not include any other IDs.

For keep and remove actions, text must be null.
For rewrite actions, text must contain the complete rewritten paragraph.
Every rewritten paragraph must cite its own source paragraph ID.

Return valid JSON only. Do not include markdown.
""".strip()


def _numbers(text):
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text or ""))


def _source_map(context):
    return {
        item["paragraph_id"]: item["text"]
        for item in context["resume_paragraphs"]
    }


def _validate_summary(summary, source_map):
    if not isinstance(summary, dict):
        raise ValueError("The generated summary is missing.")

    text = clean_resume_text(summary.get("text"))
    source_ids = summary.get("source_ids")

    if not text or not isinstance(source_ids, list) or not source_ids:
        raise ValueError("The generated summary has no source evidence.")

    if not set(source_ids).issubset(source_map):
        raise ValueError("The summary references unknown source IDs.")

    source_text = " ".join(source_map[item] for item in source_ids)

    if _numbers(text) - _numbers(source_text):
        raise ValueError("The summary contains unsupported numerical claims.")

    if len(text.split()) > 65:
        raise ValueError("The generated summary is too long.")

    return {
        "text": text,
        "source_ids": list(dict.fromkeys(source_ids)),
    }


def _validate_project_ids(project_ids, project_map):
    if not isinstance(project_ids, list):
        raise ValueError("Selected project IDs must be a list.")

    if len(project_ids) != len(set(project_ids)):
        raise ValueError("Duplicate project IDs were returned.")

    if not set(project_ids).issubset(project_map):
        raise ValueError("The model selected an unknown project.")

    return project_ids


def _validate_achievement_ids(achievement_ids, achievement_map):
    if not isinstance(achievement_ids, list):
        raise ValueError("Selected achievement IDs must be a list.")

    if len(achievement_ids) > 3:
        raise ValueError("The model selected more than three achievements.")

    if len(achievement_ids) != len(set(achievement_ids)):
        raise ValueError("Duplicate achievement IDs were returned.")

    if not set(achievement_ids).issubset(achievement_map):
        raise ValueError("The model selected an unknown achievement.")

    return achievement_ids


def _validate_decisions(decisions, editable_ids, source_map):
    if not isinstance(decisions, dict):
        raise ValueError("Paragraph decisions must be an object.")

    expected = set(editable_ids)
    returned = set(decisions)

    if expected != returned:
        raise ValueError(
            "Paragraph decision IDs do not match the supplied editable IDs. "
            f"Missing: {sorted(expected - returned)}; "
            f"unknown: {sorted(returned - expected)}."
        )

    validated = {}

    for paragraph_id, decision in decisions.items():
        if not isinstance(decision, dict):
            raise ValueError(f"Invalid decision for {paragraph_id}.")

        action = decision.get("action")
        text = decision.get("text")
        source_ids = decision.get("source_ids")

        if action not in {"keep", "rewrite", "remove"}:
            raise ValueError(f"Invalid action for {paragraph_id}.")

        if action in {"keep", "remove"}:
            if text is not None:
                raise ValueError(
                    f"{action} decision for {paragraph_id} must have null text."
                )

            validated[paragraph_id] = {
                "action": action,
                "text": None,
                "source_ids": [paragraph_id],
            }
            continue

        rewritten = clean_resume_text(text)

        if not rewritten:
            raise ValueError(f"Empty rewrite for {paragraph_id}.")

        if not isinstance(source_ids, list) or paragraph_id not in source_ids:
            raise ValueError(
                f"Rewrite for {paragraph_id} lacks its own source ID."
            )

        if not set(source_ids).issubset(source_map):
            raise ValueError(
                f"Rewrite for {paragraph_id} references unknown source IDs."
            )

        original = source_map[paragraph_id]

        if _numbers(rewritten) - _numbers(original):
            raise ValueError(
                f"Rewrite for {paragraph_id} introduces unsupported numbers."
            )

        if len(rewritten) > max(450, len(original) * 2.5):
            raise ValueError(
                f"Rewrite for {paragraph_id} is disproportionately long."
            )

        validated[paragraph_id] = {
            "action": "rewrite",
            "text": rewritten,
            "source_ids": [paragraph_id],
        }

    return validated


def generate_resume(context, structure):
    source_map = _source_map(context)

    records = structure["records"]
    projects = structure["projects"]

    project_map = {
        item["title_id"]: item
        for item in projects
    }

    achievement_records = [
        item
        for item in records
        if item.get("section") == "HIGHLIGHTS"
        and item.get("role") in {"bullet", "content"}
    ]

    achievement_map = {
        item["id"]: item
        for item in achievement_records
    }

    editable_sections = {
        "EXPERIENCE",
        "PROJECTS",
        "HIGHLIGHTS",
    }

    editable_ids = [
        item["id"]
        for item in records
        if (
            item["role"] in {"bullet", "content", "project_content"}
            and item["section"] in editable_sections
        )
    ]

    if not editable_ids:
        raise ValueError("No editable resume content was identified.")

    payload = {
        "job_requirements": context["job_requirements"],
        "resume_paragraphs": context["resume_paragraphs"],
        "projects": [
            {
                "title_id": project["title_id"],
                "title": project["title"],
                "paragraph_ids": project["paragraph_ids"],
                "content_ids": project["content_ids"],
            }
            for project in projects
        ],
        "achievements": [
            {
                "paragraph_id": item["id"],
                "text": item["text"],
                "matched_requirements": next(
                    (
                        paragraph["matched_requirements"]
                        for paragraph in context["resume_paragraphs"]
                        if paragraph["paragraph_id"] == item["id"]
                    ),
                    [],
                ),
            }
            for item in achievement_records
        ],
        "editable_ids": editable_ids,
    }

    logger.info(
        "Starting single-pass resume generation. paragraphs=%d projects=%d",
        len(source_map),
        len(projects),
    )

    response = generate_response(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False),
    )

    if not isinstance(response, dict):
        raise ValueError("The model returned an invalid resume object.")

    summary = _validate_summary(
        response.get("professional_summary"),
        source_map,
    )

    selected_projects = _validate_project_ids(
        response.get("selected_project_ids"),
        project_map,
    )

    selected_achievements = _validate_achievement_ids(
        response.get("selected_achievement_ids"),
        achievement_map,
    )

    decisions = _validate_decisions(
        response.get("paragraph_decisions"),
        editable_ids,
        source_map,
    )

    changes = response.get("changes_summary", [])

    if not isinstance(changes, list):
        changes = []

    changes = [
        clean_resume_text(item)
        for item in changes
        if isinstance(item, str) and clean_resume_text(item)
    ][:8]

    selected_skills = response.get("selected_skills", [])

    if not isinstance(selected_skills, list):
        selected_skills = []

    validated_skills = []

    for skill in selected_skills:
        if not isinstance(skill, dict):
            continue

        text = clean_resume_text(skill.get("text"))
        source_ids = skill.get("source_ids")

        if (
            text
            and isinstance(source_ids, list)
            and source_ids
            and set(source_ids).issubset(source_map)
        ):
            validated_skills.append({
                "text": text,
                "source_ids": list(dict.fromkeys(source_ids)),
            })

    return {
        "professional_summary": summary["text"],
        "summary_source_ids": summary["source_ids"],
        "selected_project_ids": selected_projects,
        "selected_achievement_ids": selected_achievements,
        "paragraph_decisions": [
            {
                "source_paragraph_ids": [paragraph_id],
                "action": decision["action"],
                "section_name": next(
                    (
                        item["section"]
                        for item in records
                        if item["id"] == paragraph_id
                    ),
                    None,
                ),
                "rewritten_text": decision["text"],
                "source_ids": decision["source_ids"],
            }
            for paragraph_id, decision in decisions.items()
        ],
        "selected_skills": validated_skills,
        "changes_summary": changes,
        "generation_version": "2.0",
    }