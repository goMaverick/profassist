"""Slide citations never open on a partial word."""

from app.profassist.skills import slide_studio


def test_cite_slide_skips_a_mid_sentence_fragment() -> None:
    hits = [
        {
            "id": "c1",
            "filename": "notes.pdf",
            "section": "p2",
            "text": (
                "ario, and describe safe ways to handle sensitive data in production. "
                "Public safety requires encrypting that data at rest."
            ),
        }
    ]

    slide = slide_studio.cite_slide("Protect the data", hits)

    bullet = slide["bullets"][0]
    assert bullet["text"].startswith("Public safety")
    assert not bullet["text"].startswith("ario")
    assert bullet["citation"]["quote"] == ("Public safety requires encrypting that data at rest.")


def test_cite_slide_marks_a_continuation_fragment() -> None:
    text = (
        "ario, and describe safe ways to handle sensitive data in production "
        "without leaking it anywhere."
    )
    hits = [{"id": "c1", "filename": "notes.pdf", "text": text}]

    slide = slide_studio.cite_slide("Protect the data", hits)

    bullet = slide["bullets"][0]
    assert bullet["text"].startswith("…")
    assert "ario" not in bullet["text"]
    assert bullet["citation"]["quote"] == text


def test_cite_slide_keeps_a_normal_sentence() -> None:
    sentence = "Public safety requires encrypting that data at rest."
    hits = [{"id": "c1", "filename": "notes.pdf", "text": sentence}]

    slide = slide_studio.cite_slide("Protect the data", hits)

    bullet = slide["bullets"][0]
    assert bullet["text"] == sentence
    assert bullet["citation"]["quote"] == sentence


def test_critique_keeps_a_continuation_bullet_grounded_in_source() -> None:
    text = (
        "ario, and describe safe ways to handle sensitive data in production "
        "without leaking it anywhere."
    )
    slides = [
        {
            "title": "Protect the data",
            "bullets": [{"text": "…" + text.split(" ", 1)[1], "citation": {"quote": text}}],
        }
    ]

    kept = slide_studio.critique(slides, [{"text": text}])

    assert kept[0]["bullets"] == slides[0]["bullets"]
