"""The loop that starts due schedule and watch automations."""
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.automations import run, watch
from app.automations.schedule import next_run
from app.db.base import session_factory
from app.db.models import Agent, Automation

logger = logging.getLogger(__name__)

TICK_SECONDS = 30
CONCURRENT = 3

_task: asyncio.Task | None = None
_slots = asyncio.Semaphore(CONCURRENT)

CLAIM = text("UPDATE automations SET next_run_at = :next WHERE id = :id AND next_run_at = :old RETURNING id")


async def _claim(automation: Automation, now: datetime) -> bool:
    """Moves the next run forward; only one of several overlapping ticks gets to do it."""
    async with session_factory() as db:
        claimed = await db.execute(CLAIM, {
            "next": next_run(automation.trigger_kind, automation.trigger, now), "id": automation.id, "old": automation.next_run_at})
        await db.commit()
        return claimed.first() is not None


async def _bounded(coro) -> None:
    async with _slots:
        await coro


async def tick(now: datetime) -> int:
    """Starts what is due in the background and returns how many runs it started."""
    async with session_factory() as db:
        due = (await db.scalars(select(Automation).join(Agent, Agent.id == Automation.agent_id).where(
            Automation.status == "active", Agent.status == "live", Automation.trigger_kind.in_(("schedule", "watch")),
            Automation.next_run_at <= now))).all()
    started = 0
    for automation in due:  # each on its own: one failing must not drop the others, whose next run is already moved
        try:
            if not await _claim(automation, now):
                continue
            if automation.trigger_kind == "schedule":
                run.spawn_run(_bounded(run.run_automation(automation.id, "schedule", wait=False)))
                started += 1
                continue
            for key, item in await watch.check(automation):
                run.spawn_run(_bounded(run.run_automation(automation.id, "watch", event=run.bounded_event(item), event_key=key, wait=True)))
                started += 1
        except Exception as exc:  # only the type: errors can carry details
            logger.warning("An automation could not be started: %s", type(exc).__name__)
    return started


async def _loop() -> None:
    while True:
        try:
            await tick(datetime.now(UTC))
        except Exception as exc:  # only the type: errors can carry details
            logger.warning("The scheduler tick failed: %s", type(exc).__name__)
        await asyncio.sleep(TICK_SECONDS)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
