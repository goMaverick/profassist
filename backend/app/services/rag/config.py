"""RAG configuration."""

import logging
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class DocumentExtensions(StrEnum):
    """Extensions supported by the RAG ingestion pipeline."""

    PDF = ".pdf"
    DOCX = ".docx"
    PPTX = ".pptx"
    POTX = ".potx"
    MD = ".md"
    TXT = ".txt"
    HTML = ".html"
    HTM = ".htm"


# The built-in processor (not PyMuPDF) parses PPTX and HTML; the name is kept
# for compatibility with the existing parser registry.
PYMUPDF_FORMATS: set[str] = {
    ".pdf",
    ".docx",
    ".pptx",
    ".potx",
    ".txt",
    ".md",
    ".html",
    ".htm",
}

LITEPARSE_FORMATS: set[str] = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".txt",
    ".md",
    ".jpg",
    ".jpeg",
    ".png",
    ".tiff",
}

LLAMAPARSE_FORMATS: set[str] = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".rtf",
    ".txt",
    ".md",
    ".epub",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".webp",
    ".xlsx",
    ".xls",
    ".csv",
    ".tsv",
    ".ods",
    ".mp3",
    ".mp4",
    ".wav",
    ".m4a",
    ".webm",
    ".html",
    ".htm",
    ".xml",
}

PARSER_FORMATS: dict[str, set[str]] = {
    "pymupdf": PYMUPDF_FORMATS,
    "liteparse": LITEPARSE_FORMATS,
    "llamaparse": LLAMAPARSE_FORMATS,
}


def get_supported_formats(parser_name: str = "pymupdf") -> set[str]:
    """Get supported file formats for a given parser."""
    return PARSER_FORMATS.get(parser_name, PYMUPDF_FORMATS)


# Known embedding models and their output dimensions.
# Local models are the ones fastembed can actually load and run on CPU; remote
# models need a hosted endpoint (OpenAI and compatible services).
DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_LOCAL_EMBEDDING_DIM = 384

LOCAL_EMBEDDING_MODELS: dict[str, int] = {
    DEFAULT_LOCAL_EMBEDDING_MODEL: DEFAULT_LOCAL_EMBEDDING_DIM,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/all-mpnet-base-v2": 768,
    # Fastembed short names (same weights as the BAAI/* ids)
    "bge-small-en-v1.5": 384,
    "bge-base-en-v1.5": 768,
    "bge-large-en-v1.5": 1024,
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
}

REMOTE_EMBEDDING_MODELS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-code-3": 1024,
    "gemini-embedding-001": 3072,
    "gemini-embedding-exp-03-07": 3072,
}

# Full catalogue, for callers that only need "is this model a known one".
EMBEDDING_DIMENSIONS: dict[str, int] = {**LOCAL_EMBEDDING_MODELS, **REMOTE_EMBEDDING_MODELS}

LOCAL_EMBEDDING_PROVIDERS = frozenset({"local", "fastembed"})
REMOTE_EMBEDDING_PROVIDERS = frozenset({"openai", "remote"})


class EmbeddingsConfig(BaseModel):
    """Embeddings configuration.

    ``dim`` is auto-derived from the model name when it is 0 (the default).

    - ``local``: the model must be one fastembed can run (see
      ``LOCAL_EMBEDDING_MODELS``). A remote-only model is replaced by
      ``DEFAULT_LOCAL_EMBEDDING_MODEL`` with a warning, so one stale
      ``EMBEDDING_MODEL`` cannot take the RAG pipeline down at startup.
    - ``openai``/``remote``: the configured model is kept and a positive
      dimension is required (a known model name or an explicit ``EMBEDDING_DIM``).
    """

    provider: str = "local"
    model: str = DEFAULT_LOCAL_EMBEDDING_MODEL
    dim: int = 0
    api_key: str = ""
    base_url: str | None = None

    @model_validator(mode="after")
    def set_dim_from_model(self) -> "EmbeddingsConfig":
        provider = self.provider.strip().lower()
        if provider not in LOCAL_EMBEDDING_PROVIDERS | REMOTE_EMBEDDING_PROVIDERS:
            raise ValueError(
                f"Unknown embedding provider '{self.provider}'. "
                "Use 'local' (fastembed) or 'openai'/'remote'."
            )
        self.provider = "local" if provider in LOCAL_EMBEDDING_PROVIDERS else "openai"
        if self.provider == "local":
            self._use_local_model()
            return self
        if self.dim <= 0:
            known = REMOTE_EMBEDDING_MODELS.get(self.model)
            if known is None:
                raise ValueError(
                    f"Unknown remote embedding model '{self.model}'. Add it to "
                    "REMOTE_EMBEDDING_MODELS or set EMBEDDING_DIM explicitly."
                )
            self.dim = known
        return self

    def _use_local_model(self) -> None:
        """Keep a model fastembed can load, falling back to bge-small."""
        local_dim = LOCAL_EMBEDDING_MODELS.get(self.model)
        if local_dim is None:
            fallback = DEFAULT_LOCAL_EMBEDDING_MODEL
            if self.dim > 0 and self.dim != DEFAULT_LOCAL_EMBEDDING_DIM:
                logger.warning(
                    "Ignoring EMBEDDING_DIM=%s: the local fallback model '%s' outputs %s dims.",
                    self.dim,
                    fallback,
                    DEFAULT_LOCAL_EMBEDDING_DIM,
                )
            logger.warning(
                "EMBEDDING_PROVIDER=local cannot run the configured model '%s' "
                "(local models: %s). Falling back to '%s' (%s dims). "
                "Set EMBEDDING_PROVIDER=openai with an API key to use '%s' remotely.",
                self.model,
                ", ".join(sorted(LOCAL_EMBEDDING_MODELS)),
                fallback,
                DEFAULT_LOCAL_EMBEDDING_DIM,
                self.model,
            )
            self.model = fallback
            self.dim = DEFAULT_LOCAL_EMBEDDING_DIM
            return
        if self.dim <= 0:
            self.dim = local_dim


class DocumentParser(BaseModel):
    """Document parsing settings (non-PDF files)."""

    method: str = "python_native"


class PdfParser(BaseModel):
    """PDF parsing settings."""

    method: str = "pymupdf"


class RAGSettings(BaseModel):
    """RAG pipeline configuration."""

    collection_name: str = "documents"

    allowed_extensions: list[DocumentExtensions] = Field(
        default_factory=lambda: list(DocumentExtensions)
    )

    chunk_size: int = 512
    chunk_overlap: int = 50
    chunking_strategy: str = "recursive"
    enable_hybrid_search: bool = False
    enable_ocr: bool = False

    embeddings_config: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)

    document_parser: DocumentParser = Field(default_factory=DocumentParser)
    pdf_parser: PdfParser = Field(default_factory=PdfParser)
    gdrive_ingestion: bool = False
