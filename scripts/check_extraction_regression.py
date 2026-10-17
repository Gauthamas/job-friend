"""On-demand regression check for REQUIREMENT_EXTRACT (requirement_extract
prompt). Needs LM Studio running with the chat model loaded -- NOT part of
the default pytest suite, which is mock-only and needs no model server.

Checks COVERAGE, not exact output: at temperature 0, content and section
coverage are stable, but wording and the splitting of compound lines into
multiple requirements can vary between runs and prompt versions (see
README.md "Limits"). So each fixture checks that every
source line is represented somewhere in the output (by distinctive
keywords, not exact text), that the requirement count falls in an expected
range, and that no boilerplate leaked in -- never that the output matches
some saved text verbatim.

Any change to REQUIREMENT_EXTRACT's prompt must be re-run against this
script before being trusted.

Usage:
    python scripts/check_extraction_regression.py

Exits 1 if any fixture fails, printing exactly which source line(s) are
missing (by which keyword set didn't match) and why.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.llm.lmstudio_client import LMStudioClient  # noqa: E402
from app.llm.runner import run_task  # noqa: E402
from app.llm.tasks import REQUIREMENT_EXTRACT  # noqa: E402

# Phrases that would indicate boilerplate (benefits/about-us/EEO text)
# leaked into the extracted requirements -- none of these fixtures'
# source JDs contain any such text, so none should ever appear.
BOILERPLATE_MARKERS = [
    "health insurance", "paid time off", "401(k)", "401k", "dental", "vision plan", "vision coverage",
    "equal opportunity", "equal employment", "eeo", "disability status", "parental leave",
    "about us", "who we are", "our mission", "our culture", "our company",
    "benefits include", "salary range", "compensation package", "perks include",
    "remote-first", "founded", "reliable operational insights", "move the needle",
]

# All three JDs below are fictional, written to match the SHAPE of the real
# postings these fixtures were originally built from (same section layout,
# same count of lines, same kind of compound/headingless content) -- not
# copied from or resembling any real company's actual posting.
FIXTURES = [
    {
        "name": "fictional_backend_role_with_heading",
        # Shape: an unheaded intro block of responsibility bullets, then a
        # "Key Responsibilities" heading holding qualifications, then a
        # "Skills, Knowledge & Expertise" heading.
        "jd_text": """Design and build backend services for a multi-tenant SaaS platform using modern cloud-native technologies and best practices.
Build scalable, maintainable, and well-tested systems.
Collaborate with cross-functional teams to define and deliver new features.
Drive technical discussions and contribute to architectural decisions.
Review code and mentor other engineers.
Investigate and resolve performance, stability, and reliability issues.
Contribute to continuous improvement of engineering practices, tooling, and development processes.

Key Responsibilities

5+ years of professional backend development experience.
Strong knowledge of Go.
Experience with goroutines and asynchronous programming.
Strong understanding of service architectural patterns including microservices, event-driven design, and Clean Architecture.
Experience with container orchestration and modern deployment practices.
Hands-on experience with Kafka and/or similar message queue systems.
Experience working with multi-service distributed systems.
Experience with dependency injection frameworks.
Solid understanding of distributed systems design patterns and software engineering principles.
Experience working with REST and gRPC APIs.
Knowledge of testing practices and CI/CD workflows.
Experience with code reviews and collaborative software development.
Strong problem-solving and debugging skills.
Good communication skills and ability to work in an international environment.


Skills, Knowledge & Expertise

Experience with real-time data processing technologies.
Knowledge of encryption and data protection standards (TLS, AES, KMS).
Experience with live telemetry or event-streaming platforms.
Experience with service mesh or API gateway technologies.
Understanding of observability and monitoring solutions.
Experience with feature flag solutions (e.g. LaunchDarkly).
Experience working at scale with systems serving millions of requests.
Experience with concurrent and parallel processing frameworks.""",
        "min_count": 27,
        "max_count": 31,
        # The 5 lines from the unheaded intro block that were silently
        # dropped before the "headingless duty blocks" prompt fix -- each
        # entry is a list of distinctive keywords for that one source
        # line; at least one keyword from each list must appear somewhere
        # in the extracted requirements.
        "required_keywords": {
            "Collaborate with cross-functional teams to define and deliver new features.":
                ["cross-functional"],
            "Drive technical discussions and contribute to architectural decisions.":
                ["technical discussion", "architectural decision"],
            "Review code and mentor other engineers.":
                ["mentor"],
            "Investigate and resolve performance, stability, and reliability issues.":
                ["investigate", "reliability issue"],
            "Contribute to continuous improvement of engineering practices, tooling, and development processes.":
                ["continuous improvement", "tooling"],
        },
    },
    {
        "name": "fictional_data_role_headingless",
        # Shape: no section headings at all, 7 bullet lines.
        "jd_text": """What Success Will Look Like:
Build Northlight SDKs and libraries for embedded edge devices, including gateway and sensor hardware, following best practices and exposing easy-to-integrate APIs.
Collect sensor analytics data, capturing readings from field devices so they can be linked to real operational outcomes.
Collect network analytics data by instrumenting edge gateways and sync processes to capture quality, performance, and engagement signals.
Collect usage analytics data, capturing how operators interact with the fleet dashboard so customers can understand behavior, performance, and outcomes.
Build the alerting monitoring solution to support anomaly detection across distributed sensor fleets.
Take ownership of solutions end to end, and be responsible for translating functional requirements into a product solution or offering.
Functionally decompose complex problems into simple, straightforward solutions.""",
        "min_count": 8,
        "max_count": 13,
        # One entry per source bullet. A compound bullet may be split into
        # several requirements (fine -- that's the known splitting
        # variation) or kept as one; this only checks the bullet's content
        # survived somewhere in the output.
        "required_keywords": {
            "Build Northlight SDKs and libraries for embedded edge devices, including gateway and sensor hardware, following best practices and exposing easy-to-integrate APIs.":
                ["Northlight", "SDK"],
            "Collect sensor analytics data, capturing readings from field devices so they can be linked to real operational outcomes.":
                ["sensor analytics", "field device"],
            "Collect network analytics data by instrumenting edge gateways and sync processes to capture quality, performance, and engagement signals.":
                ["network analytics", "edge gateway", "sync process"],
            "Collect usage analytics data, capturing how operators interact with the fleet dashboard so customers can understand behavior, performance, and outcomes.":
                ["usage analytics", "operator behavior", "operator interact"],
            "Build the alerting monitoring solution to support anomaly detection across distributed sensor fleets.":
                ["alerting monitoring", "anomaly detection"],
            "Take ownership of solutions end to end, and be responsible for translating functional requirements into a product solution or offering.":
                ["ownership", "end to end", "end-to-end"],
            "Functionally decompose complex problems into simple, straightforward solutions.":
                ["decompose", "straightforward solution"],
        },
    },
    {
        "name": "fictional_data_role_with_company_and_benefits_paragraphs",
        # Same 7 bullets as fictional_data_role_headingless, with an
        # unheaded "about the company" paragraph prepended and an unheaded
        # benefits/EEO paragraph appended -- checks that neither
        # boilerplate paragraph gets mistaken for duty bullets now that
        # unheaded text is explicitly in scope (the "headingless duty
        # blocks" fix).
        "jd_text": """Northlight Analytics helps industrial operators turn raw sensor data into reliable operational insights at scale. Founded more than a decade ago, we're a remote-first team of roughly 400 people spread across 12 countries. We care about ownership, direct feedback, and shipping things that actually move the needle for our customers, and our platform now processes billions of sensor readings every month.

Build Northlight SDKs and libraries for embedded edge devices, including gateway and sensor hardware, following best practices and exposing easy-to-integrate APIs.
Collect sensor analytics data, capturing readings from field devices so they can be linked to real operational outcomes.
Collect network analytics data by instrumenting edge gateways and sync processes to capture quality, performance, and engagement signals.
Collect usage analytics data, capturing how operators interact with the fleet dashboard so customers can understand behavior, performance, and outcomes.
Build the alerting monitoring solution to support anomaly detection across distributed sensor fleets.
Take ownership of solutions end to end, and be responsible for translating functional requirements into a product solution or offering.
Functionally decompose complex problems into simple, straightforward solutions.

We offer a competitive salary, meaningful equity, and a comprehensive benefits package including health insurance, dental and vision coverage, and a 401(k) match. Employees also enjoy unlimited paid time off and a generous parental leave policy. Northlight Analytics is proud to be an equal opportunity employer and does not discriminate on the basis of race, color, religion, sex, national origin, age, or disability status.""",
        "min_count": 7,
        "max_count": 13,
        "required_keywords": {
            "Build Northlight SDKs and libraries for embedded edge devices, including gateway and sensor hardware, following best practices and exposing easy-to-integrate APIs.":
                ["Northlight", "SDK"],
            "Collect sensor analytics data, capturing readings from field devices so they can be linked to real operational outcomes.":
                ["sensor analytics", "field device"],
            "Collect network analytics data by instrumenting edge gateways and sync processes to capture quality, performance, and engagement signals.":
                ["network analytics", "edge gateway", "sync process"],
            "Collect usage analytics data, capturing how operators interact with the fleet dashboard so customers can understand behavior, performance, and outcomes.":
                ["usage analytics", "operator behavior", "operator interact"],
            "Build the alerting monitoring solution to support anomaly detection across distributed sensor fleets.":
                ["alerting monitoring", "anomaly detection"],
            "Take ownership of solutions end to end, and be responsible for translating functional requirements into a product solution or offering.":
                ["ownership", "end to end", "end-to-end"],
            "Functionally decompose complex problems into simple, straightforward solutions.":
                ["decompose", "straightforward solution"],
        },
    },
]


def check_fixture(fixture: dict, llm_client: LMStudioClient) -> bool:
    print(f"\n=== {fixture['name']} ===")
    outcome = run_task(llm_client, REQUIREMENT_EXTRACT, fixture["jd_text"])
    if outcome.status == "error":
        print(f"FAIL: extraction returned an error: {outcome.error}")
        return False

    requirements = outcome.data.requirements
    count = len(requirements)
    haystack = " || ".join(r.text.lower() for r in requirements)
    ok = True

    if fixture["min_count"] <= count <= fixture["max_count"]:
        print(f"OK: count {count} within [{fixture['min_count']}, {fixture['max_count']}]")
    else:
        print(f"FAIL: count {count} outside [{fixture['min_count']}, {fixture['max_count']}]")
        ok = False

    missing_lines = []
    for source_line, keywords in fixture["required_keywords"].items():
        if not any(kw.lower() in haystack for kw in keywords):
            missing_lines.append((source_line, keywords))
    if missing_lines:
        print(f"FAIL: {len(missing_lines)} source line(s) not represented in the output:")
        for source_line, keywords in missing_lines:
            print(f"  - {source_line!r} (tried keywords: {keywords})")
        ok = False
    else:
        print(f"OK: all {len(fixture['required_keywords'])} source lines represented")

    boilerplate_hits = [m for m in BOILERPLATE_MARKERS if m in haystack]
    if boilerplate_hits:
        print(f"FAIL: boilerplate-looking text found: {boilerplate_hits}")
        ok = False
    else:
        print("OK: no boilerplate markers found")

    print("\nExtracted requirements:")
    for r in requirements:
        print(f"  [{r.weight}] {r.text}")

    return ok


def main() -> None:
    llm_client = LMStudioClient(settings.lm_studio_base_url, settings.llm_model)
    results = [check_fixture(f, llm_client) for f in FIXTURES]

    print("\n=== Summary ===")
    for f, ok in zip(FIXTURES, results):
        print(f"{f['name']}: {'PASS' if ok else 'FAIL'}")

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
