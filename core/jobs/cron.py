"""core/jobs/cron.py

Timezone-Aware Cron and Wall-Clock Evaluation Engine (Task R4.7).
Part of Milestone R4 (Task R4.7 - Timezone-Aware Scheduler).

Governing Principles:
- IANA Timezones Only: Validates and enforces canonical IANA identifiers (e.g. Europe/Berlin,
  America/New_York, Asia/Dhaka) using zoneinfo.ZoneInfo. Rejects ambiguous offsets and abbreviations.
- Wall-Clock Recurrence: Evaluates recurring schedules in local wall-clock calendar time.
  Never steps by fixed 24-hour UTC timedelta across DST boundary transitions.
- Explicit DST Semantics:
  * Nonexistent local time (spring-forward gap): skipped deterministically.
  * Ambiguous local time (fall-back fold): materialized exactly once using fold=0 (first valid occurrence).
- Bounded Missed-Run Calculation: Accurately identifies missed occurrence instants between
  downtime bounds without unbounded execution storms.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set, Tuple
import zoneinfo
from zoneinfo import ZoneInfo

from core.jobs.exceptions import InvalidScheduleExpressionError, InvalidTimezoneError

# Explicitly banned legacy or ambiguous timezone abbreviations and offsets
BANNED_TZ_PREFIXES_AND_ABBREVIATIONS = {
    "UTC+",
    "UTC-",
    "GMT+",
    "GMT-",
    "ETC/GMT+",
    "ETC/GMT-",
    "CET",
    "CEST",
    "EET",
    "EEST",
    "WET",
    "WEST",
    "EST",
    "EDT",
    "CST",
    "CDT",
    "MST",
    "MDT",
    "PST",
    "PDT",
    "MET",
}


def validate_iana_timezone(tz_name: str) -> ZoneInfo:
    """Validate that tz_name is a recognized, unambiguous IANA timezone.

    Raises:
        InvalidTimezoneError: If tz_name is invalid, empty, or an unsupported offset/abbreviation.
    """
    if not tz_name or not isinstance(tz_name, str):
        raise InvalidTimezoneError("Timezone identifier must be a non-empty string.")

    cleaned = tz_name.strip()
    upper = cleaned.upper()

    if "+" in cleaned or ("-" in cleaned and not cleaned.startswith("Etc/")):
        raise InvalidTimezoneError(
            f"Invalid timezone '{tz_name}': raw UTC offsets do not encode DST rules. Use IANA identifier."
        )

    for banned in BANNED_TZ_PREFIXES_AND_ABBREVIATIONS:
        if upper == banned or upper.startswith(banned):
            raise InvalidTimezoneError(
                f"Invalid timezone '{tz_name}': ambiguous abbreviation or fixed offset. Use canonical IANA identifier."
            )

    try:
        tz = ZoneInfo(cleaned)
        # Check against available timezones if available
        available = zoneinfo.available_timezones()
        if available and cleaned not in available and cleaned != "UTC":
            # Some platforms allow system symlinks; require valid tz database entry
            raise InvalidTimezoneError(
                f"Timezone '{tz_name}' is not in the IANA timezone database."
            )
        return tz
    except (zoneinfo.ZoneInfoNotFoundError, Exception) as ex:
        if isinstance(ex, InvalidTimezoneError):
            raise
        raise InvalidTimezoneError(f"Invalid or unrecognized IANA timezone: '{tz_name}'.") from ex


class ParsedCron:
    """Parsed representation of a 5-field standard cron expression."""

    def __init__(
        self,
        raw_expression: str,
        minutes: Set[int],
        hours: Set[int],
        days_of_month: Set[int],
        months: Set[int],
        days_of_week: Set[int],
        dom_is_wildcard: bool,
        dow_is_wildcard: bool,
    ):
        self.raw_expression = raw_expression
        self.minutes = minutes
        self.hours = hours
        self.days_of_month = days_of_month
        self.months = months
        self.days_of_week = days_of_week
        self.dom_is_wildcard = dom_is_wildcard
        self.dow_is_wildcard = dow_is_wildcard

    def matches(self, dt: datetime) -> bool:
        """Check if local datetime dt matches all cron fields."""
        if dt.minute not in self.minutes:
            return False
        if dt.hour not in self.hours:
            return False
        if dt.month not in self.months:
            return False

        # Day of month & day of week matching logic
        # In Python: Monday is 0, Sunday is 6.
        # In standard cron: Sunday is 0, Monday is 1, ..., Saturday is 6.
        cron_dow = (dt.weekday() + 1) % 7
        dom_match = dt.day in self.days_of_month
        dow_match = cron_dow in self.days_of_week

        if self.dom_is_wildcard and self.dow_is_wildcard:
            return True
        elif not self.dom_is_wildcard and self.dow_is_wildcard:
            return dom_match
        elif self.dom_is_wildcard and not self.dow_is_wildcard:
            return dow_match
        else:
            # Standard Vixie cron semantics: OR if both are specified
            return dom_match or dow_match


def _parse_field(field_str: str, min_val: int, max_val: int, field_name: str) -> Set[int]:
    """Parse a single cron field with support for *, */step, ranges, and comma-separated lists."""
    field_str = field_str.strip()
    if not field_str:
        raise InvalidScheduleExpressionError(f"Empty cron field: {field_name}")

    result: Set[int] = set()

    for part in field_str.split(","):
        part = part.strip()
        if not part:
            raise InvalidScheduleExpressionError(f"Invalid empty item in cron field: {field_name}")

        if "/" in part:
            subparts = part.split("/")
            if len(subparts) != 2:
                raise InvalidScheduleExpressionError(
                    f"Invalid step syntax in {field_name}: '{part}'"
                )
            range_part, step_str = subparts
            try:
                step = int(step_str)
                if step <= 0:
                    raise ValueError
            except ValueError:
                raise InvalidScheduleExpressionError(
                    f"Invalid step value in {field_name}: '{step_str}'"
                )

            if range_part == "*":
                start, end = min_val, max_val
            elif "-" in range_part:
                r_start_str, r_end_str = range_part.split("-", 1)
                try:
                    start, end = int(r_start_str), int(r_end_str)
                except ValueError:
                    raise InvalidScheduleExpressionError(
                        f"Invalid range in {field_name}: '{range_part}'"
                    )
            else:
                try:
                    start = int(range_part)
                    end = max_val
                except ValueError:
                    raise InvalidScheduleExpressionError(
                        f"Invalid range start in {field_name}: '{range_part}'"
                    )

            if start < min_val or end > max_val or start > end:
                raise InvalidScheduleExpressionError(
                    f"Range {start}-{end} out of bounds ({min_val}-{max_val}) for {field_name}"
                )
            result.update(range(start, end + 1, step))

        elif "-" in part:
            r_start_str, r_end_str = part.split("-", 1)
            try:
                start, end = int(r_start_str), int(r_end_str)
            except ValueError:
                raise InvalidScheduleExpressionError(f"Invalid range in {field_name}: '{part}'")
            if start < min_val or end > max_val or start > end:
                raise InvalidScheduleExpressionError(
                    f"Range {start}-{end} out of bounds ({min_val}-{max_val}) for {field_name}"
                )
            result.update(range(start, end + 1))

        elif part == "*":
            result.update(range(min_val, max_val + 1))

        else:
            try:
                val = int(part)
            except ValueError:
                raise InvalidScheduleExpressionError(f"Invalid number in {field_name}: '{part}'")
            if val < min_val or val > max_val:
                raise InvalidScheduleExpressionError(
                    f"Value {val} out of bounds ({min_val}-{max_val}) for {field_name}"
                )
            result.add(val)

    return result


def parse_cron_expression(expression: str) -> ParsedCron:
    """Parse standard 5-field cron syntax: 'minute hour day_of_month month day_of_week'.

    Raises:
        InvalidScheduleExpressionError: If syntax is invalid or fields are out of bounds.
    """
    if not expression or not isinstance(expression, str):
        raise InvalidScheduleExpressionError("Cron expression must be a non-empty string.")

    tokens = expression.strip().split()
    if len(tokens) != 5:
        raise InvalidScheduleExpressionError(
            f"Invalid cron expression '{expression}': expected exactly 5 fields, found {len(tokens)}."
        )

    m_str, h_str, dom_str, mon_str, dow_str = tokens

    minutes = _parse_field(m_str, 0, 59, "minute")
    hours = _parse_field(h_str, 0, 23, "hour")
    days_of_month = _parse_field(dom_str, 1, 31, "day_of_month")
    months = _parse_field(mon_str, 1, 12, "month")
    days_of_week = _parse_field(dow_str, 0, 7, "day_of_week")

    # In cron, 7 is also Sunday (0)
    if 7 in days_of_week:
        days_of_week.discard(7)
        days_of_week.add(0)

    return ParsedCron(
        raw_expression=expression,
        minutes=minutes,
        hours=hours,
        days_of_month=days_of_month,
        months=months,
        days_of_week=days_of_week,
        dom_is_wildcard=(dom_str == "*"),
        dow_is_wildcard=(dow_str == "*"),
    )


def validate_cron_expression(expression: str) -> None:
    """Validate standard 5-field cron syntax.

    Raises:
        InvalidScheduleExpressionError: If syntax is invalid or fields are out of bounds.
    """
    parse_cron_expression(expression)


def get_next_occurrence(
    cron_expression: str,
    tz_name: str,
    after_dt: Optional[datetime] = None,
    inclusive: bool = False,
) -> Tuple[datetime, datetime]:
    """Calculate the next occurrence strictly after after_dt in local wall-clock and UTC.

    DST Guarantees:
    - Nonexistent local time (spring-forward gap): skipped automatically.
    - Ambiguous local time (fall-back fold): resolved deterministically to fold=0 (first instance).

    Returns:
        (scheduled_for_utc, scheduled_for_local) tuple.

    Raises:
        InvalidScheduleExpressionError: On invalid cron syntax or no occurrence in 5 years.
        InvalidTimezoneError: On invalid timezone.
    """
    tz = validate_iana_timezone(tz_name)
    cron = parse_cron_expression(cron_expression)

    if after_dt is None:
        after_dt = datetime.now(timezone.utc)
    elif after_dt.tzinfo is None:
        after_dt = after_dt.replace(tzinfo=timezone.utc)

    # Convert after_dt to local time
    after_local = after_dt.astimezone(tz)
    after_utc = after_dt.astimezone(timezone.utc)

    # Start checking from current minute if inclusive and on whole minute, else next minute
    if inclusive and after_local.second == 0 and after_local.microsecond == 0:
        curr = after_local.replace(second=0, microsecond=0)
    else:
        curr = after_local.replace(second=0, microsecond=0) + timedelta(minutes=1)

    max_steps = 5 * 366 * 24 * 60  # 5 years maximum search window
    steps = 0

    while steps < max_steps:
        # Optimization: jump forward when months or days don't match
        if curr.month not in cron.months:
            # Advance to next month 1st at 00:00
            if curr.month == 12:
                curr = datetime(curr.year + 1, 1, 1, 0, 0, tzinfo=tz)
            else:
                curr = datetime(curr.year, curr.month + 1, 1, 0, 0, tzinfo=tz)
            steps += 60 * 24
            continue

        cron_dow = (curr.weekday() + 1) % 7
        dom_match = curr.day in cron.days_of_month
        dow_match = cron_dow in cron.days_of_week
        day_matches = (
            True
            if (cron.dom_is_wildcard and cron.dow_is_wildcard)
            else (
                dom_match
                if (not cron.dom_is_wildcard and cron.dow_is_wildcard)
                else (
                    dow_match
                    if (cron.dom_is_wildcard and not cron.dow_is_wildcard)
                    else (dom_match or dow_match)
                )
            )
        )

        if not day_matches:
            # Advance to tomorrow at 00:00
            curr_naive = curr.replace(tzinfo=None)
            next_day_naive = datetime(
                curr_naive.year, curr_naive.month, curr_naive.day
            ) + timedelta(days=1)
            curr = next_day_naive.replace(tzinfo=tz)
            steps += 60 * 24
            continue

        if curr.hour not in cron.hours:
            # Advance to next hour at 00
            curr_naive = curr.replace(tzinfo=None)
            next_hr_naive = datetime(
                curr_naive.year, curr_naive.month, curr_naive.day, curr_naive.hour
            ) + timedelta(hours=1)
            curr = next_hr_naive.replace(tzinfo=tz)
            steps += 60
            continue

        if curr.minute in cron.minutes:
            # Matched candidate! Check DST validity.
            naive = curr.replace(tzinfo=None)
            # fold=0 deterministically picks the first valid occurrence on fall-back fold
            loc = naive.replace(tzinfo=tz, fold=0)

            # Detect spring-forward gap: round-trip must match naive wall-clock
            rt = loc.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
            if rt == naive:
                occ_utc = loc.astimezone(timezone.utc)
                if occ_utc >= after_utc if inclusive else occ_utc > after_utc:
                    return (occ_utc, loc)

        curr = curr + timedelta(minutes=1)
        steps += 1

    raise InvalidScheduleExpressionError(
        f"Cron expression '{cron_expression}' produced no valid occurrence within 5 years in timezone '{tz_name}'."
    )


def get_missed_occurrences(
    cron_expression: str,
    tz_name: str,
    since_dt: datetime,
    up_to_dt: datetime,
    max_occurrences: int = 1000,
) -> List[Tuple[datetime, datetime]]:
    """Calculate all scheduled occurrences that should have occurred in the half-open window:

        since_dt < scheduled_for_utc <= up_to_dt

    Returns:
        List of (scheduled_for_utc, scheduled_for_local) sorted chronologically.
    """
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=timezone.utc)
    if up_to_dt.tzinfo is None:
        up_to_dt = up_to_dt.replace(tzinfo=timezone.utc)

    if since_dt >= up_to_dt:
        return []

    occurrences: List[Tuple[datetime, datetime]] = []
    current_search = since_dt

    while len(occurrences) < max_occurrences:
        try:
            next_utc, next_local = get_next_occurrence(
                cron_expression, tz_name, after_dt=current_search
            )
        except Exception:
            break

        if next_utc > up_to_dt:
            break

        occurrences.append((next_utc, next_local))
        current_search = next_utc

    return occurrences
