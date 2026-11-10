"""The Analytics page's numbers, read from PostHog by the backend for one of the user's agents."""
import asyncio
import datetime as dt
import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query

from app.analytics import posthog
from app.api.deps import get_owned_agent
from app.core.errors import ApiError
from app.db.models import Agent
from app.tools.http import ToolError

router = APIRouter()

RANGES = {"7d": 7, "30d": 30, "90d": 90}
CACHE_SECONDS = 60
_cache: dict[tuple[str, str, str], tuple[float, dict]] = {}

# Every query is limited to one agent of one user, over the period. All values are
# placeholders: nothing from the request is ever written into the query text. The period starts
# at the viewer's local midnight of the first day shown, so totals, tools and bars cover the
# same days (not "this hour, seven days ago").
_WHERE = "properties.agent_id = {agent_id} and distinct_id = {user_id} and timestamp >= toDateTime({start}, 'UTC')"
_FAILED = "toString(properties.success) != 'true'"

TOTALS = f"""
select
    countIf(event = 'session_started'),
    countIf(event = 'message_sent'),
    countIf(event = 'tool_called'),
    countIf(event = 'tool_called' and {_FAILED}),
    avgIf(toFloat(properties.duration_ms), event = 'tool_called'),
    countIf(event = 'knowledge_base_searched'),
    countIf(event = 'write_action_decision' and properties.decision = 'approved'),
    countIf(event = 'write_action_decision' and properties.decision = 'rejected'),
    countIf(event = 'connection_expired'),
    countIf(event = 'document_ingested' and properties.status = 'ready')
from events
where {_WHERE}
"""

DAYS = f"""
select toDate(toTimeZone(timestamp, {{tz}})) as day, countIf(event = 'message_sent'), countIf(event = 'tool_called')
from events
where {_WHERE}
group by day
order by day
"""

TOOLS = f"""
select properties.tool_name as name, any(properties.tool_type), any(properties.app), count() as calls,
    countIf({_FAILED}), avg(toFloat(properties.duration_ms))
from events
where event = 'tool_called' and {_WHERE}
group by name
order by calls desc
limit 50
"""


def _number(value) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


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
        "tools": [
            {"name": name, "type": kind, "app": app, "calls": int(_number(count)), "failures": int(_number(failed)),
             "avg_ms": round(_number(avg))}
            for name, kind, app, count, failed, avg in tools if name
        ],
    }


@router.get("/agents/{agent_id}/analytics")
async def agent_analytics(
    agent: Agent = Depends(get_owned_agent),
    range_: Literal["7d", "30d", "90d"] = Query("7d", alias="range"),
    tz: str = Query("UTC", max_length=64),  # the viewer's time zone: days are counted in it
) -> dict:
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, OSError):  # OSError: a folder name such as "Asia" on Windows
        raise ApiError(422, "invalid_time_zone", "That time zone isn't recognised.") from None
    if not posthog.queries_enabled():
        return {"enabled": False}
    key = (str(agent.id), range_, tz)
    remembered = _cache.get(key)
    if remembered and remembered[0] > time.monotonic():
        return remembered[1]
    first_day = dt.datetime.now(zone).date() - dt.timedelta(days=RANGES[range_] - 1)
    start = dt.datetime.combine(first_day, dt.time(), zone).astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")
    values = {"agent_id": str(agent.id), "user_id": str(agent.user_id), "tz": tz, "start": start}
    try:
        totals, days, tools = await asyncio.gather(*(posthog.query(sql, values) for sql in (TOTALS, DAYS, TOOLS)))
    except ToolError as error:
        raise ApiError(503, "analytics_unavailable", "Analytics can't be reached right now. Try again in a moment.") from error
    result = {"enabled": True, "range": range_, **_shape(totals, days, tools, RANGES[range_], zone)}
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = (time.monotonic() + CACHE_SECONDS, result)
    return result
