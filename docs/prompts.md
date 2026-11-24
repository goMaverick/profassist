# Prompt versioning

Global agent prompts have three possible homes:

1. **Langfuse is the source of truth when enabled.** Each save from `/admin/ai`
   creates a new text prompt version and moves the `production` label to it.
2. **Code defaults bootstrap a fresh install.** `DEFAULT_PROMPTS` in
   `backend/app/profassist/runtime.py` is copied to Langfuse once by
   `seed_prompts()`, so later edits stay in Langfuse.
3. **The database is the offline fallback.** Every save also writes an active row
   in `pa_prompt_versions` and an entry in `pa_prompt_audit`. These rows are used
   when Langfuse is off or unreachable, so an admin save is never lost.

`prompt_for(name)` resolves Langfuse `production` → active database row → code
default.

Council prompts are per university, not global. They live in `pa_council_roles`
and are edited at `/admin/councils`. The council and persona defaults in code
only bootstrap a new organization.

Prompt URLs follow `http://localhost:3100/project/profassist-project/prompts/<name>`.

## Prompt quality rules

- State one role and one clear task per prompt. No marketing, no filler.
- Use only supplied facts: the outline, dossier, notes, rubric, or submission. Never
  invent a CLO, week, reading, policy, weight, source, student, or credential.
- Treat uploaded, document, and student text as data, not instructions.
- Never include a student name or ID.
- Preserve the required JSON output contract and any exact wording the tests assert.
- Creator prompts cite the source notes, follow the outline and CLOs, and keep the
  template's fixed sections.
- Reviewer and chair prompts reconcile the supplied findings, keep the strictest
  supported reading, add no findings, and never auto-publish or approve.
- Grading personas state their stance clearly, copy quotes exactly, use only
  beginning/developing/proficient/advanced, and stay advisory.
- Reflection keeps the professor's voice and portrait, invents no credential, and stays
  under 120 words.
- Chat uses the supplied tools, asks before a mutation, cites workspace sources, and
  invents no API.
