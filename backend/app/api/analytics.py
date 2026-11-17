"""The Analytics page's numbers, read from PostHog by the backend for one of the user's agents."""
import asyncio
import datetime as dt
import math
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import posthog
from app.api.deps import get_owned_agent
from app.core import cache
from app.core.errors import ApiError
from app.db.base import get_db
from app.db.models import Agent, Automation
from app.integrations import composio
from app.tools.http import ToolError
from app.tools.registry import REGISTRY

router = APIRouter()

RANGES = {"7d": 7, "30d": 30, "90d": 90}
CACHE_SECONDS = 60

# Every query is limited to one agent of one user, over the period. All values are
# placeholders: nothing from the request is ever written into the query text. The period starts
# at the viewer's local midnight of the first day shown, so totals, tools and bars cover the
# same days (not "this hour, seven days ago").
_WHERE = "properties.agent_id = {agent_id} and distinct_id = {user_id} and timestamp >= toDateTime({start}, 'UTC')"
_FAILED = "toString(properties.success) != 'true'"
# The Chat tab leaves out automation runs' tool calls. Chat's own carry no source: a bare != would drop them.
_CHAT_TOOL = "event = 'tool_called' and ifNull(toString(properties.source), '') != 'automation'"

TOTALS = f"""
select
    countIf(event = 'session_started'),
    countIf(event = 'message_sent'),
    countIf({_CHAT_TOOL}),
    countIf({_CHAT_TOOL} and {_FAILED}),
    avgIf(toFloat(properties.duration_ms), {_CHAT_TOOL}),
    countIf(event = 'knowledge_base_searched'),
    countIf(event = 'write_action_decision' and properties.decision = 'approved'),
    countIf(event = 'write_action_decision' and properties.decision = 'rejected'),
    countIf(event = 'connection_expired'),
    countIf(event = 'document_ingested' and properties.status = 'ready')
from events
where {_WHERE}
"""

DAYS = f"""
select toDate(toTimeZone(timestamp, {{tz}})) as day, countIf(event = 'message_sent'), countIf({_CHAT_TOOL})
from events
where {_WHERE}
group by day
order by day
"""

TOOLS = f"""
select properties.tool_name as name, any(properties.tool_type), any(properties.app), count() as calls,
    countIf({_FAILED}), avg(toFloat(properties.duration_ms))
from events
where {_CHAT_TOOL} and {_WHERE}
group by name
order by calls desc
limit 500
"""


def _number(value) -> float:
    # ClickHouse answers NaN for an average over no rows; round() would raise on it.
    return float(value) if isinstance(value, int | float) and math.isfinite(value) else 0.0


def _shape(totals: list[list], days: list[list], tools: list[list], span: int, zone: ZoneInfo) -> dict:
    row = (totals or [[0] * 10])[0]
    sessions, messages, calls, failures, avg_ms, kb, approved, rejected, broken, documents = (_number(v) for v in row)
    by_day = {str(day)[:10]: (int(_number(m)), int(_number(t))) for day, m, t in days}
    today = dt.datetime.now(zone).date()  # the viewer's today, so this morning is not yesterday
    return {
        "totals": {
            "sessions": int(sessions), "messages": int(messages), "tool_calls": int(calls), "tool_failures": int(failures),
            "success_rate": round((calls - failures) / calls, 3) if calls else None,
            "avg_tool_ms": round(avg_ms) if calls else None,
            "kb_searches": int(kb), "approved": int(approved), "rejected": int(rejected),
            "connection_problems": int(broken), "documents": int(documents),
        },
        # Every day of the period, so a quiet day shows as zero rather than going missing.
        "days": [
            {"date": day, "messages": by_day.get(day, (0, 0))[0], "tool_calls": by_day.get(day, (0, 0))[1]}
            for day in ((today - dt.timedelta(days=offset)).isoformat() for offset in range(span - 1, -1, -1))
        ],
        "tools": _merge_tools(tools),
    }


def _display_name(name: str, kind: str | None, app: str | None) -> str:
    if kind == "composio" and app in composio.APPS:
        return composio.APPS[app].name
    if kind == "knowledge_base":
        return "Knowledge base"
    spec = REGISTRY.get(name)
    return spec.label if spec else name


def _merge_tools(tools: list[list]) -> list[dict]:
    """One row per app or tool, under the name the user knows: every Gmail action is one "Gmail" row."""
    rows: dict[str, dict] = {}
    for name, kind, app, count, failed, avg in tools:
        if not name:
            continue
        calls = int(_number(count))
        row = rows.setdefault(_display_name(name, kind, app), {"type": kind, "app": app, "calls": 0, "failures": 0, "total_ms": 0.0})
        row["calls"] += calls
        row["failures"] += int(_number(failed))
        row["total_ms"] += _number(avg) * calls
    merged = [
        {"name": shown, "type": row["type"], "app": row["app"], "calls": row["calls"], "failures": row["failures"],
         "avg_ms": round(row["total_ms"] / row["calls"]) if row["calls"] else 0}
        for shown, row in rows.items()
    ]
    return sorted(merged, key=lambda row: row["calls"], reverse=True)


AUTO_TOTALS = f"""
select
    countIf(event = 'automation_run' and properties.source != 'test'),
    countIf(event = 'automation_run' and properties.source != 'test' and toString(properties.success) = 'true'),
    countIf(event = 'automation_run' and properties.source = 'test'),
    avgIf(toFloat(properties.duration_ms), event = 'automation_run' and properties.source != 'test'),
    countIf(event = 'automation_created'),
    countIf(event = 'tool_called' and properties.source = 'automation')
from events
where {_WHERE}
"""

AUTO_DAYS = f"""
select toDate(toTimeZone(timestamp, {{tz}})) as day,
    countIf(event = 'automation_run' and properties.source != 'test' and toString(properties.success) = 'true'),
    countIf(event = 'automation_run' and properties.source != 'test' and {_FAILED})
from events
where {_WHERE}
group by day
order by day
"""

AUTO_TABLE = f"""
select properties.automation_id, countIf(properties.source != 'test'),
    countIf(properties.source != 'test' and {_FAILED}), countIf(properties.source = 'test'),
    avgIf(toFloat(properties.duration_ms), properties.source != 'test'), max(timestamp)
from events
where event = 'automation_run' and {_WHERE}
group by properties.automation_id
order by 2 desc
limit 50
"""


def _shape_automations(totals, days, table, span, zone, known: dict, active_now: int) -> dict:
    runs, succeeded, tests, avg_ms, created, tool_calls = (_number(v) for v in (totals or [[0] * 6])[0])
    by_day = {str(day)[:10]: (int(_number(ok)), int(_number(bad))) for day, ok, bad in days}
    today = dt.datetime.now(zone).date()
    return {
        "totals": {
            "runs": int(runs), "succeeded": int(succeeded),
            "success_rate": round(succeeded / runs, 3) if runs else None,
            "test_runs": int(tests), "avg_run_ms": round(avg_ms) if runs else None,
            "created": int(created), "tool_calls": int(tool_calls),
        },
        "days": [
            {"date": day, "succeeded": by_day.get(day, (0, 0))[0], "failed": by_day.get(day, (0, 0))[1]}
            for day in ((today - dt.timedelta(days=offset)).isoformat() for offset in range(span - 1, -1, -1))
        ],
        "automations": [
            {"id": str(id_), "name": known[str(id_)].name if str(id_) in known else "Deleted automation",
             "trigger_text": known[str(id_)].trigger_text if str(id_) in known else None,
             "status": known[str(id_)].status if str(id_) in known else "deleted",
             "runs": int(_number(n)), "failures": int(_number(failed)), "test_runs": int(_number(test)),
             "avg_ms": round(_number(avg)), "last_run_at": last}
            for id_, n, failed, test, avg, last in table if id_
        ],
        "active_now": active_now,
    }


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):  # OSError: a folder name such as "Asia" on Windows
        raise ApiError(422, "invalid_time_zone", "That time zone isn't recognised.") from None


async def _ask(agent: Agent, range_: str, tz: str, zone: ZoneInfo, queries: tuple[str, ...]) -> list:
    first_day = dt.datetime.now(zone).date() - dt.timedelta(days=RANGES[range_] - 1)
    start = dt.datetime.combine(first_day, dt.time(), zone).astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
    values = {"agent_id": str(agent.id), "user_id": str(agent.user_id), "tz": tz, "start": start}
    try:
        return await asyncio.gather(*(posthog.query(sql, values) for sql in queries))
    except ToolError as error:
        raise ApiError(503, "analytics_unavailable", "Analytics can't be reached right now. Try again in a moment.") from error


async def _remember(key: str, result: dict) -> dict:
    await cache.set_json(key, result, CACHE_SECONDS)
    return result


@router.get("/agents/{agent_id}/analytics")
async def agent_analytics(
    agent: Agent = Depends(get_owned_agent),
    range_: Literal["7d", "30d", "90d"] = Query("7d", alias="range"),
    tz: str = Query("UTC", max_length=64),  # the viewer's time zone: days are counted in it
) -> dict:
    zone = _zone(tz)
    if not posthog.queries_enabled():
        return {"enabled": False}
    key = f"analytics:{agent.id}:chat:{range_}:{tz}"
    if (remembered := await cache.get_json(key)) is not None:
        return remembered
    totals, days, tools = await _ask(agent, range_, tz, zone, (TOTALS, DAYS, TOOLS))
    return await _remember(key, {"enabled": True, "range": range_, **_shape(totals, days, tools, RANGES[range_], zone)})


@router.get("/agents/{agent_id}/analytics/automations")
async def automation_analytics(
    agent: Agent = Depends(get_owned_agent),
    db: AsyncSession = Depends(get_db),
    range_: Literal["7d", "30d", "90d"] = Query("7d", alias="range"),
    tz: str = Query("UTC", max_length=64),
) -> dict:
    zone = _zone(tz)
    if not posthog.queries_enabled():
        return {"enabled": False}
    key = f"analytics:{agent.id}:automations:{range_}:{tz}"
    if (remembered := await cache.get_json(key)) is not None:
        return remembered
    totals, days, table = await _ask(agent, range_, tz, zone, (AUTO_TOTALS, AUTO_DAYS, AUTO_TABLE))
    # Names and status are the database's, so a rename or pause shows at once and a deleted one is told apart.
    rows = (await db.scalars(select(Automation).where(Automation.agent_id == agent.id))).all()
    known = {str(row.id): row for row in rows}
    active_now = sum(row.status == "active" for row in rows)
    shaped = _shape_automations(totals, days, table, RANGES[range_], zone, known, active_now)
    return await _remember(key, {"enabled": True, "range": range_, **shaped})
