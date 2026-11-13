"""When an automation runs next, and whether a schedule the model proposed is acceptable."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

MIN_MINUTES = 5
WATCH_MINUTES = 5

_TOO_OFTEN = f"Schedules must be at least {MIN_MINUTES} minutes apart."


def check_schedule(trigger: dict) -> str | None:
    """Error text for the model, or None when the schedule is fine."""
    every = trigger.get("every_minutes")
    if every is not None:
        if not isinstance(every, int) or isinstance(every, bool):
            return "every_minutes must be a whole number of minutes."
        return None if every >= MIN_MINUTES else _TOO_OFTEN
    cron = trigger.get("cron")
    if not isinstance(cron, str) or len(cron.split()) != 5 or not croniter.is_valid(cron):
        return "Give either every_minutes or a valid cron expression (5 fields) with a timezone."
    try:
        tz = ZoneInfo(trigger.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return "That time zone is not recognised. Use a name like Asia/Kolkata."
    # Gaps under 5 minutes can only come from the minute and hour fields, so ignore date fields (conservative:
    # may refuse a date-limited cron that never fires twice close together) and scan a fixed two days, not "now".
    minute, hour = cron.split()[:2]
    it = croniter(f"{minute} {hour} * * *", datetime(2024, 1, 1, tzinfo=tz))
    end = datetime(2024, 1, 3, tzinfo=tz)
    prev = it.get_next(datetime)
    while (cur := it.get_next(datetime)) < end:
        if cur - prev < timedelta(minutes=MIN_MINUTES):
            return _TOO_OFTEN
        prev = cur
    return None


def next_run(trigger_kind: str, trigger: dict, after: datetime) -> datetime | None:
    if trigger_kind == "watch":
        return after + timedelta(minutes=WATCH_MINUTES)
    if trigger_kind != "schedule":
        return None
    if "every_minutes" in trigger:
        return after + timedelta(minutes=trigger["every_minutes"])
    tz = ZoneInfo(trigger.get("timezone") or "UTC")
    return croniter(trigger["cron"], after.astimezone(tz)).get_next(datetime).astimezone(UTC)
