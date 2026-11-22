"""Professional decks. A template, when she uploads one, sets the page size."""

import io
import math
from typing import Any

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

INK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x4B, 0x55, 0x63)
RULE = RGBColor(0x1D, 0x4E, 0x89)
PAPER = RGBColor(0xF8, 0xFA, 0xFC)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def fit_font(
    text: str, width_in: float, height_in: float, max_pt: int = 28, min_pt: int = 14
) -> int:
    """Largest size that keeps the text inside the box."""
    body = text or " "
    for size in range(max_pt, min_pt - 1, -1):
        chars = max(8, int(width_in * 72 / (size * 0.5)))
        lines = 0
        for paragraph in body.split("\n"):
            lines += max(1, math.ceil(len(paragraph) / chars)) if paragraph else 1
        if lines * size * 1.2 <= height_in * 72:
            return size
    return min_pt


def text_fits(text: str, width_emu: int, height_emu: int, font_pt: int) -> bool:
    width_in = width_emu / 914400
    height_in = height_emu / 914400
    chars = max(8, int(width_in * 72 / (font_pt * 0.5)))
    lines = 0
    for paragraph in (text or "").split("\n"):
        lines += max(1, math.ceil(len(paragraph) / chars)) if paragraph else 1
    return lines * font_pt * 1.2 <= height_in * 72 + 1


def _bullet_text(bullet: Any) -> str:
    if isinstance(bullet, dict):
        return str(bullet.get("text") or "")
    return str(bullet)


def _notes(slide: dict, fallback: str) -> str:
    notes = slide.get("notes") or fallback
    citations = slide.get("citations") or []
    if citations:
        notes = f"{notes}\nSources: {', '.join(citations)}"
    return notes[:1200]


def deck_plan(title: str, content: list[dict]) -> list[dict]:
    """Turn cited content into a full deck: title, agenda, body, summary, references."""
    kept = [slide for slide in content if not slide.get("gap")]
    titles = [slide.get("title") or "Idea" for slide in kept] or ["Course notes"]
    citations: list[str] = []
    for slide in kept:
        for bullet in slide.get("bullets") or []:
            if isinstance(bullet, dict):
                name = (bullet.get("citation") or {}).get("filename")
                if name and name not in citations:
                    citations.append(name)
        for name in slide.get("citations") or []:
            if name not in citations:
                citations.append(name)
    plan = [
        {
            "layout": "title",
            "title": title or "Course deck",
            "bullets": ["Draft for the professor. Nothing here is published."],
            "notes": "Title slide. Say what the hour is for, then the first objective.",
            "citations": citations,
        },
        {
            "layout": "agenda",
            "title": "Agenda",
            "bullets": titles[:8],
            "notes": "Read the agenda, then ask which objective she wants first.",
            "citations": citations,
        },
    ]
    for slide in kept:
        bullets = [_bullet_text(item) for item in (slide.get("bullets") or [])]
        plan.append(
            {
                "layout": "section",
                "title": slide.get("title") or "Section",
                "bullets": [],
                "notes": _notes(slide, "Section divider."),
                "citations": citations,
            }
        )
        layout = "two" if len(bullets) >= 2 else "content"
        plan.append(
            {
                "layout": layout,
                "title": slide.get("title") or "Notes",
                "bullets": bullets or ["See the course note."],
                "notes": _notes(slide, "Content slide."),
                "citations": citations,
            }
        )
        numbers = [item for item in bullets if any(char.isdigit() for char in item)]
        if numbers:
            plan.append(
                {
                    "layout": "chart",
                    "title": "From the notes",
                    "bullets": numbers[:4],
                    "notes": "Only numbers that appear in the uploaded notes.",
                    "citations": citations,
                }
            )
        if bullets:
            plan.append(
                {
                    "layout": "quote",
                    "title": "From the source",
                    "bullets": [bullets[0]],
                    "notes": _notes(slide, "Read the quotation, then the citation."),
                    "citations": citations,
                }
            )
    plan.append(
        {
            "layout": "summary",
            "title": "Key takeaways",
            "bullets": titles[:5],
            "notes": "Close on the takeaways. Do not add a claim that was not in the notes.",
            "citations": citations,
        }
    )
    plan.append(
        {
            "layout": "references",
            "title": "References",
            "bullets": citations or ["Course notes"],
            "notes": "Every citation used in this deck.",
            "citations": citations or ["Course notes"],
        }
    )
    return plan


def _fit_box(
    slide, left, top, width, height, text: str, max_pt: int, color=INK, bold: bool = False
):
    size = fit_font(text, width / 914400, height / 914400, max_pt=max_pt, min_pt=14)
    return _box(slide, left, top, width, height, text, size, color, bold)


def _image_placeholder(slide, left, top, width, height):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = PAPER
    frame = shape.text_frame
    frame.word_wrap = True
    paragraph = frame.paragraphs[0]
    paragraph.text = "Image"
    paragraph.font.size = Pt(14)
    paragraph.font.color.rgb = MUTED
    paragraph.font.name = "Calibri"
    return shape


def _box(slide, left, top, width, height, text: str, size: int, color=INK, bold: bool = False):
    shape = slide.shapes.add_textbox(left, top, width, height)
    frame = shape.text_frame
    frame.word_wrap = True
    frame.clear()
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    paragraph.font.size = Pt(size)
    paragraph.font.bold = bold
    paragraph.font.color.rgb = color
    paragraph.font.name = "Calibri"
    return shape


def _write_bullets(slide, left, top, width, height, lines: list[str], max_pt: int = 22):
    text = "\n".join(f"• {line}" for line in lines) or "• "
    size = fit_font(text, width / 914400, height / 914400, max_pt=max_pt, min_pt=14)
    return _box(slide, left, top, width, height, text, size)


def _footer(slide, number: int, total: int):
    _box(
        slide,
        Inches(11.6),
        Inches(7.05),
        Inches(1.4),
        Inches(0.32),
        f"{number} / {total}",
        12,
        MUTED,
    )


def _notes_on(slide, text: str):
    slide.notes_slide.notes_text_frame.text = text or "Speaker note."


def render_thumbnails(plan: list[dict]) -> list[str]:
    """Small pictures for the review screen. Returns PNG data-URL strings."""
    try:
        import base64

        from PIL import Image, ImageDraw
    except Exception:
        return []
    images = []
    for item in plan:
        image = Image.new("RGB", (640, 360), (248, 250, 252))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 12, 360), fill=(29, 78, 137))
        title = (item.get("title") or "")[:48]
        draw.text((28, 24), title, fill=(31, 41, 55))
        y = 70
        for line in (item.get("bullets") or [])[:5]:
            draw.text((28, y), f"• {str(line)[:70]}", fill=(75, 85, 99))
            y += 36
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        images.append("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode())
    return images


def _numbers(lines: list[str]) -> list[float]:
    found: list[float] = []
    for line in lines:
        for token in line.replace(",", " ").split():
            try:
                found.append(float(token))
            except ValueError:
                continue
    return found[:6]


def _open_presentation(template: bytes | None):
    from pptx import Presentation

    if not template:
        presentation = Presentation()
        presentation.slide_width = SLIDE_W
        presentation.slide_height = SLIDE_H
        return presentation
    try:
        presentation = Presentation(io.BytesIO(template))
        width, height = presentation.slide_width, presentation.slide_height
        while len(presentation.slides) > 0:
            relation = presentation.slides._sldIdLst[0]
            presentation.part.drop_rel(relation.rId)
            relation.getparent().remove(relation)
        presentation.slide_width = width
        presentation.slide_height = height
        return presentation
    except Exception:
        presentation = Presentation()
        presentation.slide_width = SLIDE_W
        presentation.slide_height = SLIDE_H
        return presentation


def build_pptx(title: str, slides: list[dict], template: bytes | None = None) -> bytes:
    presentation = _open_presentation(template)
    layouts = presentation.slide_layouts
    blank = layouts[6] if len(layouts) > 6 else layouts[0]
    plan = deck_plan(title, slides)
    total = len(plan)
    for index, item in enumerate(plan, start=1):
        page = presentation.slides.add_slide(blank)
        layout = item["layout"]
        if layout == "title":
            _fit_box(
                page,
                Inches(0.8),
                Inches(2.2),
                Inches(11),
                Inches(1.4),
                item["title"],
                40,
                bold=True,
            )
            _write_bullets(
                page, Inches(0.8), Inches(4.0), Inches(8.5), Inches(1.2), item["bullets"], 22
            )
            _image_placeholder(page, Inches(10.0), Inches(4.2), Inches(2.6), Inches(1.8))
        elif layout == "section":
            _fit_box(
                page,
                Inches(0.8),
                Inches(2.8),
                Inches(11),
                Inches(1.5),
                item["title"],
                36,
                RULE,
                True,
            )
        elif layout == "two":
            _fit_box(
                page,
                Inches(0.6),
                Inches(0.4),
                Inches(12),
                Inches(0.7),
                item["title"],
                28,
                bold=True,
            )
            half = max(1, math.ceil(len(item["bullets"]) / 2))
            _write_bullets(
                page, Inches(0.6), Inches(1.4), Inches(5.8), Inches(4.6), item["bullets"][:half]
            )
            _write_bullets(
                page, Inches(6.8), Inches(1.4), Inches(5.8), Inches(4.6), item["bullets"][half:]
            )
        elif layout == "quote":
            quote = item["bullets"][0]
            _fit_box(page, Inches(0.8), Inches(2.2), Inches(11.5), Inches(2.4), quote, 26, RULE)
        elif layout == "chart":
            _fit_box(
                page,
                Inches(0.6),
                Inches(0.35),
                Inches(12),
                Inches(0.6),
                item["title"],
                28,
                bold=True,
            )
            _chart_or_table(page, item["bullets"])
        elif layout == "references":
            _fit_box(
                page,
                Inches(0.6),
                Inches(0.4),
                Inches(12),
                Inches(0.7),
                item["title"],
                28,
                bold=True,
            )
            _write_bullets(
                page, Inches(0.6), Inches(1.4), Inches(12), Inches(5.2), item["bullets"], 20
            )
        else:
            _fit_box(
                page, Inches(0.6), Inches(0.4), Inches(8), Inches(0.8), item["title"], 28, bold=True
            )
            _write_bullets(
                page, Inches(0.6), Inches(1.4), Inches(8), Inches(5.0), item["bullets"], 20
            )
            _image_placeholder(page, Inches(9.0), Inches(1.6), Inches(3.6), Inches(3.2))
        _footer(page, index, total)
        _notes_on(page, _notes(item, item["title"]))
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()


def _chart_or_table(page, lines: list[str]) -> None:
    values = _numbers(lines)
    if len(values) >= 2:
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE

        data = CategoryChartData()
        data.categories = [f"Item {index}" for index in range(1, len(values) + 1)]
        data.add_series("From the notes", values)
        page.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.8), Inches(1.3), Inches(11), Inches(5.2), data
        )
        return
    rows = len(lines) + 1
    table = page.shapes.add_table(rows, 2, Inches(0.8), Inches(1.4), Inches(11), Inches(4.8)).table
    _cell(table.cell(0, 0), "From the note")
    _cell(table.cell(0, 1), "Detail")
    for row_index, line in enumerate(lines, start=1):
        _cell(table.cell(row_index, 0), f"Item {row_index}")
        _cell(table.cell(row_index, 1), line[:80])


def _cell(cell, text: str) -> None:
    cell.text = text
    for paragraph in cell.text_frame.paragraphs:
        paragraph.font.size = Pt(12)
        paragraph.font.name = "Calibri"
        paragraph.font.color.rgb = INK
