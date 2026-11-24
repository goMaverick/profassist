"""The assessment brief renders the same template in DOCX and PDF."""

from __future__ import annotations

import io

import pymupdf
from docx import Document

from app.profassist.assignment_doc import CLASS_FIELDS, render_docx, render_pdf

BODY = {
    "class_details": {
        "institution": "University of Wollongong in Dubai",
        "course": "MAAI903 AI Solutions Design & MLOps",
        "lecturer": "Dr Patrick Mukala",
        "assessment": "Assessment 2: Solutions Architecture Report",
        "weight": "25%",
        "report_length": "Maximum 2,500 words, with visualizations (diagrams, tables, "
        "screenshots, timelines)",
        "report_due": "Week 7",
        "presentation": "Week 7, 10 minutes presentation + 5 minutes questions",
        "submission": "Upload to the course Moodle page",
    },
    "overview": [
        "This assessment requires you to design an AI solution architecture for a realistic "
        "business or industry problem. You must document and justify your approach to data flow, "
        "model selection, orchestration of pipelines, deployment strategies, monitoring "
        "mechanisms, and tool choices.",
        "Your proposed solution must reflect real-world constraints and considerations such as "
        "scalability, reproducibility, latency, and compliance. You may choose a problem from the "
        "list in Section 2, or propose your own, subject to the lecturer's approval.",
    ],
    "problem_choices": [
        {
            "problem": "Streaming video recommender",
            "description": "Personalized home-page rows for millions of subscribers, with "
            "cold-start users and a catalogue that changes daily.",
        },
        {
            "problem": "Retail facial-recognition checkout",
            "description": "Identity verification at self-checkout under a strict "
            "per-transaction latency budget, with biometric privacy obligations.",
        },
        {
            "problem": "Bank fraud detection",
            "description": "Real-time scoring of card transactions inside an authorization "
            "window, with human review of borderline cases and evolving fraud patterns.",
        },
        {
            "problem": "Customer-support assistant",
            "description": "Conversational assistant over a company knowledge base, with "
            "escalation to humans and controls on incorrect or unsafe answers.",
        },
        {
            "problem": "Predictive maintenance",
            "description": "Failure prediction from industrial sensor streams, with edge "
            "constraints, intermittent connectivity, and safety-critical alerts.",
        },
    ],
    "deliverables": [
        {
            "title": "Technical report",
            "description": "A structured technical report of at most 2,500 words, including "
            "visualizations such as diagrams, tables, screenshots, and timelines. It must cover "
            "the eleven sections below, in this order.",
        },
        {
            "title": "Presentation deck",
            "description": "A presentation deck for the Week 7 session.",
        },
        {
            "title": "Live presentation",
            "description": "A 10-minute presentation plus 5 minutes of questions in Week 7.",
        },
    ],
    "report_sections": [
        {
            "number": "1",
            "section": "Executive Summary",
            "guidelines": "The problem, the proposed architecture, and the most important design "
            "decision, readable on its own by a non-technical executive.",
        },
        {
            "number": "2",
            "section": "Problem Definition & Business Context",
            "guidelines": "The industry context, who is affected, and measurable business impact: "
            "the target metric, the current baseline, and the intended improvement.",
        },
        {
            "number": "3",
            "section": "Solution Overview",
            "guidelines": "The end-to-end architecture, shown in a well-labelled architecture "
            "diagram, with each component and data flow explained and the main alternatives you "
            "rejected.",
        },
        {
            "number": "4",
            "section": "Data Strategy",
            "guidelines": "Sources, collection, quality checks, storage, labelling, versioning, "
            "and access controls; how data is kept consistent between training and serving.",
        },
        {
            "number": "5",
            "section": "AI Workflow Design (ML Pipeline)",
            "guidelines": "Pipeline stages from ingestion to model registry, how they are "
            "orchestrated, how experiments are tracked, and how runs are made reproducible.",
        },
        {
            "number": "6",
            "section": "Tool & Technology Stack",
            "guidelines": "The tools chosen, why they were chosen over named alternatives, and "
            "how they integrate; a table is a good fit.",
        },
        {
            "number": "7",
            "section": "Model Deployment & Scalability Strategy",
            "guidelines": "Serving pattern (batch, online, streaming, or edge), CI/CD for models, "
            "rollout and rollback, and how latency and throughput targets are met at scale.",
        },
        {
            "number": "8",
            "section": "Monitoring, Retraining & Maintenance",
            "guidelines": "What is monitored (system, data, model, business), drift detection, "
            "alert thresholds, retraining triggers, and who owns maintenance.",
        },
        {
            "number": "9",
            "section": "Ethical, Regulatory & Risk Considerations",
            "guidelines": "Fairness, explainability, privacy, and the specific legal frameworks "
            "that apply, with the main risks and how they are mitigated.",
        },
        {
            "number": "10",
            "section": "Conclusion & Recommendations",
            "guidelines": "What the design achieves, its main limitations, and a prioritized "
            "path to implementation.",
        },
        {
            "number": "11",
            "section": "References",
            "guidelines": "Every source cited in the text, in one consistent style.",
        },
    ],
}


def _docx() -> Document:
    return Document(io.BytesIO(render_docx(BODY)))


def test_docx_has_the_template_headings_and_tables() -> None:
    document = _docx()
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert "Assessment 2: Solutions Architecture Report" in text
    assert "1 Overview" in text
    assert "2 Choosing Your Problem" in text
    assert "3 Deliverables" in text
    assert "3.1 Technical report" in text
    for paragraph in BODY["overview"]:
        assert paragraph in text
    for item in BODY["deliverables"]:
        assert item["title"] in text

    assert len(document.tables) == 3

    details = document.tables[0]
    assert [cell.text for cell in details.rows[0].cells] == ["Field", "Value"]
    assert len(details.rows) == len(CLASS_FIELDS) + 1
    rows = {row.cells[0].text: row.cells[1].text for row in details.rows[1:]}
    assert rows["Institution"] == "University of Wollongong in Dubai"
    assert rows["Course"] == "MAAI903 AI Solutions Design & MLOps"
    assert rows["Lecturer"] == "Dr Patrick Mukala"
    assert rows["Assessment"] == "Assessment 2: Solutions Architecture Report"
    assert rows["Weight"] == "25%"
    assert rows["Report length"] == (
        "Maximum 2,500 words, with visualizations (diagrams, tables, screenshots, timelines)"
    )
    assert rows["Report due"] == "Week 7"
    assert rows["Presentation"] == "Week 7, 10 minutes presentation + 5 minutes questions"
    assert rows["Submission"] == "Upload to the course Moodle page"

    problems = document.tables[1]
    assert [cell.text for cell in problems.rows[0].cells] == ["Problem", "Description"]
    assert len(problems.rows) == len(BODY["problem_choices"]) + 1
    assert [row.cells[0].text for row in problems.rows[1:]] == [
        item["problem"] for item in BODY["problem_choices"]
    ]
    assert [row.cells[1].text for row in problems.rows[1:]] == [
        item["description"] for item in BODY["problem_choices"]
    ]

    sections = document.tables[2]
    assert [cell.text for cell in sections.rows[0].cells] == ["#", "Section", "Guidelines"]
    assert len(sections.rows) == len(BODY["report_sections"]) + 1
    assert [row.cells[0].text for row in sections.rows[1:]] == [str(i) for i in range(1, 12)]
    assert [row.cells[1].text for row in sections.rows[1:]] == [
        item["section"] for item in BODY["report_sections"]
    ]
    assert [row.cells[2].text for row in sections.rows[1:]] == [
        item["guidelines"] for item in BODY["report_sections"]
    ]


def test_pdf_is_readable_across_pages() -> None:
    data = render_pdf(BODY)
    assert data.startswith(b"%PDF")
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        assert document.page_count >= 2
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    finally:
        document.close()

    assert len(text) > 2000
    assert "Assessment 2: Solutions Architecture Report" in text
    assert "1 Overview" in text
    assert "2 Choosing Your Problem" in text
    assert "3 Deliverables" in text
    assert "3.1 Technical report" in text
    assert "Field" in text
    assert "Value" in text
    for paragraph in BODY["overview"]:
        assert paragraph in text
    for item in BODY["problem_choices"]:
        assert item["problem"] in text
        assert item["description"] in text
    for item in BODY["deliverables"]:
        assert item["title"] in text
    for item in BODY["report_sections"]:
        assert item["section"] in text
        assert item["guidelines"] in text


def test_unknown_fields_stay_empty_and_no_sections_are_invented() -> None:
    title = "Assessment 2: Solutions Architecture Report"
    body = {"class_details": {"assessment": title}}
    document = Document(io.BytesIO(render_docx(body)))

    assert len(document.tables) == 3
    assert len(document.tables[0].rows) == len(CLASS_FIELDS) + 1
    rows = {row.cells[0].text: row.cells[1].text for row in document.tables[0].rows[1:]}
    assert rows["Assessment"] == title
    for label, _key in CLASS_FIELDS:
        if label != "Assessment":
            assert rows[label] == ""
    assert len(document.tables[1].rows) == 1
    assert len(document.tables[2].rows) == 1

    headings = [
        p.text
        for p in document.paragraphs
        if p.style.name == "Title" or p.style.name.startswith("Heading")
    ]
    assert headings == [
        title,
        "1 Overview",
        "2 Choosing Your Problem",
        "3 Deliverables",
        "3.1 Technical report",
    ]

    pdf = pymupdf.open(stream=render_pdf(body), filetype="pdf")
    try:
        assert pdf.page_count >= 1
        text = " ".join(" ".join(page.get_text().split()) for page in pdf)
    finally:
        pdf.close()
    assert title in text
    assert "1 Overview" in text
    assert "2 Choosing Your Problem" in text
    assert "3 Deliverables" in text
    assert "3.1 Technical report" in text
