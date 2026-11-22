"""PDF and Word submissions for the integrity drill-down.

Files are stored in MinIO when it is configured. A Word file is converted to PDF
for viewing. Similarity uses the extracted sentences and keeps the page and box
for each match. Text is scrubbed before any model call.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import fitz

from app.core.config import settings
from app.profassist.pii import assert_prompt_is_clean, scrub
from app.profassist.storage import save_bytes

_LIBRARY: dict[str, Any] | None = None

EXTRAS: list[dict[str, Any]] = [
    {
        "id": "m8",
        "percent": 96,
        "source": "shared",
        "page": 1,
        "text": "Peak arrivals cluster in the twenty minutes after the 2pm workshop.",
    },
    {
        "id": "m9",
        "percent": 90,
        "source": "shared",
        "page": 2,
        "text": "The Thursday door count is the one we would repeat before changing the timetable.",
    },
    {
        "id": "m10",
        "percent": 86,
        "source": "shared",
        "page": 2,
        "text": "Level two is the only floor where the meter and the door count agree.",
    },
    {
        "id": "m11",
        "percent": 84,
        "source": "shared",
        "page": 3,
        "text": "A pilot should start on the floor we could read clearly.",
    },
    {
        "id": "m12",
        "percent": 81,
        "source": "shared",
        "page": 3,
        "text": "The meter on level two reads 42.7 during the Thursday class change.",
    },
    {
        "id": "m13",
        "percent": 70,
        "source": "readings",
        "page": 3,
        "text": "The reading notes that operational data should be tied to a decision, not only a chart.",
    },
]

OPENERS = {
    "A": "We watched the Knowledge Hub doors across four teaching weeks and counted entries in ten-minute blocks. The tally stayed in the group notebook.",
    "B": "We started from the published timetable and then stood at the same doors the following week. Two of us counted while the third kept the clock.",
    "C": "Our count covered the east stair, because that is the route from the afternoon labs. We checked the totals together each evening.",
    "D": "We measured queue time at the print desk rather than the door. The sheet names the hour, not the student.",
    "E": "The group split the building by floor and compared the sheets before writing this up.",
    "F": "We followed one workshop room for three weeks and noted when the booking and the actual use disagreed.",
}

TABLES = {
    "A": [("Mon", "42", "18.2"), ("Thu", "71", "42.7"), ("Fri", "36", "16.4")],
    "B": [("Mon", "39", "17.8"), ("Thu", "74", "42.7"), ("Fri", "33", "15.9")],
    "C": [("Mon", "28", "11.4"), ("Thu", "46", "22.0"), ("Fri", "31", "14.2")],
    "D": [("Mon", "18", "9.1"), ("Thu", "27", "13.6"), ("Fri", "16", "8.4")],
    "E": [("Mon", "22", "12.0"), ("Thu", "40", "21.5"), ("Fri", "19", "10.8")],
    "F": [("Mon", "15", "8.0"), ("Thu", "21", "11.2"), ("Fri", "14", "7.6")],
}


def gate_for_model(text: str) -> str:
    """Scrub personal data, then refuse the call if an email or ID remains."""
    cleaned = scrub(text or "").text
    assert_prompt_is_clean(cleaned)
    return cleaned


def _decisions_path() -> Path:
    path = Path(settings.MEDIA_DIR) / "profassist" / "integrity-decisions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_decisions() -> dict[str, dict[str, str]]:
    path = _decisions_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_decision(pair_id: str, match_id: str, action: str) -> dict[str, str]:
    data = load_decisions()
    pair = dict(data.get(pair_id) or {})
    pair[match_id] = action
    data[pair_id] = pair
    _decisions_path().write_text(json.dumps(data))
    return pair


def _source(passage: dict[str, Any]) -> str:
    text = str(passage.get("left") or "").lower()
    if passage.get("common") and "reading" in text:
        return "readings"
    if passage.get("common"):
        return "brief"
    return "shared"


def _targets(
    course: dict[str, Any], assignment: dict[str, Any], group: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pair in assignment["pairs"]:
        if group not in {pair["left"], pair["right"]}:
            continue
        side = "left" if pair["left"] == group else "right"
        for passage in pair["passages"]:
            key = str(passage["id"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "id": key,
                    "text": str(passage.get(side) or passage.get("left") or ""),
                    "percent": int(passage["percent"]),
                    "source": _source(passage),
                    "page": 1 if passage.get("common") else 2,
                }
            )
    if course["slug"] == "MAAI903" and str(assignment["number"]) == "1" and group in {"A", "B"}:
        for extra in EXTRAS:
            if extra["id"] in seen:
                continue
            seen.add(extra["id"])
            rows.append(dict(extra))
    return rows


def _blocks(title: str, group: str, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pages: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    pages[1].extend(
        [
            {"kind": "heading", "text": f"Group {group} - {title}"},
            {
                "kind": "body",
                "text": OPENERS.get(
                    group, "We measured one campus process and kept our own notes."
                ),
            },
            {
                "kind": "body",
                "text": "The rooms in this report are the ones booked for the afternoon workshop. We did not borrow a figure from another group.",
            },
        ]
    )
    pages[2].extend(
        [
            {"kind": "heading", "text": "What we counted"},
            {"kind": "table", "rows": TABLES.get(group, TABLES["A"])},
            {"kind": "caption", "text": "Figure 1. Afternoon entries counted by the group."},
        ]
    )
    pages[3].extend(
        [
            {"kind": "heading", "text": "What we would change"},
            {
                "kind": "body",
                "text": "The recommendation is a draft for the tutor. We would repeat the count for one more week before asking for a room change.",
            },
        ]
    )
    for target in targets:
        pages[int(target["page"])].append({"kind": "body", "text": target["text"]})
    blocks: list[dict[str, Any]] = []
    for number in (1, 2, 3):
        if number > 1:
            blocks.append({"kind": "break"})
        blocks.extend(pages[number])
    return blocks


def _wrap_height(text: str, size: int) -> float:
    chars = 62 if size < 14 else 48
    lines = 0
    for para in text.split("\n") or [""]:
        lines += max(1, math.ceil(len(para) / chars))
    return lines * (size + 4) + 8


def _write_text(
    doc: fitz.Document, page: fitz.Page, y: float, text: str, size: int
) -> tuple[fitz.Page, float]:
    height = _wrap_height(text, size)
    if y + height > 800:
        page = doc.new_page(width=595, height=842)
        y = 64
    rect = fitz.Rect(68, y, 527, y + height + 12)
    unused = page.insert_textbox(rect, text, fontsize=size, fontname="helv")
    used = height if unused < 0 else min(height, (height + 12) - unused)
    return page, y + max(used, size + 6) + 8


def _draw_table(page: fitz.Page, y: float, rows: list[tuple[str, str, str]]) -> float:
    columns = [68, 200, 340, 527]
    headers = ("Day", "Entries", "Meter")
    row_h = 18
    for index, row in enumerate([headers, *rows]):
        top = y + index * row_h
        for column, value in enumerate(row):
            rect = fitz.Rect(columns[column], top, columns[column + 1], top + row_h)
            page.draw_rect(rect, color=(0.75, 0.75, 0.75), width=0.6)
            page.insert_text((columns[column] + 4, top + 13), value, fontsize=10, fontname="helv")
    return y + (len(rows) + 1) * row_h + 8


def render_pdf(blocks: list[dict[str, Any]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 64.0
    for block in blocks:
        kind = block["kind"]
        if kind == "break":
            page = doc.new_page(width=595, height=842)
            y = 64
            continue
        if kind == "table":
            if y + 90 > 800:
                page = doc.new_page(width=595, height=842)
                y = 64
            y = _draw_table(page, y, block["rows"])
            continue
        size = 16 if kind == "heading" else 11
        if kind == "caption":
            size = 10
        page, y = _write_text(doc, page, y, block["text"], size)
    data = doc.tobytes()
    doc.close()
    return data


def render_docx(blocks: list[dict[str, Any]]) -> bytes:
    import io

    from docx import Document

    document = Document()
    for block in blocks:
        kind = block["kind"]
        if kind == "break":
            document.add_page_break()
        elif kind == "heading":
            document.add_heading(block["text"], level=1)
        elif kind == "caption":
            paragraph = document.add_paragraph(block["text"])
            paragraph.italic = True
        elif kind == "table":
            table = document.add_table(rows=1, cols=3)
            for cell, value in zip(table.rows[0].cells, ("Day", "Entries", "Meter"), strict=False):
                cell.text = value
            for row in block["rows"]:
                cells = table.add_row().cells
                for cell, value in zip(cells, row, strict=False):
                    cell.text = value
        else:
            document.add_paragraph(block["text"])
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _convert_docx(paths: list[Path]) -> dict[str, bytes]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice or not paths:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        copied = []
        for path in paths:
            target = out / path.name
            target.write_bytes(path.read_bytes())
            copied.append(str(target))
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, *copied],
            check=False,
            timeout=120,
            capture_output=True,
        )
        found = {}
        for path in paths:
            pdf = out / f"{path.stem}.pdf"
            if pdf.exists():
                found[path.stem] = pdf.read_bytes()
        return found


def _context_side(fragment: str) -> str:
    words = []
    for word in fragment.split():
        if any(ch.isdigit() for ch in word) or word.lower() in {
            "figure",
            "day",
            "entries",
            "meter",
        }:
            words = []
            continue
        words.append(word)
    return " ".join(words[-8:])


def _box(page: fitz.Page, rects: list[fitz.Rect]) -> dict[str, float]:
    x0 = min(rect.x0 for rect in rects)
    y0 = min(rect.y0 for rect in rects)
    x1 = max(rect.x1 for rect in rects)
    y1 = max(rect.y1 for rect in rects)
    width = page.rect.width or 1
    height = page.rect.height or 1
    return {
        "x": round(x0 / width, 4),
        "y": round(y0 / height, 4),
        "w": round((x1 - x0) / width, 4),
        "h": round(max(y1 - y0, 8) / height, 4),
    }


def _locate(pdf: bytes, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    document = fitz.open(stream=pdf, filetype="pdf")
    found = []
    for target in targets:
        needle = target["text"]
        for index, page in enumerate(document):
            rects = page.search_for(needle)
            if not rects:
                continue
            text = " ".join(page.get_text().split())
            at = text.find(needle)
            before = _context_side(text[max(0, at - 80) : at])
            after = _context_side(text[at + len(needle) : at + len(needle) + 80])
            context = " ".join(part for part in (before, needle, after) if part)
            found.append(
                {
                    "id": target["id"],
                    "text": needle,
                    "percent": int(target["percent"]),
                    "source": target["source"],
                    "page": index + 1,
                    "box": _box(page, rects),
                    "context": context,
                }
            )
            break
    document.close()
    return found


def _store(key: str, data: bytes, content_type: str) -> None:
    try:
        save_bytes(key, data, content_type)
    except Exception:
        return


def build_library() -> dict[str, Any]:
    from app.profassist.integrity_board import COURSES

    pending_docx: list[tuple[str, Path, list[dict[str, Any]]]] = []
    prepared: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for course in COURSES:
            for assignment in course["assignments"]:
                for group in assignment["groups"]:
                    targets = _targets(course, assignment, group)
                    blocks = _blocks(assignment["title"], group, targets)
                    origin = "docx" if group in {"B", "D", "F"} else "pdf"
                    key = f"{course['slug']}-{assignment['number']}-{group}"
                    if origin == "docx":
                        original = render_docx(blocks)
                        path = folder / f"{key}.docx"
                        path.write_bytes(original)
                        pending_docx.append((key, path, targets))
                        prepared.append(
                            {
                                "key": key,
                                "slug": course["slug"],
                                "number": str(assignment["number"]),
                                "group": group,
                                "origin": "docx",
                                "original": original,
                                "name": f"group-{group.lower()}.docx",
                                "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                "targets": targets,
                                "blocks": blocks,
                            }
                        )
                    else:
                        pdf = render_pdf(blocks)
                        prepared.append(
                            {
                                "key": key,
                                "slug": course["slug"],
                                "number": str(assignment["number"]),
                                "group": group,
                                "origin": "pdf",
                                "original": pdf,
                                "pdf": pdf,
                                "converter": "native",
                                "name": f"group-{group.lower()}.pdf",
                                "content_type": "application/pdf",
                                "targets": targets,
                                "blocks": blocks,
                            }
                        )
        converted = _convert_docx([path for _, path, _ in pending_docx])
        files = {}
        for item in prepared:
            pdf = item.get("pdf")
            converter = item.get("converter", "builtin")
            if item["origin"] == "docx":
                pdf = converted.get(item["key"])
                converter = "libreoffice" if pdf else "builtin"
                if pdf is None:
                    pdf = render_pdf(item["blocks"])
            sentences = _locate(pdf, item["targets"])
            # The model only sees scrubbed text. Matching stays on the extracted sentences.
            gate_for_model("\n".join(row["text"] for row in sentences))
            record = {
                "slug": item["slug"],
                "number": item["number"],
                "group": item["group"],
                "origin": item["origin"],
                "converter": converter,
                "pdf": pdf,
                "original": item["original"],
                "name": item["name"],
                "content_type": item["content_type"],
                "pages": _page_count(pdf),
                "sentences": sentences,
            }
            files[item["key"]] = record
            base = f"integrity/{item['slug']}/{item['number']}/{item['group']}"
            _store(f"{base}/{item['name']}", item["original"], item["content_type"])
            _store(f"{base}/view.pdf", pdf, "application/pdf")
    return {"files": files}


def _page_count(pdf: bytes) -> int:
    document = fitz.open(stream=pdf, filetype="pdf")
    count = document.page_count
    document.close()
    return count


def reset_library() -> None:
    """Drop the cached PDFs so a course registered later is included."""
    global _LIBRARY
    _LIBRARY = None


def library() -> dict[str, Any]:
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = build_library()
    return _LIBRARY


def _file(slug: str, number: str, group: str) -> dict[str, Any] | None:
    return library()["files"].get(f"{slug}-{number}-{group}")


def file_bytes(slug: str, number: str, group: str, which: str = "pdf") -> tuple[bytes, str, str]:
    row = _file(slug, number, group) or _file("MAAI903", "1", group) or _file("MAAI903", "1", "A")
    if row is None:
        pdf = render_pdf(
            [
                {"kind": "heading", "text": f"Group {group}"},
                {
                    "kind": "text",
                    "text": "The meter on level two reads 42.7 during the Thursday class change.",
                },
            ]
        )
        return pdf, "application/pdf", f"group-{group.lower()}.pdf"
    if which == "original":
        return row["original"], row["content_type"], row["name"]
    return row["pdf"], "application/pdf", f"group-{group.lower()}.pdf"


def locate_sentence(slug: str, number: str, group: str, text: str) -> dict[str, Any] | None:
    row = _file(slug, number, group)
    if row is None:
        return None
    for sentence in row["sentences"]:
        if sentence["text"] == text:
            return sentence
    document = fitz.open(stream=row["pdf"], filetype="pdf")
    for index, page in enumerate(document):
        rects = page.search_for(text)
        if rects:
            found = {"page": index + 1, "box": _box(page, rects), "text": text}
            document.close()
            return found
    document.close()
    return None


def pair_matches(slug: str, number: str, left: str, right: str) -> list[dict[str, Any]]:
    left_file = _file(slug, number, left)
    right_file = _file(slug, number, right)
    if left_file is None or right_file is None:
        return []
    right_by_id = {row["id"]: row for row in right_file["sentences"]}
    matches = []
    for sentence in left_file["sentences"]:
        other = right_by_id.get(sentence["id"])
        if other is None:
            continue
        label = {
            "shared": "Shared",
            "brief": "From the brief - not counted",
            "readings": "From readings - not counted",
        }
        matches.append(
            {
                "id": sentence["id"],
                "percent": int(sentence["percent"]),
                "source": sentence["source"],
                "tag": label.get(sentence["source"], "Shared"),
                "quote": sentence["text"],
                "context": sentence["context"],
                "page_left": sentence["page"],
                "page_right": other["page"],
                "left_box": sentence["box"],
                "right_box": other["box"],
            }
        )
    matches.sort(key=lambda row: row["percent"], reverse=True)
    return matches


def decision_status(matches: list[dict[str, Any]], decisions: dict[str, str]) -> str | None:
    shared = [row for row in matches if row["source"] == "shared"]
    if not shared:
        return None
    flagged = pending_high = pending_mid = 0
    for row in shared:
        decision = decisions.get(row["id"], "pending")
        if decision == "flag":
            flagged += 1
        elif decision == "ok":
            continue
        elif row["percent"] >= 75:
            pending_high += 1
        elif row["percent"] >= 40:
            pending_mid += 1
    if flagged or pending_high:
        return "Concern"
    if pending_mid:
        return "Review"
    return "Clear"


def summarise(matches: list[dict[str, Any]], decisions: dict[str, str]) -> dict[str, int]:
    flagged = ok = pending = 0
    for row in matches:
        decision = decisions.get(row["id"], "pending")
        if decision == "flag":
            flagged += 1
        elif decision == "ok":
            ok += 1
        else:
            pending += 1
    return {"flagged": flagged, "ok": ok, "pending": pending}


def document_side(slug: str, number: str, group: str) -> dict[str, Any]:
    row = _file(slug, number, group) or {}
    return {
        "group": group,
        "origin": row.get("origin", "pdf"),
        "converter": row.get("converter", ""),
        "pages": row.get("pages", 0),
        "view": f"/integrity/file?course={slug}&number={number}&group={group}&which=pdf",
        "original": f"/integrity/file?course={slug}&number={number}&group={group}&which=original",
        "filename": row.get("name", f"group-{group.lower()}.pdf"),
    }
