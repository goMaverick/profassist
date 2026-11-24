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
