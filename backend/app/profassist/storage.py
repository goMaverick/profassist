"""Store files in MinIO when it is configured, otherwise on the local media disk."""

import logging
import tempfile
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION or "us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )


def save_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if settings.S3_ENDPOINT and settings.S3_ACCESS_KEY:
        try:
            client = _client()
            bucket = settings.S3_BUCKET or "profassist"
            try:
                client.head_bucket(Bucket=bucket)
            except Exception:
                client.create_bucket(Bucket=bucket)
            client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
            return f"s3://{bucket}/{key}"
        except Exception:
            logger.info("MinIO write failed; keeping the file on local disk")
    path = Path(settings.MEDIA_DIR) / "profassist" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def read_bytes(storage_key: str) -> bytes:
    if storage_key.startswith("s3://"):
        _, rest = storage_key.split("s3://", 1)
        bucket, key = rest.split("/", 1)
        client = _client()
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()
    return Path(storage_key).read_bytes()


def extract_text(filename: str, data: bytes) -> str:
    import os

    if os.getenv("DOCLING_ENABLED", "").lower() in {"1", "true", "yes"}:
        try:
            from docling.document_converter import DocumentConverter

            suffix = os.path.splitext(filename)[1] or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(data)
                path = handle.name
            converted = DocumentConverter().convert(path)
            text = converted.document.export_to_markdown()
            if text.strip():
                return text
        except Exception:
            logger.info("Docling did not parse %s; using the built-in parser", filename)
    lower = filename.lower()
    if lower.endswith(".pdf"):
        import fitz

        document = fitz.open(stream=data, filetype="pdf")
        return "\n".join(page.get_text() for page in document)
    if lower.endswith(".docx"):
        import io

        from docx import Document

        document = Document(io.BytesIO(data))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if lower.endswith(".pptx"):
        import io

        from pptx import Presentation

        presentation = Presentation(io.BytesIO(data))
        bits = []
        for slide in presentation.slides:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    bits.append(shape.text)
        return "\n".join(bits)
    return data.decode("utf-8", errors="replace")
