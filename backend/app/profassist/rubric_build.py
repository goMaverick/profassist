"""Manual rubrics, imports, and alignment checks. The professor approves the result."""

import io
import re
from typing import Any

VAGUE = (
    "good",
    "appropriate",
    "satisfactory",
    "etc",
    "some",
    "various",
    "nice",
    "well",
    "adequate",
)
LEVELS = ("beginning", "developing", "proficient", "advanced")


def vague_flags(criteria: list[dict[str, Any]]) -> list[str]:
    flags = []
    for criterion in criteria:
        name = criterion.get("name") or "Criterion"
        blob = (
            name + " " + " ".join(str(value) for value in (criterion.get("levels") or {}).values())
        )
        words = {word.strip(".,;:").lower() for word in blob.split()}
        hits = [word for word in VAGUE if word in words]
        if hits:
            flags.append(f"{name} uses vague wording: {', '.join(hits)}.")
        if len(criterion.get("levels") or {}) < 4:
            flags.append(f"{name} is missing one of the four levels.")
    return flags


def alignment(criteria: list[dict[str, Any]], clos: list[str]) -> dict[str, Any]:
    flags = list(vague_flags(criteria))
    covered = []
    for clo in clos:
        tokens = {word.lower() for word in re.findall(r"[A-Za-z]{5,}", clo)}
        blob = " ".join(
            (item.get("name") or "") + " " + " ".join((item.get("levels") or {}).values())
            for item in criteria
        ).lower()
        if tokens and any(token in blob for token in tokens):
            covered.append(clo)
        elif clo:
            flags.append(f"No criterion mentions this outcome: {clo[:120]}")
    return {"flags": flags, "covered": covered, "clos": clos}


def parse_rubric_text(text: str) -> list[dict[str, Any]]:
    """Read a pasted or extracted rubric. Blank lines separate criteria."""
    blocks = re.split(r"\n\s*\n", text.strip())
    criteria = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        name = ""
        weight = 1
        levels: dict[str, str] = {}
        for line in lines:
            label, _, rest = line.partition(":")
            key = label.strip().lower()
            if key in {"criterion", "name", "criteria"}:
                name = rest.strip() or name
            elif key == "weight":
                digits = re.findall(r"\d+", rest)
                weight = int(digits[0]) if digits else 1
            elif key in LEVELS:
                levels[key] = rest.strip()
        if not name:
            name = lines[0][:80]
        if levels:
            criteria.append({"name": name, "weight": weight, "levels": levels})
    return criteria


def parse_rubric_file(filename: str, data: bytes) -> list[dict[str, Any]]:
    from app.profassist.storage import extract_text

    lower = filename.lower()
    if lower.endswith(".xlsx"):
        return _parse_xlsx(data)
    text = extract_text(filename, data)
    return parse_rubric_text(text)


def _parse_xlsx(data: bytes) -> list[dict[str, Any]]:
    import zipfile
    from xml.etree import ElementTree

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(node.text or "" for node in item.iter(f"{{{ns['m']}}}t")))
        sheet_name = "xl/worksheets/sheet1.xml"
        if sheet_name not in archive.namelist():
            return []
        root = ElementTree.fromstring(archive.read(sheet_name))
    rows = []
    for row in root.findall("m:sheetData/m:row", ns):
        values = []
        for cell in row.findall("m:c", ns):
            kind = cell.attrib.get("t")
            node = cell.find("m:v", ns)
            raw = node.text if node is not None and node.text else ""
            if kind == "s" and raw.isdigit():
                values.append(shared[int(raw)])
            else:
                values.append(raw)
        if any(values):
            rows.append(values)
    if not rows:
        return []
    header = [item.lower() for item in rows[0]]
    criteria = []
    for values in rows[1:]:
        record = {header[index]: values[index] for index in range(min(len(header), len(values)))}
        name = record.get("criterion") or record.get("name") or ""
        if not name:
            continue
        levels = {level: record.get(level, "") for level in LEVELS if record.get(level)}
        weight_text = record.get("weight") or "1"
        digits = re.findall(r"\d+", weight_text)
        criteria.append({"name": name, "weight": int(digits[0]) if digits else 1, "levels": levels})
    return criteria
