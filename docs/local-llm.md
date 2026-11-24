# A model for chat and the council

With no provider key configured, drafting raises an explicit `503` error instead of inventing a draft. A `GEMINI_API_KEY` on the API process is used when the saved provider has no key. The Google Gemini default in AI settings is `gemini-3.5-flash-lite`. `gemini-2.0-flash` is retired, and `gemini-2.5-flash` is refused for new keys. Put the key only in the process environment or an untracked `.env` file. Do not commit it.

Ollama is an optional local fallback, used only when no cloud key is set. Nothing here changes the committed provider default, and no key is stored in the repo.

```bash
ollama pull llama3.2:1b
export OLLAMA_API_BASE=http://127.0.0.1:11434
export LLM_MODEL=llama3.2:1b
```

Restart the API process with those variables. Open **AI settings** and press **Test Ollama / local**. The button uses `LLM_MODEL` when it is set, otherwise `llama3.2`.

`make local-llm` prints the same steps.
