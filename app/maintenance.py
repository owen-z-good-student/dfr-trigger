import asyncio
import logging


logger = logging.getLogger(__name__)


async def cleanup_loop(audit_store, idempotency_store, retention_days: int) -> None:
    while True:
        try:
            audit_store.cleanup(retention_days)
        except Exception:
            logger.exception("audit cleanup failed")
        try:
            idempotency_store.cleanup()
        except Exception:
            logger.exception("idempotency cleanup failed")
        await asyncio.sleep(86_400)
