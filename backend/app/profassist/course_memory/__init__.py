"""Course memory: contracts, deterministic cleaning, and the graph that builds it.

The pure helpers (contracts, cleaners, merge, prompts) are imported eagerly.
The graph and the database service are lazy so importing a prompt never pulls
in a model client or a database session.
"""

from __future__ import annotations

from typing import Any

from app.profassist.course_memory.cleaners import (
    clean_file_dossier,
    clean_merged_dossier,
    content_hash,
    parse_json_object,
)
from app.profassist.course_memory.merge import merge_dossiers, shrink_dossier
from app.profassist.course_memory.prompts import COURSE_MEMORY_MERGE, DOCUMENT_ANALYST
from app.profassist.course_memory.schemas import FileDossier, MergedDossier

_LAZY: dict[str, tuple[str, str]] = {
    "ExtractState": ("app.profassist.course_memory.graph", "ExtractState"),
    "MemoryState": ("app.profassist.course_memory.graph", "MemoryState"),
    "build_memory_graph": ("app.profassist.course_memory.graph", "build_memory_graph"),
    "extract_material_dossier": (
        "app.profassist.course_memory.graph",
        "extract_material_dossier",
    ),
    "pii_gate_dossier": ("app.profassist.course_memory.graph", "pii_gate_dossier"),
    "run_course_memory": ("app.profassist.course_memory.graph", "run_course_memory"),
    "run_memory_state": ("app.profassist.course_memory.graph", "run_memory_state"),
    "dossier_ai_context": ("app.profassist.course_memory.service", "dossier_ai_context"),
    "load_dossier": ("app.profassist.course_memory.service", "load_dossier"),
    "load_memory_inputs": ("app.profassist.course_memory.service", "load_memory_inputs"),
    "rebuild_course_memory": (
        "app.profassist.course_memory.service",
        "rebuild_course_memory",
    ),
    "rebuild_material": ("app.profassist.course_memory.service", "rebuild_material"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(target[0]), target[1])
    globals()[name] = value
    return value


__all__ = [
    "COURSE_MEMORY_MERGE",
    "DOCUMENT_ANALYST",
    "ExtractState",
    "FileDossier",
    "MemoryState",
    "MergedDossier",
    "build_memory_graph",
    "clean_file_dossier",
    "clean_merged_dossier",
    "content_hash",
    "dossier_ai_context",
    "extract_material_dossier",
    "load_dossier",
    "load_memory_inputs",
    "merge_dossiers",
    "parse_json_object",
    "pii_gate_dossier",
    "rebuild_course_memory",
    "rebuild_material",
    "run_course_memory",
    "run_memory_state",
    "shrink_dossier",
]
