from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MockJobSeed:
    external_job_id: str
    title: str
    location: str
    description: str


_ROLE_TEMPLATES = (
    ("Backend Engineer", "Python, FastAPI, PostgreSQL, Redis, Docker", "Backend Engineering"),
    ("Frontend Engineer", "TypeScript, React, Next.js, CSS, Git", "Frontend Engineering"),
    ("Data Engineer", "Python, SQL, Spark, Airflow, PostgreSQL", "Data Engineering"),
    (
        "Machine Learning Engineer",
        "Python, Machine Learning, PyTorch, SQL, Docker",
        "Machine Learning",
    ),
    ("DevOps Engineer", "Linux, Docker, Kubernetes, AWS, Terraform", "DevOps / Platform"),
    ("Product Manager", "Product Management, SQL, Analytics, Figma", "Product"),
    ("QA Automation Engineer", "Python, Java, 自动化测试, Docker, Git", "Quality Engineering"),
    ("Mobile Engineer", "JavaScript, TypeScript, React, Git", "Mobile Engineering"),
    ("Security Engineer", "Python, Linux, AWS, Kubernetes, SQL", "Security"),
    ("Product Designer", "Figma, Product Management, User Research", "Design"),
)

_LOCATIONS = ("Remote", "Shanghai", "Shenzhen")


def build_mock_jobs() -> list[MockJobSeed]:
    seeds: list[MockJobSeed] = []
    index = 1
    for role, skills, category in _ROLE_TEMPLATES:
        for location in _LOCATIONS:
            seniority = "Senior" if location == "Remote" else "Mid-level"
            title = f"{seniority} {role}"
            description = f"""{title} — {category}

Location: {location}
Salary: 15k-30k CNY

Responsibilities
- Build reliable products and services for our users.
- Collaborate with engineering, product, and design partners.
- Improve quality, observability, and delivery speed.

Requirements
- Bachelor's degree or equivalent practical experience.
- 3+ years of relevant professional experience.
- Strong experience with {skills}.

Preferred Qualifications
- Experience working on a distributed team.
- Familiarity with AI-assisted development and data-informed decisions.
"""
            seeds.append(MockJobSeed(f"mock-{index:03d}", title, location, description))
            index += 1
    return seeds


MOCK_JOB_DATASET = build_mock_jobs()
