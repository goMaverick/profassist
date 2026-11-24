# Memory

ProfAssist keeps a small, scrubbed memory for each professor: preferences, tone notes, and lessons learned while grading. Memory is scoped to one professor inside one university. Student names never enter memory - the text is scrubbed before it is stored.

## Postgres is the source of truth

Every memory write goes to Postgres first (profassist_memory). This is the primary store used to read memory back: recall(), the memory list, and the memory panel all read from Postgres.

## Qdrant is a 64-dim mirror

After the Postgres write, a copy is upserted into the profassist_memory Qdrant collection using a 64-dimension hash embedding. This mirror exists for similarity work; it is not the source of truth. If Qdrant is down or the write fails, the failure is logged and the Postgres copy remains.

## Mem0 is an optional mirror

The open-source Mem0 library can also receive each scrubbed memory, and - when enabled - its hits are merged into slide-edit recall. It is:

- **Not installed by default.** `mem0ai` is not a project dependency, so a normal `uv sync` and the Docker image do not include it. The code imports it lazily and stays inert when the package is absent.
- **Off by default.** Nothing is sent to Mem0 unless explicitly enabled.
- **Never the source of truth.** Postgres answers every read first. Mem0 results are merged in after the Postgres ones, and Postgres remains the fallback whenever Mem0 is missing, misconfigured, or slow.
- **Best-effort.** A missing library, a bad configuration, or a failed call is logged and swallowed; the Postgres copy has already succeeded.

### How to enable

Mem0 must be installed before the flag has any effect. From `backend/`, install the pinned version:

    uv add mem0ai==2.2.1

`uv add` updates `pyproject.toml`, relocks `uv.lock`, and installs the package. If you would rather keep the default dependency surface clean, add it to an explicit extra instead - for example, `[project.optional-dependencies]` with `mem0 = ["mem0ai==2.2.1"]` - and install with `uv sync --extra mem0`. Either way, commit the relocked `uv.lock`: `uv sync --frozen` does not resolve new dependencies, so an unrelocked change fails the frozen (Docker) install.

> **Warning:** `mem0ai==2.2.1` requires `protobuf<7.0.0,>=5.29.6`. Locking it therefore downgrades protobuf in `uv.lock` (from 7.x to 6.x at the time of writing). That is expected when you opt in, but it changes the image and anything else sharing the lock, so relock deliberately and review the protobuf diff.

Then set both of the following in backend/.env:

    MEM0_ENABLED=true
    LLM_API_KEY=...   # Mem0 needs an LLM key to extract facts

MEM0_ENABLED accepts 1 or true (case-insensitive). Anything else, or an unset value, leaves Mem0 disabled. With no LLM key, Mem0 stays off even when the flag is true.

### Which embedder runs

Mem0 embeds every memory before it stores it. Its own default is OpenAI's text-embedding-3-small, which would send scrubbed memory text to api.openai.com from a deployment that may run its model somewhere else. ProfAssist therefore always sets an embedder explicitly:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MEM0_EMBEDDER_PROVIDER` | `fastembed` | The embedder Mem0 uses. `fastembed`, `huggingface`, and `ollama` run on this machine, so no text leaves it. `openai` and `azure_openai` are used only when named here on purpose, and then take `LLM_API_KEY` and `LLM_BASE_URL`. |
| `MEM0_EMBEDDER_MODEL` | unset | The embedder's model. Unset means Mem0's own default (thenlper/gte-large for `fastembed`). |
| `MEM0_EMBEDDER_DIMS` | `1024` for `fastembed`, `1536` for `openai` | Vector size. Required whenever `MEM0_EMBEDDER_MODEL` is set, because a custom model's size cannot be guessed. |
| `MEM0_HISTORY_PATH` | `profassist-mem0.db` under the OS temp directory | Mem0's sqlite history file. Its parent directory is created on demand. |

If no safe embedder is configured - an unknown provider, a custom model without `MEM0_EMBEDDER_DIMS`, or a cloud embedder without a key - the Mem0 write and search are skipped with an info log. Nothing is sent to OpenAI as a fallback.

### Telemetry

Mem0 ships PostHog telemetry on by default. ProfAssist sets `MEM0_TELEMETRY=False` before the library is imported, so no event leaves the process unless an operator sets `MEM0_TELEMETRY=true`.

## What memory does not do

- It does not replace Postgres. Postgres remains the only source of truth.
- It does not use Mem0 in place of Postgres for recall: Mem0 hits are merged in only when enabled, and a Mem0 failure leaves the Postgres answer intact.
- It does not store student names, emails, IDs, or other PII.
- It does not cross tenant or professor scope.
