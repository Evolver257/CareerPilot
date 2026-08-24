from io import BytesIO

from docx import Document
from httpx import AsyncClient
from reportlab.pdfgen import canvas

from app.services.resume_parsing import ResumeFileParser


def _docx_bytes() -> bytes:
    document = Document()
    document.add_heading("Resume", level=1)
    document.add_paragraph("Skills")
    document.add_paragraph("Python, FastAPI, RAG")
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _pdf_bytes() -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(72, 720, "AI Agent Engineer - Python RAG")
    pdf.save()
    return output.getvalue()


def test_pdf_and_docx_parsers_extract_text() -> None:
    parser = ResumeFileParser()

    pdf = parser.parse(filename="resume.pdf", content_type="application/pdf", data=_pdf_bytes())
    docx = parser.parse(
        filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=_docx_bytes(),
    )

    assert "AI Agent Engineer" in pdf.raw_text
    assert "Python, FastAPI, RAG" in docx.raw_text


async def test_resume_upload_parse_and_chunk_endpoints(client: AsyncClient) -> None:
    resume_text = """Alex Chen

Summary
AI Agent Engineer with Python, RAG, and FastAPI experience.

Projects
CareerPilot - built a resume intelligence service with PostgreSQL and Docker.

Skills
Python, FastAPI, RAG, PostgreSQL, Docker
"""
    response = await client.post(
        "/api/resumes",
        files={"file": ("alex_resume.txt", resume_text.encode("utf-8"), "text/plain")},
        data={"name": "Alex Resume"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Alex Resume"
    assert payload["raw_text"].startswith("Alex Chen")
    assert "Python" in payload["structured_profile"]["skills"]
    assert payload["chunk_count"] >= 2

    resume_id = payload["id"]
    chunks = await client.get(f"/api/resumes/{resume_id}/chunks")
    assert chunks.status_code == 200
    assert chunks.json()[0]["embedding_dimensions"] == 384

    parsed = await client.post(f"/api/resumes/{resume_id}/parse")
    assert parsed.status_code == 200
    assert parsed.json()["chunk_count"] == payload["chunk_count"]

    listed = await client.get("/api/resumes")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
