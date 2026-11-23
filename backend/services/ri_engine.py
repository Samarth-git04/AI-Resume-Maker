import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.services.context_builder import build_ai_context
from backend.services.llm_service import generate_response
from backend.services.resume_structure import build_resume_structure
from backend.services.resume_text import clean_resume_text, comparison_text

logger = logging.getLogger(__name__)


def _numbers(text: str) -> set:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text or ""))


def _safe_rewrite(original: str, proposed: Any) -> str | None:
    if not isinstance(proposed, str) or not proposed.strip():
        return None

    proposed = re.sub(r"\s+", " ", proposed).strip()

    if len(proposed) > max(450, len(original) * 2.5):
        return None

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

def _find_key_achievements(records: list) -> list:
    achievement_heading_found = False
    achievement_ids = []

    for record in records:
        section = record.get("section")
        role = record.get("role")
        text = clean_resume_text(record.get("text", ""))

        if not text:
            continue

        if section != "HIGHLIGHTS":
            if achievement_heading_found:
                break
            continue

        if comparison_text(text).rstrip(":").strip() == "key achievements":
            achievement_heading_found = True
            continue

        if not achievement_heading_found:
            continue

        if role in {"subheading", "section_heading"}:
            break

        if role in {"bullet", "content"}:
            achievement_ids.append(record["id"])

    return achievement_ids

def _experience_context(records: list) -> tuple[list, list, str]:
    experience_records = [
        record
        for record in records
        if record.get("section") == "EXPERIENCE"
    ]

    company_candidates = []

    for record in experience_records:
        if record.get("role") != "subheading":
            continue

        candidate = clean_resume_text(record.get("text", ""))

        if candidate and candidate not in company_candidates:
            company_candidates.append(candidate)

    experience_text = "\n".join(
        clean_resume_text(record.get("text", ""))
        for record in experience_records
        if clean_resume_text(record.get("text", ""))
    )

    editable_experience = [
        {
            "id": record["id"],
            "text": record["text"],
            "role": record["role"],
        }
        for record in experience_records
        if record.get("role") in {"bullet", "content"}
    ]

    return editable_experience, company_candidates, experience_text


def _company_is_supported(
    company: str,
    company_candidates: list,
    experience_text: str,
    original_achievement: str,
) -> bool:
    company = clean_resume_text(company)

    if not company:
        return False

    company_key = comparison_text(company)

    if company_candidates:
        if any(
            company_key in comparison_text(candidate)
            for candidate in company_candidates
        ):
            return True

    if company_key in comparison_text(experience_text):
        return True

    prefix_match = re.match(
        r"^\s*(.{2,70}?)\s*:\s*.+$",
        original_achievement,
    )

    if prefix_match and company_key == comparison_text(prefix_match.group(1)):
        return True

    return False


def _achievement_body(original: str, proposed: Any, company: str) -> str | None:
    if not isinstance(proposed, str) or not proposed.strip():
        return None

    proposed = clean_resume_text(proposed)

    prefix = re.match(
        rf"^{re.escape(company)}\s*:\s*(.*)$",
        proposed,
        flags=re.IGNORECASE,
    )

    if prefix:
        proposed = prefix.group(1).strip()

    if not proposed:
        return None

    return _safe_rewrite(original, proposed)


def _normalise_achievements(
    proposed: Any,
    achievement_ids: list,
    paragraph_lookup: dict,
    company_candidates: list,
    experience_text: str,
) -> list:
    if not isinstance(proposed, list) or len(proposed) != 3:
        return []

    valid_ids = set(achievement_ids)
    selected = []
    seen_ids = set()

    for item in proposed:
        if not isinstance(item, dict):
            return []

        paragraph_id = item.get("source_paragraph_id")
        company = clean_resume_text(item.get("company", ""))

        if (
            paragraph_id not in valid_ids
            or paragraph_id in seen_ids
            or not _company_is_supported(
                company,
                company_candidates,
                experience_text,
                paragraph_lookup[paragraph_id]["text"],
            )
        ):
            return []

        original = paragraph_lookup[paragraph_id]["text"]

        body = _achievement_body(
            original,
            item.get("what_i_did"),
            company,
        )

        if body is None:
            return []

        seen_ids.add(paragraph_id)

        selected.append({
            "source_paragraph_id": paragraph_id,
            "company": company,
            "text": f"{company}: {body}",
        })

    return selected if len(selected) == 3 else []


def _fallback_achievements(
    achievement_ids: list,
    paragraph_lookup: dict,
    company_candidates: list,
    experience_text: str,
) -> list:
    ranked = []

    for paragraph_id in achievement_ids:
        paragraph = paragraph_lookup[paragraph_id]

        scores = [
            float(match["score"])
            for match in paragraph.get("matched_requirements", [])
            if isinstance(match.get("score"), (int, float))
        ]

        ranked.append((
            max(scores) if scores else 0.0,
            sum(scores) / len(scores) if scores else 0.0,
            paragraph_id,
        ))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    selected = []

    for _, _, paragraph_id in ranked:
        original = paragraph_lookup[paragraph_id]["text"]

        prefix_match = re.match(
            r"^\s*(.{2,70}?)\s*:\s*(.+)$",
            original,
        )

        company = None
        body = original

        if prefix_match and _company_is_supported(
            prefix_match.group(1),
            company_candidates,
            experience_text,
            original,
        ):
            company = clean_resume_text(prefix_match.group(1))
            body = clean_resume_text(prefix_match.group(2))

        elif len(company_candidates) == 1:
            company = company_candidates[0]

        if not company:
            continue

        selected.append({
            "source_paragraph_id": paragraph_id,
            "company": company,
            "text": f"{company}: {body}",
        })

        if len(selected) == 3:
            return selected

    return []


def _normalise_model_decisions(
    model_decisions: Any,
    records: list,
    paragraph_lookup: dict,
    requirements: list,
    protected_ids: set,
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

        if paragraph_id in protected_ids and action == "remove":
            action = "keep"

        matched = decision.get("matched_requirements", [])

        if not isinstance(matched, list):
            matched = []

        matched = [
            item
            for item in matched
            if item in requirement_ids
        ]

        if action == "rewrite":
            rewritten = _safe_rewrite(
                source["text"],
                decision.get("rewritten_text"),
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

    # print("\n--- RESUME STRUCTURE DEBUG ---")
    # for record in records:
    #     text = str(record.get("text", ""))
    #     if "achievement" in text.lower() or "highlight" in str(record.get("section", "")).lower():
    #         print({
    #             "id": record.get("id"),
    #             "section": record.get("section"),
    #             "role": record.get("role"),
    #             "text": text
    #         })
    # print("--- END DEBUG ---\n")

    if len(projects) < 3:
        raise ValueError(
            f"At least three identifiable project titles are required; found {len(projects)}."
        )

    paragraph_lookup = {
        item["paragraph_id"]: item
        for item in paragraphs
    }

    header_ids = {
        item["id"]
        for item in records
        if item["role"] == "header"
    }

    editable_ids = structure["editable_ids"] - header_ids

    if profile_id:
        editable_ids.discard(profile_id)

    achievement_ids = _find_key_achievements(records)

    if len(achievement_ids) < 3:
        raise ValueError(
            "At least three bullet points are required under HIGHLIGHTS > KEY ACHIEVEMENTS."
        )

    experience_paragraphs, company_candidates, experience_text = (
        _experience_context(records)
    )

    experience_ids = {
        item["id"]
        for item in experience_paragraphs
    }

    achievement_id_set = set(achievement_ids)

    project_payload = []

    for project in projects:
        project_payload.append({
            "title_id": project["title_id"],
            "title": project["title"],
            "paragraphs": [
                {
                    "id": paragraph_id,
                    "text": paragraph_lookup[paragraph_id]["text"],
                    "matched_requirements": paragraph_lookup[paragraph_id]["matched_requirements"],
                }
                for paragraph_id in project["paragraph_ids"]
                if paragraph_id != project["title_id"]
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
        if (
            item["id"] in editable_ids
            and item["id"] not in achievement_id_set
            and item["role"] != "project_content"
        )
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

    achievement_payload = [
        {
            "id": paragraph_id,
            "text": paragraph_lookup[paragraph_id]["text"],
            "matched_requirements": paragraph_lookup[paragraph_id]["matched_requirements"],
        }
        for paragraph_id in achievement_ids
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
2. Select exactly THREE key achievements from key_achievements. Select the
   three most relevant to the job description. Do not invent or combine separate
   achievements. For each selected achievement, return its original paragraph
   ID, the exact employer/company name supported by the experience section,
   and a concise what_i_did statement. The final format will be
   "Company: What I did". Use a company name from company_candidates, or an
   employer name explicitly present in the experience text. Never use a job
   title as the company name. Preserve the achievement's factual meaning.
3. Edit the supplied editable paragraphs and project description paragraphs.
   Use keep, rewrite or remove. Rewrite only when it improves relevance or
   clarity.
4. For EVERY bullet under the EXPERIENCE section, retain the point. You may
   keep it unchanged or rewrite it, and you may use a mixture of unchanged and
   rewritten bullets across both jobs. Do not remove any experience bullet.
   Keep each bullet's original responsibility, scope and factual meaning.
5. Preserve technical detail and all numeric claims. Never add new numbers,
   dates, percentages, quantities, employers, tools, responsibilities or outcomes.
6. Never invent a skill merely because it appears in the job description.
7. Do not create section names, headings, job titles, employer names or dates.
8. Do not merge paragraphs. Do not return decisions for paragraph IDs not supplied.

Return one JSON object with exactly these keys:
{
  "professional_summary": "string",
  "selected_project_ids": ["P1", "P2", "P3"],
  "selected_achievements": [
    {
      "source_paragraph_id": "P4",
      "company": "Exact employer name",
      "what_i_did": "Factual achievement statement"
    }
  ],
  "paragraph_decisions": [
    {
      "source_paragraph_ids": ["P5"],
      "action": "keep",
      "rewritten_text": null,
      "matched_requirements": ["R001"]
    }
  ],
  "changes_summary": ["short explanation"]
}

Return exactly three selected_achievements with three distinct source paragraph IDs.
Every editable paragraph ID supplied must have exactly one decision.
Every project description paragraph supplied must have exactly one decision.
Use one source paragraph ID per decision. Do not return section_name.
For keep and remove, rewritten_text must be null. For rewrite, provide text.
For experience bullets, use only keep or rewrite.
Do not add markdown or text outside the JSON object.
""".strip()

    user_payload = {
        "job_requirements": context["job_requirements"],
        "original_profile": profile_text,
        "company_candidates": company_candidates,
        "experience_text": experience_text,
        "experience_paragraphs": experience_paragraphs,
        "key_achievements": achievement_payload,
        "editable_paragraphs": editable_payload,
        "project_groups": project_payload,
        "project_description_paragraphs": project_content_payload,
    }

    import json

    response = generate_response(
        system_prompt=system_prompt,
        user_prompt=json.dumps(user_payload, ensure_ascii=False),
    )

    if not isinstance(response, dict):
        raise ValueError("The resume editor returned an invalid response.")

    valid_project_ids = {
        item["title_id"]
        for item in projects
    }

    selected_projects = response.get("selected_project_ids")

    if (
        not isinstance(selected_projects, list)
        or len(selected_projects) != 3
        or len(set(selected_projects)) != 3
        or not set(selected_projects).issubset(valid_project_ids)
    ):
        selected_projects = _fallback_project_selection(
            projects,
            paragraph_lookup,
        )

    if len(selected_projects) != 3:
        raise ValueError("Could not select exactly three projects.")

    selected_achievements = _normalise_achievements(
        response.get("selected_achievements"),
        achievement_ids,
        paragraph_lookup,
        company_candidates,
        experience_text,
    )

    if len(selected_achievements) != 3:
        selected_achievements = _fallback_achievements(
            achievement_ids,
            paragraph_lookup,
            company_candidates,
            experience_text,
        )

    if len(selected_achievements) != 3:
        raise ValueError(
            "The AI could not select and format exactly three achievements "
            "with employer names supported by the uploaded resume."
        )

    summary = response.get("professional_summary")

    if not isinstance(summary, str) or not summary.strip():
        summary = profile_text
    else:
        summary = re.sub(r"\s+", " ", summary).strip()
        all_source_text = " ".join(
            item["text"]
            for item in paragraphs
        )

        if _numbers(summary) - _numbers(all_source_text):
            summary = profile_text

        if re.search(
            r"\b\d+\+?\s+years?\s+(?:of\s+)?experience\b",
            summary,
            re.I,
        ):
            if not re.search(
                r"\b\d+\+?\s+years?\s+(?:of\s+)?experience\b",
                all_source_text,
                re.I,
            ):
                summary = profile_text

        if len(summary.split()) > 65:
            summary = profile_text

    model_decisions = _normalise_model_decisions(
        response.get("paragraph_decisions"),
        records,
        paragraph_lookup,
        context["job_requirements"],
        experience_ids,
    )

    achievement_lookup = {
        item["source_paragraph_id"]: item["text"]
        for item in selected_achievements
    }

    for paragraph_id in achievement_ids:
        if paragraph_id in achievement_lookup:
            achievement_text = achievement_lookup[paragraph_id]
            original_text = paragraph_lookup[paragraph_id]["text"]

            model_decisions[paragraph_id] = {
                "source_paragraph_ids": [paragraph_id],
                "action": (
                    "keep"
                    if comparison_text(achievement_text) == comparison_text(original_text)
                    else "rewrite"
                ),
                "section_name": "HIGHLIGHTS",
                "rewritten_text": (
                    None
                    if comparison_text(achievement_text) == comparison_text(original_text)
                    else achievement_text
                ),
                "matched_requirements": [
                    match["requirement_id"]
                    for match in paragraph_lookup[paragraph_id]["matched_requirements"]
                    if "requirement_id" in match
                ],
            }
        else:
            model_decisions[paragraph_id] = {
                "source_paragraph_ids": [paragraph_id],
                "action": "remove",
                "section_name": "HIGHLIGHTS",
                "rewritten_text": None,
                "matched_requirements": [],
            }

    decisions = []

    for item in records:
        paragraph_id = item["id"]

        if paragraph_id in header_ids or paragraph_id == profile_id:
            continue

        if paragraph_id in model_decisions and (
            paragraph_id in editable_ids
            or item["role"] == "project_content"
            or paragraph_id in achievement_id_set
        ):
            decisions.append(model_decisions[paragraph_id])
        else:
            decisions.append({
                "source_paragraph_ids": [paragraph_id],
                "action": "keep",
                "section_name": item["section"],
                "rewritten_text": None,
                "matched_requirements": [
                    match["requirement_id"]
                    for match in paragraph_lookup[paragraph_id]["matched_requirements"]
                    if "requirement_id" in match
                ],
            })

    expected_ids = {
        item["id"]
        for item in records
        if item["id"] not in header_ids and item["id"] != profile_id
    }

    returned_ids = [
        paragraph_id
        for decision in decisions
        for paragraph_id in decision["source_paragraph_ids"]
    ]

    if (
        len(returned_ids) != len(set(returned_ids))
        or set(returned_ids) != expected_ids
    ):
        raise ValueError("Internal resume decision validation failed.")

    changes = response.get("changes_summary", [])

    if not isinstance(changes, list):
        changes = []

    changes = [
        str(item).strip()
        for item in changes
        if str(item).strip()
    ][:8]

    logger.info(
        "Resume tailoring complete. resume_id=%s source_paragraphs=%s "
        "selected_projects=%s selected_achievements=%s experience_bullets=%s",
        resume_id,
        len(paragraphs),
        len(selected_projects),
        len(selected_achievements),
        len(experience_ids),
    )

    return {
        "professional_summary": summary,
        "selected_project_ids": selected_projects,
        "selected_achievement_ids": [
            item["source_paragraph_id"]
            for item in selected_achievements
        ],
        "paragraph_decisions": decisions,
        "changes_summary": changes,
    }