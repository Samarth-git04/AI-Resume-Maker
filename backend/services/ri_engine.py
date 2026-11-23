import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.services.context_builder import build_ai_context
from backend.services.llm_service import generate_response
from backend.services.resume_structure import build_resume_structure

logger = logging.getLogger(__name__)


def _numbers(text: str) -> set:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text or ""))


def _safe_rewrite(original: str, proposed: Any) -> str | None:
    if not isinstance(proposed, str) or not proposed.strip():
        return None

    proposed = re.sub(r"\s+", " ", proposed).strip()
    if len(proposed) > max(450, len(original) * 2.5):
        return None

    # Do not accept newly introduced numeric claims, dates, percentages or
    # quantities that cannot be traced to the original paragraph.
    if _numbers(proposed) - _numbers(original):
        return None

    return proposed


def _fallback_project_selection(projects: list, paragraph_lookup: dict) -> list:
    ranked = []
    for project in projects:
        scores = []
        for paragraph_id in project["paragraph_ids"]:
            paragraph = paragraph_lookup.get(paragraph_id, {})
            for match in paragraph.get("matched_requirements", []):
                score = match.get("score")
                if isinstance(score, (int, float)):
                    scores.append(float(score))
        ranked.append((
            max(scores) if scores else 0.0,
            sum(scores) / len(scores) if scores else 0.0,
            project["title_id"]
        ))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:3]]


def _normalise_model_decisions(
    model_decisions: Any,
    records: list,
    paragraph_lookup: dict,
    requirements: list,
) -> dict:
    valid_ids = {item["id"] for item in records}
    requirement_ids = {item["requirement_id"] for item in requirements}
    result = {}

    if not isinstance(model_decisions, list):
        model_decisions = []

    for decision in model_decisions:
        if not isinstance(decision, dict):
            continue

        ids = decision.get("source_paragraph_ids")
        if not isinstance(ids, list) or len(ids) != 1:
            continue

        paragraph_id = ids[0]
        if paragraph_id not in valid_ids or paragraph_id in result:
            continue

        source = paragraph_lookup[paragraph_id]
        action = decision.get("action")
        if action not in {"keep", "rewrite", "remove"}:
            continue

        matched = decision.get("matched_requirements", [])
        if not isinstance(matched, list):
            matched = []
        matched = [item for item in matched if item in requirement_ids]

        if action == "rewrite":
            rewritten = _safe_rewrite(
                source["text"],
                decision.get("rewritten_text")
            )
            if rewritten is None:
                action = "keep"
                rewritten = None
        else:
            rewritten = None

        result[paragraph_id] = {
            "source_paragraph_ids": [paragraph_id],
            "action": action,
            "section_name": source.get("section"),
            "rewritten_text": rewritten,
            "matched_requirements": matched,
        }

    return result


def run_ri_engine(db: Session, resume_id: int, job_description: str) -> dict:
    if not isinstance(job_description, str) or not job_description.strip():
        raise ValueError("Job description cannot be empty.")

    context = build_ai_context(db, resume_id, job_description)
    paragraphs = context["resume_paragraphs"]
    formatting = context["resume_formatting"]

    if len(paragraphs) < 4:
        raise ValueError("The uploaded resume does not contain enough content.")

    structure = build_resume_structure(paragraphs, formatting)
    records = structure["records"]
    projects = structure["projects"]
    profile_id = structure["profile_id"]

    if len(projects) < 3:
        raise ValueError(
            f"At least three identifiable project titles are required; found {len(projects)}."
        )

    paragraph_lookup = {
        item["paragraph_id"]: item
        for item in paragraphs
    }
    record_lookup = {item["id"]: item for item in records}

    header_ids = {item["id"] for item in records if item["role"] == "header"}
    editable_ids = structure["editable_ids"] - header_ids
    if profile_id:
        editable_ids.discard(profile_id)

    # Build a compact, explicit structure map for the model. The model never
    # receives permission to rename, reorder or recreate structural elements.
    project_payload = []
    for project in projects:
        project_payload.append({
            "title_id": project["title_id"],
            "title": project["title"],
            "paragraphs": [
                {
                    "id": pid,
                    "text": paragraph_lookup[pid]["text"],
                    "matched_requirements": paragraph_lookup[pid]["matched_requirements"],
                }
                for pid in project["paragraph_ids"]
                if pid != project["title_id"]
            ],
        })

    editable_payload = [
        {
            "id": item["id"],
            "section": item["section"],
            "text": item["text"],
            "matched_requirements": paragraph_lookup[item["id"]]["matched_requirements"],
        }
        for item in records
        if item["id"] in editable_ids and item["role"] != "project_content"
    ]

    project_content_payload = [
        {
            "id": item["id"],
            "section": item["section"],
            "text": item["text"],
            "matched_requirements": paragraph_lookup[item["id"]]["matched_requirements"],
        }
        for item in records
        if item["role"] == "project_content"
    ]

    profile_text = (
        paragraph_lookup[profile_id]["text"]
        if profile_id and profile_id in paragraph_lookup
        else ""
    )

    system_prompt = """
You are a conservative professional resume editor. The supplied resume is the
only source of candidate facts.

Your tasks:
1. Write a concise professional summary based only on the original profile and
   factual resume content. Do not infer years of experience, seniority, metrics,
   qualifications, employers, dates, tools or achievements.
2. Select exactly THREE projects from the supplied project list. Return only
   their title paragraph IDs in selected_project_ids.
3. Edit only the supplied editable paragraphs and project description paragraphs.
   Use keep, rewrite or remove. Rewrite only when it improves relevance or clarity.
4. Preserve the factual meaning, technical detail and all numeric claims.
5. Never invent a skill merely because it appears in the job description.
6. Do not create section names, headings, job titles, employer names or dates.
7. Do not merge paragraphs. Do not return decisions for paragraph IDs not supplied.

Return one JSON object with exactly these keys:
{
  "professional_summary": "string",
  "selected_project_ids": ["P1", "P2", "P3"],
  "paragraph_decisions": [
    {
      "source_paragraph_ids": ["P4"],
      "action": "keep",
      "rewritten_text": null,
      "matched_requirements": ["R001"]
    }
  ],
  "changes_summary": ["short explanation"]
}

Every editable paragraph ID supplied must have exactly one decision.
Every project description paragraph supplied must have exactly one decision.
Use one source paragraph ID per decision. Do not return section_name.
For keep and remove, rewritten_text must be null. For rewrite, provide text.
Do not add markdown or text outside the JSON object.
""".strip()

    user_payload = {
        "job_requirements": context["job_requirements"],
        "original_profile": profile_text,
        "editable_paragraphs": editable_payload,
        "project_groups": project_payload,
        "project_description_paragraphs": project_content_payload,
    }

    import json
    response = generate_response(
        system_prompt=system_prompt,
        user_prompt=json.dumps(user_payload, ensure_ascii=False)
    )

    if not isinstance(response, dict):
        raise ValueError("The resume editor returned an invalid response.")

    # The model may omit or misidentify project IDs. In that case, use the
    # paragraph-level retrieval evidence to make a deterministic selection.
    valid_project_ids = {item["title_id"] for item in projects}
    selected = response.get("selected_project_ids")
    if (
        not isinstance(selected, list)
        or len(selected) != 3
        or len(set(selected)) != 3
        or not set(selected).issubset(valid_project_ids)
    ):
        selected = _fallback_project_selection(projects, paragraph_lookup)

    if len(selected) != 3:
        raise ValueError("Could not select exactly three projects.")

    # A summary containing a new number or an unsupported experience-duration
    # claim is rejected in favour of the candidate's own source profile.
    summary = response.get("professional_summary")
    if not isinstance(summary, str) or not summary.strip():
        summary = profile_text
    else:
        summary = re.sub(r"\s+", " ", summary).strip()
        all_source_text = " ".join(item["text"] for item in paragraphs)
        if _numbers(summary) - _numbers(all_source_text):
            summary = profile_text
        if re.search(r"\b\d+\+?\s+years?\s+(?:of\s+)?experience\b", summary, re.I):
            if not re.search(
                r"\b\d+\+?\s+years?\s+(?:of\s+)?experience\b",
                all_source_text,
                re.I
            ):
                summary = profile_text
        if len(summary.split()) > 65:
            summary = profile_text

    model_decisions = _normalise_model_decisions(
        response.get("paragraph_decisions"),
        records,
        record_lookup,
        context["job_requirements"],
    )

    decisions = []
    for item in records:
        pid = item["id"]
        if pid in header_ids or pid == profile_id:
            continue

        if pid in model_decisions and pid in editable_ids | {
            record["id"] for record in records if record["role"] == "project_content"
        }:
            decisions.append(model_decisions[pid])
        else:
            decisions.append({
                "source_paragraph_ids": [pid],
                "action": "keep",
                "section_name": item["section"],
                "rewritten_text": None,
                "matched_requirements": [
                    match["requirement_id"]
                    for match in paragraph_lookup[pid]["matched_requirements"]
                    if "requirement_id" in match
                ],
            })

    # This is an invariant for downstream rendering: every non-header,
    # non-profile source paragraph appears exactly once in the decision list.
    expected_ids = {
        item["id"] for item in records
        if item["id"] not in header_ids and item["id"] != profile_id
    }
    returned_ids = [
        pid
        for decision in decisions
        for pid in decision["source_paragraph_ids"]
    ]
    if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
        raise ValueError("Internal resume decision validation failed.")

    changes = response.get("changes_summary", [])
    if not isinstance(changes, list):
        changes = []
    changes = [str(item).strip() for item in changes if str(item).strip()][:8]

    logger.info(
        "Resume tailoring complete. resume_id=%s source_paragraphs=%s selected_projects=%s",
        resume_id,
        len(paragraphs),
        len(selected)
    )

    return {
        "professional_summary": summary,
        "selected_project_ids": selected,
        "paragraph_decisions": decisions,
        "changes_summary": changes,
    }
