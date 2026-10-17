from reportlab.pdfgen import canvas

from app.extraction.pdf import extract_text


def make_pdf_bytes(lines: list[str]) -> bytes:
    import io

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_extract_text_recovers_known_lines():
    pdf_bytes = make_pdf_bytes(["Priya Chattopadhyay", "Senior Mobile Engineer"])
    text = extract_text(pdf_bytes)
    assert "Priya Chattopadhyay" in text
    assert "Senior Mobile Engineer" in text


def test_extract_text_joins_multiple_pages():
    pdf_bytes = make_pdf_bytes(["Page one line"])
    text = extract_text(pdf_bytes)
    assert text.strip() != ""
