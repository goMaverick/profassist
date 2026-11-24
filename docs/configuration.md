# Configuration Reference

All configuration is managed via environment variables, loaded from
`backend/.env` using [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Settings are defined in `app/core/config.py` and accessed via the global
`settings` object:

```python
from app.core.config import settings

print(settings.AI_MODEL)
print(settings.DEBUG)
```

## Getting Started

```bash
cd backend

# Copy the example file (may already exist if generated with --generate-env)
cp .env.example .env

# Generate a secure secret key
openssl rand -hex 32
# Paste the output as SECRET_KEY in .env
```

## Project Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_NAME` | `profassist` | Display name for the project |
| `API_V1_STR` | `/api/v1` | API version prefix |
| `DEBUG` | `false` | Enable debug mode (verbose errors, auto-reload) |
| `ENVIRONMENT` | `local` | One of: `development`, `local`, `staging`, `production` |
| `TIMEZONE` | `Asia/Dubai` | IANA timezone (e.g. `UTC`, `Europe/Warsaw`, `America/New_York`) |
| `MODELS_CACHE_DIR` | `./models_cache` | Directory for cached ML models |
| `MEDIA_DIR` | `./media` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_MB` | `50` | Maximum file upload size in megabytes |

## Authentication

### JWT

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (insecure default) | JWT signing key. **Must** be changed in production. Generate with: `openssl rand -hex 32` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_MINUTES` | `10080` | Refresh token lifetime (7 days) |
| `ALGORITHM` | `HS256` | JWT signing algorithm |

Production validation: `SECRET_KEY` must be at least 32 characters and cannot
use the default value in `ENVIRONMENT=production`.

### API Key

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `change-me-in-production` | Shared API key for programmatic access |
| `API_KEY_HEADER` | `X-API-Key` | HTTP header name for API key |

Production validation: `API_KEY` cannot use the default value in
`ENVIRONMENT=production`.


## Database (PostgreSQL)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_USER` | `postgres` | PostgreSQL user |
| `POSTGRES_PASSWORD` | (empty) | PostgreSQL password |
| `POSTGRES_DB` | `profassist` | Database name |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Max overflow connections |
| `DB_POOL_TIMEOUT` | `30` | Pool timeout in seconds |

Computed properties:
- `DATABASE_URL` -- async connection string (`postgresql+asyncpg://...`)
- `DATABASE_URL_SYNC` -- sync connection string for Alembic

## Redis

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `localhost` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_PASSWORD` | (none) | Redis password (optional) |
| `REDIS_DB` | `0` | Redis database number |

## AI Agent

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (empty) | OpenAI API key |
| `AI_MODEL` | `gpt-5.5` | Default LLM model for chat |
| `AI_TEMPERATURE` | `0.7` | LLM temperature (0.0 = deterministic, 1.0 = creative) |
| `AI_AVAILABLE_MODELS` | (auto-configured) | JSON list of models shown in the UI model selector |
| `AI_FRAMEWORK` | `langgraph` | AI framework (informational) |
| `LLM_PROVIDER` | `openai` | LLM provider (informational) |

### Customizing Available Models

Override `AI_AVAILABLE_MODELS` in `.env` to customize the model selector:

```bash
AI_AVAILABLE_MODELS=["gpt-5.5","gpt-5.4","claude-opus-4-7"]
```

## RAG (Retrieval Augmented Generation)

### Vector Database

| Variable | Default | Description |
|----------|---------|-------------|
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `QDRANT_API_KEY` | (empty) | Qdrant API key (optional) |

### Embeddings

Local embeddings are the default: fastembed runs on CPU and needs no API key.
The model downloads once into MODELS_CACHE_DIR.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_PROVIDER` | `local` | `local` (fastembed) or `openai`/`remote` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local model (384 dims) or remote model (`text-embedding-3-small` = 1536, `text-embedding-3-large` = 3072) |
| `EMBEDDING_API_KEY` | (empty) | Remote key; falls back to `OPENAI_API_KEY` |
| `EMBEDDING_BASE_URL` | (empty) | OpenAI-compatible embeddings endpoint |
| `EMBEDDING_DIM` | `0` | 0 = derive from the model; set only for a custom model |

### Chunking & Retrieval

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_CHUNK_SIZE` | `512` | Maximum characters per chunk |
| `RAG_CHUNK_OVERLAP` | `50` | Characters of overlap between chunks |
| `RAG_CHUNKING_STRATEGY` | `recursive` | Chunking strategy: `recursive`, `markdown`, `fixed` |
| `RAG_DEFAULT_COLLECTION` | `documents` | Default collection for search (used by agent tool) |
| `RAG_TOP_K` | `10` | Default number of results to return |
| `RAG_HYBRID_SEARCH` | `false` | Enable BM25 + vector hybrid search |
| `RAG_ENABLE_OCR` | `false` | OCR fallback for scanned PDFs (requires `tesseract-ocr`) |

### Document Parsing

### S3/MinIO Sync

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_RAG_ENDPOINT` | (none) | S3/MinIO endpoint URL |
| `S3_RAG_ACCESS_KEY` | (empty) | Access key |
| `S3_RAG_SECRET_KEY` | (empty) | Secret key |
| `S3_RAG_BUCKET` | `profassist-rag` | Bucket name |
| `S3_RAG_REGION` | `us-east-1` | AWS region |

## CORS

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:8080"]` | Allowed origins (JSON array) |
| `CORS_ALLOW_CREDENTIALS` | `true` | Allow credentials (cookies) |
| `CORS_ALLOW_METHODS` | `["*"]` | Allowed HTTP methods |
| `CORS_ALLOW_HEADERS` | `["*"]` | Allowed HTTP headers |

Production validation: `CORS_ORIGINS` cannot contain `"*"` in
`ENVIRONMENT=production`.

## Rate Limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_REQUESTS` | `100` | Maximum requests per period |
| `RATE_LIMIT_PERIOD` | `60` | Period in seconds |

## File Storage (S3/MinIO)

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_ENDPOINT` | (none) | S3/MinIO endpoint URL |
| `S3_ACCESS_KEY` | (empty) | Access key |
| `S3_SECRET_KEY` | (empty) | Secret key |
| `S3_BUCKET` | `profassist` | Bucket name |
| `S3_REGION` | `us-east-1` | AWS region |

## Docker / Production

| Variable | Default | Description |
|----------|---------|-------------|
| `DOMAIN` | `example.com` | Production domain (for Traefik) |
| `ACME_EMAIL` | `admin@example.com` | Let's Encrypt email for SSL certs |
| `REDIS_PASSWORD` | `change-me-in-production` | Redis password for production |

## Production Checklist

Before deploying to production, ensure these variables are properly set:
1. `SECRET_KEY` -- Generate a unique 64-character hex key: `openssl rand -hex 32`
2. `API_KEY` -- Generate a unique key: `openssl rand -hex 32`
3. `ENVIRONMENT` -- Set to `production`
4. `DEBUG` -- Set to `false`
5. `POSTGRES_PASSWORD` -- Use a strong, unique password
6. `CORS_ORIGINS` -- List only your actual frontend domain(s)
7. `REDIS_PASSWORD` -- Set a strong password
8. `OPENAI_API_KEY` -- Your production API key
