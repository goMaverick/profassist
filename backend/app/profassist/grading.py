"""Council vote, judge, and the rule that nothing is pushed before approval."""

import zlib
from collections import Counter
from typing import Any

LEVELS = ["beginning", "developing", "proficient", "advanced"]


def level_spread(votes: list[dict[str, Any]]) -> int:
    """How many rubric steps separate the highest and lowest mark."""
    indexes = [LEVELS.index(vote["level"]) for vote in votes if vote.get("level") in LEVELS]
    if len(indexes) < 2:
        return 0
    return max(indexes) - min(indexes)


def needs_debate(votes: list[dict[str, Any]], threshold: int) -> bool:
    return level_spread(votes) > threshold


def quotes_in_text(quotes: list[str], text: str) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    rejected: list[str] = []
    for quote in quotes:
        if quote and quote in (text or ""):
            kept.append(quote)
        else:
            rejected.append(quote)
    return kept, rejected


def checks_contradict(votes: list[dict[str, Any]]) -> bool:
    """Same quote, opposite yes/no. That is a contradiction, not a level debate."""
    answers: dict[str, set[bool]] = {}
    for vote in votes:
        for check in vote.get("checks") or []:
            quote = check.get("quote") or ""
            if not quote:
                continue
            answers.setdefault(quote, set()).add(bool(check.get("answer")))
    return any(len(values) > 1 for values in answers.values())


def reconcile(votes: list[dict[str, Any]], submission: str) -> dict[str, Any]:
    all_quotes: list[str] = []
    for vote in votes:
        all_quotes.extend(vote.get("quotes") or [])
    kept, rejected = quotes_in_text(all_quotes, submission)
    reject_rate = (len(rejected) / len(all_quotes)) if all_quotes else 1.0
    levels = [vote.get("level") for vote in votes]
    split = ", ".join(str(level) for level in levels)
    unreliable = reject_rate > 0.5 or checks_contradict(votes) or not kept
    if unreliable:
        return {
            "evidence_status": "no_reliable_evidence",
            "level": None,
            "vote_split": levels,
            "quotes": kept,
            "rejected_quotes": rejected,
            "skip_calibrator": True,
            "why": (
                "No reliable evidence. The judge rejected quotes that are not in the "
                f"submission, or the graders contradicted each other. Vote split: {split}. "
                "The calibrator was skipped. The level is left for you."
            ),
        }
    top, _count = Counter(levels).most_common(1)[0]
    return {
        "evidence_status": "ok",
        "level": top,
        "vote_split": levels,
        "quotes": kept,
        "rejected_quotes": rejected,
        "skip_calibrator": False,
        "why": (
            f"Why this level: the council voted {split}. "
            f"The judge kept {len(kept)} quote(s) that appear verbatim in the submission "
            f"and set the level to {top}. A one-level gap stays visible for you."
        ),
    }


def is_blind_sample(key: str) -> bool:
    """About one draft in twenty hides the council level until the professor decides."""
    return zlib.crc32((key or "").encode()) % 20 == 0


def assert_can_push(status: str) -> None:
    if status != "approved":
        raise PermissionError(
            "The professor has not approved this yet. Nothing is pushed to Moodle."
        )


def redact_blind(
    results: list[dict[str, Any]], feedback: str, blind: bool, revealed: bool
) -> tuple[list, str]:
    if not blind or revealed:
        return results, feedback
    hidden = []
    for row in results:
        copy = dict(row)
        judge = dict(copy.get("judge") or {})
        judge["level"] = None
        judge["why"] = (
            "Blind sample. Read the quotes and choose a level before you reveal the council. "
            "This is one of the drafts held back so the suggestion does not anchor you."
        )
        copy["judge"] = judge
        copy["feedback"] = ""
        hidden.append(copy)
    return hidden, ""
