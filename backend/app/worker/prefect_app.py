"""Prefect runner — starts a long-running server that hosts all flow deployments.

Run with:
    python -m app.worker.prefect_app

The process registers scheduled deployments with the Prefect server and polls for
work.  Set PREFECT_API_URL to http://prefect-server:4200/api (self-hosted Docker)
or to your Prefect Cloud workspace URL + PREFECT_API_KEY for Cloud mode.
"""

import asyncio
import logging

from prefect import aserve
from prefect.client.schemas.schedules import IntervalSchedule

from app.worker.tasks.profassist_tasks import grade_batch_flow
from app.worker.tasks.rag_tasks import (
    check_scheduled_syncs_flow,
    ingest_document_flow,
    sync_collection_flow,
    sync_single_source_flow,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Register all deployments and serve them."""
    deployments = []
    # On-demand: triggered from API on file upload
    deployments.append(await ingest_document_flow.ato_deployment(name="ingest-document"))
    deployments.append(await sync_single_source_flow.ato_deployment(name="sync-single-source"))
    deployments.append(await sync_collection_flow.ato_deployment(name="sync-collection"))
    deployments.append(await grade_batch_flow.ato_deployment(name="profassist-grade-batch"))
    # Scheduled: check connector sources every minute
    deployments.append(
        await check_scheduled_syncs_flow.ato_deployment(
            name="rag-sync-check",
            schedules=[IntervalSchedule(interval=60)],
        )
    )
    logger.info("Starting Prefect runner with %d deployments", len(deployments))
    await aserve(*deployments)


if __name__ == "__main__":
    asyncio.run(main())
