"""Build a .pptx the professor can download. Nothing is sent anywhere."""

import io


def build_pptx(title: str, slides: list[dict]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    for slide in slides:
        layout = presentation.slide_layouts[1]
        page = presentation.slides.add_slide(layout)
        page.shapes.title.text = (slide.get("title") or title or "Draft")[:120]
        body = page.placeholders[1].text_frame
        body.clear()
        bullets = slide.get("bullets") or ["Draft bullet"]
        for index, bullet in enumerate(bullets):
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.text = str(bullet)[:500]
            paragraph.level = 0
            paragraph.font.size = Pt(18)
        notes = slide.get("notes")
        if notes:
            page.notes_slide.notes_text_frame.text = str(notes)[:1000]
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()
