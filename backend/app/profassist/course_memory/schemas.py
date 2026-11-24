"""Tolerant contracts for the document-intelligence dossier pipeline.

A model response is a proposal, never a fact. Every field has a default,
unknown keys are ignored, numbers that arrive as strings are coerced, and an
unrecognised document kind falls back to ``other``. The deterministic cleaners
repair provider drift (camelCase, ``LO``/``CLO``, ``"25%"``) before validation,
so a partial or sloppy response still yields a usable dossier.
"""

from __future__ import annotations

import re
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentKind = Literal["syllabus", "lecture", "assignment", "rubric", "policy", "reading", "other"]
DOCUMENT_KINDS: tuple[str, ...] = get_args(DocumentKind)

Levels = dict[str, str] | list[str]


def _as_int(value: Any) -> int | None:
    """``"Week 3"`` and ``3.0`` both become ``3``; junk becomes ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _as_float(value: Any) -> float | None:
    """``"25%"`` becomes ``25.0``; junk becomes ``None``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _as_string_list(value: Any) -> list[str]:
    """One code, a comma list, or a list of codes all become a list of codes."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;/|]", value) if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


class DossierModel(BaseModel):
    """Base for every dossier contract: a partial response still validates."""

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)


class Topic(DossierModel):
    name: str = ""
    week: int | None = None

    @field_validator("week", mode="before")
    @classmethod
    def _week(cls, value: Any) -> int | None:
        return _as_int(value)


class WeekLink(DossierModel):
    week: int = 0
    topic: str = ""

    @field_validator("week", mode="before")
    @classmethod
    def _week(cls, value: Any) -> int:
        return _as_int(value) or 0


class Outcome(DossierModel):
    code: str = ""
    text: str = ""


class OutcomeMapping(DossierModel):
    clo: str = ""
    plos: list[str] = Field(default_factory=list)

    @field_validator("plos", mode="before")
    @classmethod
    def _plos(cls, value: Any) -> list[str]:
        return _as_string_list(value)


class Outcomes(DossierModel):
    clos: list[Outcome] = Field(default_factory=list)
    plos: list[Outcome] = Field(default_factory=list)
    mappings: list[OutcomeMapping] = Field(default_factory=list)


class Assessment(DossierModel):
    name: str = ""
    weight: float | None = None
    due: str = ""
    lo_codes: list[str] = Field(default_factory=list)

    @field_validator("weight", mode="before")
    @classmethod
    def _weight(cls, value: Any) -> float | None:
        return _as_float(value)

    @field_validator("lo_codes", mode="before")
    @classmethod
    def _codes(cls, value: Any) -> list[str]:
        return _as_string_list(value)


class Reading(DossierModel):
    citation: str = ""
    week: int | None = None

    @field_validator("week", mode="before")
    @classmethod
    def _week(cls, value: Any) -> int | None:
        return _as_int(value)


class PolicyDate(DossierModel):
    key: str = ""
    title: str = ""
    body: str = ""
    date: str = ""


class KeyTerm(DossierModel):
    term: str = ""
    definition: str = ""


class FormulaExample(DossierModel):
    name: str = ""
    body: str = ""


class GradingCriterion(DossierModel):
    name: str = ""
    levels: Levels = Field(default_factory=dict)


class Claim(DossierModel):
    field: str = ""
    chunk_ordinal: int = 0
    quote: str = ""

    @field_validator("chunk_ordinal", mode="before")
    @classmethod
    def _ordinal(cls, value: Any) -> int:
        return _as_int(value) or 0


class Provenance(DossierModel):
    field: str = ""
    value: str = ""
    filename: str = ""
    chunk_ordinal: int = 0
    kind: str = ""

    @field_validator("chunk_ordinal", mode="before")
    @classmethod
    def _ordinal(cls, value: Any) -> int:
        return _as_int(value) or 0


class Conflict(DossierModel):
    field: str = ""
    winner: str = ""
    loser: str = ""
    reason: str = ""


class FileDossier(DossierModel):
    """What one file says. Everything is optional so a partial reply validates."""

    document_kind: DocumentKind = "other"
    summary: str = ""
    topics: list[Topic] = Field(default_factory=list)
    week_links: list[WeekLink] = Field(default_factory=list)
    outcomes: Outcomes = Field(default_factory=Outcomes)
    assessments: list[Assessment] = Field(default_factory=list)
    readings: list[Reading] = Field(default_factory=list)
    policies_dates: list[PolicyDate] = Field(default_factory=list)
    key_terms: list[KeyTerm] = Field(default_factory=list)
    formulas_examples: list[FormulaExample] = Field(default_factory=list)
    grading_criteria: list[GradingCriterion] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)

    @field_validator("document_kind", mode="before")
    @classmethod
    def _kind(cls, value: Any) -> DocumentKind:
        text = str(value or "").strip().lower()
        return cast(DocumentKind, text) if text in DOCUMENT_KINDS else "other"

    @field_validator("open_questions", mode="before")
    @classmethod
    def _questions(cls, value: Any) -> list[str]:
        return _as_string_list(value)


class MergedDossier(DossierModel):
    """One course-wide dossier: authority-ranked content plus its audit trail."""

    version: int = 1
    summary: str = ""
    topics: list[Topic] = Field(default_factory=list)
    weeks: list[WeekLink] = Field(default_factory=list)
    outcomes: Outcomes = Field(default_factory=Outcomes)
    assessments: list[Assessment] = Field(default_factory=list)
    readings: list[Reading] = Field(default_factory=list)
    policies_dates: list[PolicyDate] = Field(default_factory=list)
    key_terms: list[KeyTerm] = Field(default_factory=list)
    formulas_examples: list[FormulaExample] = Field(default_factory=list)
    grading_criteria: list[GradingCriterion] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: Any) -> int:
        return _as_int(value) or 1

    @field_validator("open_questions", mode="before")
    @classmethod
    def _questions(cls, value: Any) -> list[str]:
        return _as_string_list(value)
