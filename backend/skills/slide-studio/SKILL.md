# Slide studio

A reusable skill the course agent loads when the professor asks for a deck.

## When to use it

Use this skill after the professor has approved at least one objective and uploaded course notes. Do not invent slides from general knowledge.

## Tools

- `plan` — turn each objective into one or two retrieval questions.
- `retrieve` — search this professor's notes. Run a second hop for any question that came back thin, and link a chunk that mentions the same term in another note.
- `cite` — every bullet keeps the filename and the passage it came from.
- `critique` — drop a bullet that is not in the notes. Mark an objective as a gap when nothing supports it.
- `pptx` — export a full deck: title, agenda, section divider, content or two columns, a chart or table when the notes contain numbers, a quote, key takeaways, and a references slide. An uploaded .pptx or .potx master sets the page size. Every slide has a number, speaker notes, and its sources. Text is sized to stay inside its box. An image box is a placeholder until a figure is supplied.

## Rules

The professor reviews the sources beside each slide, and the thumbnails, before she approves the deck. A gap is shown, not filled in. Student names are not used; the privacy gate runs before retrieval text is sent to a model.
