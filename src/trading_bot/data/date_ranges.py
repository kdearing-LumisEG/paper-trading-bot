"""Date parsing and monthly chunk generation for historical downloads."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone


@dataclass(frozen=True)
class DateRangeChunk:
    """A timezone-aware interval with an exclusive end time."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Validate the chunk boundaries."""

        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Chunk boundaries must be timezone-aware.")

        if self.start >= self.end:
            raise ValueError("Chunk start must occur before chunk end.")


def parse_iso_date(
    value: str,
    field_name: str = "date",
) -> date:
    """Parse a date in YYYY-MM-DD format."""

    cleaned_value = value.strip()

    if not cleaned_value:
        raise ValueError(f"{field_name} cannot be empty.")

    try:
        parsed_date = date.fromisoformat(cleaned_value)
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must use YYYY-MM-DD format."
        ) from exc

    return parsed_date


def parse_date_range(
    start_value: str,
    end_value: str,
) -> tuple[date, date]:
    """Parse and validate an inclusive user-facing date range."""

    start_date = parse_iso_date(
        start_value,
        field_name="start",
    )

    end_date = parse_iso_date(
        end_value,
        field_name="end",
    )

    if start_date >= end_date:
        raise ValueError(
            "start must occur before end."
        )

    return start_date, end_date


def _first_day_of_next_month(value: datetime) -> datetime:
    """Return midnight UTC on the first day of the next month."""

    if value.month == 12:
        return datetime(
            value.year + 1,
            1,
            1,
            tzinfo=timezone.utc,
        )

    return datetime(
        value.year,
        value.month + 1,
        1,
        tzinfo=timezone.utc,
    )


def build_monthly_chunks(
    start_date: date,
    end_date: date,
) -> list[DateRangeChunk]:
    """Split an inclusive date range into monthly UTC chunks.

    The caller-facing end date is inclusive. Each returned chunk uses
    an exclusive end datetime so adjacent chunks share no timestamps.
    """

    if start_date >= end_date:
        raise ValueError(
            "start must occur before end."
        )

    overall_start = datetime.combine(
        start_date,
        time.min,
        tzinfo=timezone.utc,
    )

    overall_end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )

    chunks: list[DateRangeChunk] = []
    current_start = overall_start

    while current_start < overall_end_exclusive:
        next_month = _first_day_of_next_month(
            current_start
        )

        current_end = min(
            next_month,
            overall_end_exclusive,
        )

        chunks.append(
            DateRangeChunk(
                start=current_start,
                end=current_end,
            )
        )

        current_start = current_end

    return chunks