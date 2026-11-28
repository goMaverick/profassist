"""Convert professor-reviewed text pairs to the private snapshot contract."""

import csv
import hashlib
import io

COLUMNS = ("text_a", "text_b", "review_label", "shared_passage")
EXCERPTS = ("shared_passage_a", "shared_passage_b")
MAX_BYTES = 1024 * 1024


def _offset(text: str, quote: str, row: int, side: str) -> int:
    start = text.find(quote)
    if start < 0 or text.find(quote, start + 1) >= 0:
        raise ValueError(f"Row {row}: the shared passage must occur exactly once in text {side}.")
    return start


def parse_text_pairs(raw: bytes) -> tuple[list[dict], list[dict]]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Upload a UTF-8 CSV no larger than 1 MiB.")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    header = tuple(next(reader, ()))
    if header not in {COLUMNS, COLUMNS + EXCERPTS}:
        raise ValueError("Use the headers in the text-pair sample CSV.")
    reports, reviews, seen = {}, [], set()
    for row in reader:
        line = reader.line_num
        if len(row) != len(header) or len(reviews) >= 500:
            raise ValueError(f"Row {line}: use the sample columns and no more than 500 pairs.")
        left, right, label, common, *excerpts = row
        label = label.strip().lower()
        if (
            not left.strip()
            or not right.strip()
            or label not in {"shared wording", "no shared wording"}
        ):
            raise ValueError(f"Row {line}: enter both texts and a valid review label.")
        reused = label == "shared wording"
        spans = []
        if reused:
            if common and not any(excerpts):
                quote_a = quote_b = common
            elif not common and len(excerpts) == 2 and all(excerpts):
                quote_a, quote_b = excerpts
            else:
                raise ValueError(
                    f"Row {line}: enter one shared quote or one excerpt from each text."
                )
            a, b = _offset(left, quote_a, line, "A"), _offset(right, quote_b, line, "B")
            spans.append(
                {
                    "left_start": a,
                    "left_end": a + len(quote_a),
                    "right_start": b,
                    "right_end": b + len(quote_b),
                }
            )
        elif common or any(excerpts):
            raise ValueError(f"Row {line}: leave the shared passage blank for no shared wording.")
        keys = [hashlib.sha256(text.encode()).hexdigest() for text in (left, right)]
        pair = tuple(sorted(keys))
        if pair in seen:
            raise ValueError(f"Row {line}: this report pair appears more than once.")
        seen.add(pair)
        if keys[0] == keys[1]:
            keys[1] += "-copy"
        refs = []
        for key, text in zip(keys, (left, right), strict=True):
            ref = {"report_id": key, "version_id": key}
            reports.setdefault(key, {**ref, "text": text})
            refs.append(ref)
        reviews.append(
            {
                "review_id": f"csv-{line}",
                "revision": 1,
                "left": refs[0],
                "right": refs[1],
                "coverage": "full",
                "reused": reused,
                "spans": spans,
            }
        )
    if {row["reused"] for row in reviews} != {False, True}:
        raise ValueError("Include examples of both shared wording and no shared wording.")
    return list(reports.values()), reviews
