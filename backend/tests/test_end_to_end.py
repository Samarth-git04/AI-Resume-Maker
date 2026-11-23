import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8000"

RESUME_PATH = "test_resume.docx"

JD = """
Junior Data Analyst

We are looking for a Junior Data Analyst proficient in Python,
SQL, Pandas, and Power BI.

Responsibilities:
- Analyse datasets using Python and SQL.
- Perform data cleaning and exploratory data analysis.
- Develop interactive Power BI dashboards.
- Identify business trends and communicate insights.

Requirements:
- Bachelor's degree in Computer Science or Statistics.
- Knowledge of Python, SQL, Pandas and data visualization.
- Understanding of statistical analysis.
- 0-2 years of experience.
"""

def check(response, stage):
    print(f"\n[{stage}] Status: {response.status_code}")

    if not response.ok:
        print(response.text)
        sys.exit(1)

    try:
        return response.json()
    except ValueError:
        print(response.text)
        sys.exit(1)


def main():

    print("STARTING END-TO-END TEST")

    # 1. Upload resume
    with open(RESUME_PATH, "rb") as file:
        response = requests.post(
            f"{BASE_URL}/resumes/upload",
            params={"replace": False},
            files={
                "file": (
                    "test_resume.docx",
                    file,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
            },
            timeout=120
        )

    upload_data = check(response, "RESUME UPLOAD")

    print(json.dumps(upload_data, indent=2))

    resume_id = upload_data.get("id") or upload_data.get("resume_id")

    if not resume_id:
        print("Could not identify resume ID.")
        sys.exit(1)

    # 2. Analyze resume against JD
    response = requests.post(
        f"{BASE_URL}/resumes/{resume_id}/analyze",
        json={"job_description": JD},
        timeout=300
    )

    analysis_data = check(response, "RESUME ANALYSIS")

    print("\nANALYSIS RESULT:")
    print(json.dumps(analysis_data, indent=2))

    print("\nEND-TO-END TEST COMPLETED SUCCESSFULLY")


if __name__ == "__main__":
    main()