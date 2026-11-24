"""Langfuse traces for agent runs.

Spans are opened around each LangGraph run and each model step. Inputs are the
payloads already passed through the privacy gate. Tenant and professor ids are
stored as short hashes, not as emails or names.
"""

import hashlib
import logging
import os
from contextvars import ContextVar
from typing import Any

from app.profassist.config import langfuse_enabled
from app.profassist.runtime import DEFAULT_PROMPTS

logger = logging.getLogger(__name__)

_actor: ContextVar[dict[str, str] | None] = ContextVar("pa_actor", default=None)
# The latest model-step trace for the current request. Consumers read it only
# for a top-level response key, never inside the parsed artifact JSON.
_step_trace: ContextVar[str | None] = ContextVar("pa_step_trace", default=None)
_prompt_cache: dict[str, tuple[str, int]] = {}


def opaque(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def set_actor(organization_id: str, user_id: str) -> None:
    _actor.set({"tenant": opaque(organization_id), "professor": opaque(user_id)})


def actor_metadata() -> dict[str, str]:
    return dict(_actor.get() or {})


def public_base() -> str:
    return os.getenv("LANGFUSE_PUBLIC_BASE_URL", "http://localhost:3100").rstrip("/")


def project_id() -> str:
    return os.getenv("LANGFUSE_PROJECT_ID", "profassist-project")


def prompt_url(name: str) -> str:
    return f"{public_base()}/project/{project_id()}/prompts/{name}"


def trace_url(trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    return f"{public_base()}/project/{project_id()}/traces/{trace_id}"


def trace_about() -> str:
    """The portrait for Langfuse: identity lines removed, body still scrubbed.

    The professor's own name, role, and course codes stay out of the trace
    store. Imported lazily because ``runtime`` imports this module.
    """
    from app.profassist.lessons import split_identity
    from app.profassist.runtime import labelled_about

    labelled = labelled_about()
    if not labelled:
        return ""
    _, body = split_identity(labelled)
    return body.strip()[:900]


def _client():
    if not langfuse_enabled():
        return None
    try:
        from langfuse import get_client

        return get_client()
    except Exception:
        logger.info("Langfuse client is not available")
        return None


def callbacks() -> list[Any]:
    """LangGraph/LangChain callback so each node is a nested span."""
    if not langfuse_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception:
        logger.info("Langfuse LangGraph callback is not available")
        return []


def invoke_graph(
    graph: Any, state: dict, *, name: str, metadata: dict[str, Any] | None = None
) -> tuple[Any, str | None]:
    """Run a graph and return (result, public trace url)."""
    about = trace_about()
    meta = {**actor_metadata(), **(metadata or {})}
    if about:
        meta["about_this_professor"] = about
    client = _client()
    if client is None:
        return graph.invoke(state), None
    trace_id = None
    result = None
    try:
        with client.start_as_current_span(
            name=name, metadata=meta, input={"run": name, "about_this_professor": about}
        ):
            client.update_current_trace(
                name=name, metadata=meta, tags=["profassist", str(meta.get("kind") or "agent")]
            )
            result = graph.invoke(
                state,
                config={"callbacks": callbacks(), "run_name": name, "metadata": meta},
            )
            trace_id = client.get_current_trace_id()
        client.flush()
    except Exception:
        logger.info("Langfuse trace for %s was not stored", name)
        if result is None:
            result = graph.invoke(state)
    return result, trace_url(trace_id)


def reset_step_trace() -> None:
    """Start a request with no remembered model-step trace."""
    _step_trace.set(None)


def step_trace_url() -> str | None:
    """The public URL of the last model step traced in this request, if any."""
    return _step_trace.get()


def record_step(name: str, *, input_data: Any, output_data: Any, model: str) -> None:
    """One generation span. Safe to call when no parent trace is open."""
    client = _client()
    if client is None:
        return
    try:
        with client.start_as_current_generation(
            name=name,
            input=input_data,
            output=output_data,
            model=model,
            metadata=actor_metadata(),
        ):
            client.update_current_trace(name=name, metadata=actor_metadata())
            trace_id = client.get_current_trace_id()
        link = trace_url(trace_id)
        if link:
            _step_trace.set(link)
        client.flush()
    except Exception:
        logger.info("Langfuse step %s was not stored", name)


def ensure_bucket() -> None:
    """Langfuse stores events in a MinIO bucket named langfuse."""
    endpoint = os.getenv("S3_ENDPOINT") or ""
    key = os.getenv("S3_ACCESS_KEY") or ""
    secret = os.getenv("S3_SECRET_KEY") or ""
    if not endpoint or not key:
        return
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
            region_name=os.getenv("S3_REGION") or "us-east-1",
            config=Config(s3={"addressing_style": "path"}),
        )
        existing = [bucket["Name"] for bucket in client.list_buckets().get("Buckets", [])]
        if "langfuse" not in existing:
            client.create_bucket(Bucket="langfuse")
    except Exception:
        logger.info("Langfuse bucket was not created")


def seed_prompts(prompts: dict[str, str] | None = None) -> None:
    """Create the production prompt for each agent once. Later edits stay in Langfuse."""
    ensure_bucket()
    client = _client()
    if client is None:
        return
    bodies = prompts or DEFAULT_PROMPTS
    for name, text in bodies.items():
        try:
            client.get_prompt(
                name,
                label="production",
                cache_ttl_seconds=0,
                max_retries=1,
                fetch_timeout_seconds=2,
            )
        except Exception:
            try:
                client.create_prompt(
                    name=name,
                    type="text",
                    prompt=text,
                    labels=["production"],
                    commit_message="Seeded from ProfAssist defaults",
                )
            except Exception:
                logger.info("Could not seed Langfuse prompt %s", name)
    try:
        client.flush()
    except Exception:
        return


def production_prompt(name: str) -> tuple[str, int] | None:
    """Return (text, version) for the production label, or None if Langfuse has no copy."""
    cached = _prompt_cache.get(name)
    if cached:
        return cached
    client = _client()
    if client is None:
        return None
    try:
        prompt = client.get_prompt(
            name,
            label="production",
            cache_ttl_seconds=60,
            max_retries=1,
            fetch_timeout_seconds=2,
        )
    except Exception:
        return None
    text = getattr(prompt, "prompt", None)
    version = int(getattr(prompt, "version", 1) or 1)
    if not isinstance(text, str) or not text.strip():
        return None
    _prompt_cache[name] = (text, version)
    return text, version


def publish_prompt(name: str, body: str) -> int | None:
    """Publish a new production version of a global prompt to Langfuse.

    Returns the new version, or ``None`` when Langfuse is off or the publish
    fails. The database copy saved by the admin remains the offline fallback.
    """
    client = _client()
    if client is None:
        return None
    try:
        prompt = client.create_prompt(
            name=name,
            type="text",
            prompt=body,
            labels=["production"],
            commit_message="Published from ProfAssist admin",
        )
        _prompt_cache.pop(name, None)
        client.flush()
        version = getattr(prompt, "version", None)
        try:
            return int(version) if version is not None else None
        except (TypeError, ValueError):
            return None
    except Exception:
        logger.info("Langfuse prompt %s was not published", name)
        return None


def prompt_status(name: str, database_text: str | None) -> dict[str, Any]:
    live = production_prompt(name)
    if live:
        return {
            "agent": name,
            "source": "langfuse",
            "version": live[1],
            "label": "production",
            "text": live[0],
            "url": prompt_url(name),
        }
    if database_text:
        return {
            "agent": name,
            "source": "database",
            "version": None,
            "label": "published",
            "text": database_text,
            "url": prompt_url(name),
        }
    return {
        "agent": name,
        "source": "code",
        "version": None,
        "label": "default",
        "text": DEFAULT_PROMPTS.get(name, ""),
        "url": prompt_url(name),
    }
