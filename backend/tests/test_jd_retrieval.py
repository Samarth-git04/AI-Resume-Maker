from backend.services.jd_retrieval import retrieve_for_job


RESUME_ID = 1

JOB_DESCRIPTION = """
Data Analyst

Required Skills:
- Strong Python and SQL skills are required.
- Experience with Power BI and Tableau.
- Knowledge of statistics and data analysis.

Preferred Skills:
- Familiarity with machine learning.
- Knowledge of AWS is desirable.

Responsibilities:
- Develop dashboards and reports.
- Analyse datasets to identify trends and insights.
- Build automated data pipelines.
- Communicate findings to stakeholders.

Required Qualifications:
- A Master's degree in Physics, Statistics, Mathematics or a related field.

Experience:
- Candidates should have 2 years of professional experience.
"""


def main():

    print("\n--- 1. Extracting requirements and retrieving paragraphs ---")

    results = retrieve_for_job(
        resume_id=RESUME_ID,
        job_description=JOB_DESCRIPTION
    )

    requirements = results["requirements"]
    paragraphs = results["unique_paragraphs"]

    print(f"\nRequirements: {len(requirements)}")
    print(f"Unique paragraphs: {len(paragraphs)}")

    for paragraph in paragraphs:

        print("\n" + "=" * 80)
        print(f"Paragraph ID: {paragraph['paragraph_id']}")
        print(f"Text: {paragraph['text']}")
        print("Matched requirements:")

        for match in paragraph["matched_requirements"]:
            print(
                f"  {match['requirement_id']} | "
                f"Rank: {match['rank']} | "
                f"Score: {match['score']:.4f}"
            )

    paragraph_ids = [
        paragraph["paragraph_id"]
        for paragraph in paragraphs
    ]

    assert len(paragraph_ids) == len(set(paragraph_ids))

    for requirement in requirements:
        if requirement["priority"] == "not_required":
            assert not requirement["retrieved_paragraph_ids"]

    print("\nAll retrieval and deduplication checks passed.")


if __name__ == "__main__":
    main()