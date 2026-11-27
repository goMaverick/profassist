"""Topic-aware similarity. Flags are evidence for a viva, not a verdict.

Three untrained layers: winnowing fingerprints, rare details, and a hashing
embedding that only breaks a tie. Sections are compared with the same section.
"""

import hashlib
import re
from collections import Counter
from typing import Any

COMMON = {
    "because",
    "therefore",
    "limitation",
    "evidence",
    "students",
    "course",
    "report",
    "group",
    "campus",
    "energy",
    "method",
    "findings",
    "introduction",
    "would",
    "their",
    "there",
    "which",
    "about",
    "after",
    "before",
    "should",
    "could",
    "other",
    "these",
    "those",
    "using",
    "from",
    "with",
    "that",
    "this",
    "have",
    "were",
    "been",
    "into",
    "only",
    "your",
    "they",
    "them",
    "than",
    "then",
    "when",
    "what",
    "where",
    "also",
    "such",
    "each",
    "same",
    "over",
    "under",
    "between",
    "across",
    "within",
    "without",
    "during",
    "while",
    "staff",
    "floors",
    "trend",
    "reliable",
    "weekdays",
    "missing",
    "interviewed",
    "facilities",
    "mapped",
    "meters",
    "paragraph",
    "example",
    "brief",
    "designed",
    "dashboard",
    "teaching",
    "baseline",
    "recommend",
    "review",
    "weekly",
    "unnoticed",
    "overnight",
    "opening",
    "hours",
    "extend",
    "later",
    "partial",
    "cautious",
    "library",
    "water",
    "sensor",
    "counts",
    "class",
    "changeover",
    "sample",
    "small",
    "studied",
    "rather",
    "copying",
    "staying",
    "inside",
    "operations",
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def fingerprints(text: str, k: int = 8, window: int = 4) -> dict[str, str]:
    words = tokens(text)
    if len(words) < k:
        return {}
    grams: list[tuple[str, str]] = []
    for index in range(len(words) - k + 1):
        gram = " ".join(words[index : index + k])
        digest = hashlib.sha1(gram.encode()).hexdigest()
        grams.append((digest, gram))
    chosen: dict[str, str] = {}
    for index in range(len(grams) - window + 1):
        digest, gram = min(grams[index : index + window], key=lambda item: item[0])
        chosen[digest] = gram
    return chosen


def expand_shared_passage(left: str, right: str, fingerprint: str) -> tuple[str, str]:
    """Extend a shared fingerprint through adjacent matching text in both reports."""
    anchor = tokens(fingerprint)
    if not anchor:
        return fingerprint, fingerprint

    def locate(text: str) -> tuple[list[re.Match[str]], int | None]:
        words = list(re.finditer(r"[a-z0-9']+", text, re.IGNORECASE | re.ASCII))
        values = [word.group().lower() for word in words]
        index = next(
            (
                i
                for i, value in enumerate(values)
                if value == anchor[0] and values[i : i + len(anchor)] == anchor
            ),
            None,
        )
        return words, index

    left_words, a = locate(left)
    right_words, b = locate(right)
    if a is None or b is None:
        return fingerprint, fingerprint

    left_end, right_end = a + len(anchor) - 1, b + len(anchor) - 1

    def same_link(i: int, j: int) -> bool:
        return (
            left[left_words[i].end() : left_words[i + 1].start()].strip()
            == right[right_words[j].end() : right_words[j + 1].start()].strip()
        )

    while (
        a > 0
        and b > 0
        and same_link(a - 1, b - 1)
        and left_words[a - 1].group().lower() == right_words[b - 1].group().lower()
    ):
        a -= 1
        b -= 1
    while (
        left_end + 1 < len(left_words)
        and right_end + 1 < len(right_words)
        and same_link(left_end, right_end)
        and left_words[left_end + 1].group().lower() == right_words[right_end + 1].group().lower()
    ):
        left_end += 1
        right_end += 1

    left_stop, right_stop = left_words[left_end].end(), right_words[right_end].end()
    punctuation = re.match(r"[.!?]+", left[left_stop:])
    if punctuation and right.startswith(punctuation.group(), right_stop):
        left_stop += len(punctuation.group())
        right_stop += len(punctuation.group())
    return left[left_words[a].start() : left_stop], right[right_words[b].start() : right_stop]


def hash_embed(text: str, dim: int = 64) -> list[float]:
    vector = [0.0] * dim
    for token in tokens(text):
        digest = hashlib.sha1(token.encode()).digest()
        bucket = digest[0] % dim
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = sum(value * value for value in vector) ** 0.5 or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?im)^(introduction|method|findings)\s*$", text or ""))
    if not matches:
        return {"body": text or ""}
    found: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[match.group(1).lower()] = text[start:end].strip()
    return found


def _rare_tokens(text: str) -> set[str]:
    found = set(re.findall(r"\b\d+\.\d+\b", text or ""))
    for token in tokens(text):
        if len(token) >= 8 and token not in COMMON and not token.isalpha():
            found.add(token)
        if len(token) >= 10 and token not in COMMON:
            found.add(token)
    return found


def compare_submissions(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """rows: id, group_name, topic, text. Only the same topic is compared."""
    flags: list[dict[str, Any]] = []
    by_topic: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_topic.setdefault(row.get("topic") or "general", []).append(row)

    for topic, group in by_topic.items():
        section_maps = [(row, sections(row.get("text") or "")) for row in group]
        names = sorted({name for _, mapping in section_maps for name in mapping})
        for section in names:
            texts = [(row, mapping.get(section, "")) for row, mapping in section_maps]
            rare_sets = [_rare_tokens(text) for _, text in texts]
            document_frequency: Counter[str] = Counter()
            for token_set in rare_sets:
                document_frequency.update(token_set)
            for left in range(len(texts)):
                for right in range(left + 1, len(texts)):
                    left_row, left_text = texts[left]
                    right_row, right_text = texts[right]
                    if not left_text or not right_text:
                        continue
                    left_fp = fingerprints(left_text)
                    right_fp = fingerprints(right_text)
                    shared = set(left_fp) & set(right_fp)
                    score = (
                        (len(shared) / min(len(left_fp), len(right_fp)))
                        if left_fp and right_fp
                        else 0.0
                    )
                    passage = ""
                    if shared:
                        passage = max((left_fp[digest] for digest in shared), key=len)
                    rare = [
                        token
                        for token in rare_sets[left] & rare_sets[right]
                        if document_frequency[token] == 2
                    ]
                    embed = cosine(hash_embed(left_text), hash_embed(right_text))
                    kind = None
                    if score >= 0.18:
                        kind = "fingerprint"
                    elif len(rare) >= 1 and score >= 0.05:
                        kind = "rare_detail"
                    elif 0.05 <= score < 0.18 and embed >= 0.8:
                        kind = "embedding_tie"
                    shared_typo = kind is None and any(
                        token.isalpha() and not token.replace(".", "").isdigit() for token in rare
                    )
                    if shared_typo:
                        kind = "rare_detail"
                    if kind is None:
                        continue
                    passage_a, passage_b = (
                        expand_shared_passage(left_text, right_text, passage)
                        if passage
                        else (left_text[:280], right_text[:280])
                    )
                    flags.append(
                        {
                            "left_id": left_row["id"],
                            "right_id": right_row["id"],
                            "left_group": left_row.get("group_name"),
                            "right_group": right_row.get("group_name"),
                            "topic": topic,
                            "section": section,
                            "score": round(score, 3),
                            "embedding": round(embed, 3),
                            "kind": kind,
                            "passage_a": passage_a,
                            "passage_b": passage_b,
                            "rare_details": sorted(rare)[:8],
                        }
                    )
    flags.sort(key=lambda item: item["score"], reverse=True)
    return flags
