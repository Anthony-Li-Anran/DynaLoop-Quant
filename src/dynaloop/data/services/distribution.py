"""Deterministic single-column distribution summaries for visualization.

Fixed, reproducible rules; no adaptive behavior:

- Missing values follow the same marker set as CSV preview (blank + common
  markers, case-insensitive) so charts agree with the profile table.
- Numeric columns use Sturges' rule k = ceil(log2(n)) + 1 with equal-width
  bins over [min, max], clamped to at most 64 bins. The rightmost edge is
  closed so max always falls in the last bin; empty bins are reported.
- Non-numeric columns are counted by exact text value, sorted by descending
  count then ascending value (deterministic), keeping the top 20 and
  aggregating the remainder under other_count.

These rules are part of the module's reproducible behavior; change them only
with an explicit rule version bump in callers that persist them.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from dynaloop.data.domain.errors import DataDefinitionError

# Keep aligned with the CSV preview missing markers in services.acquisition.
_MISSING_TOKENS = {"", ".", "na", "n/a", "nan", "null", "none"}
_NUMERIC = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
HISTOGRAM_BIN_CAP = 64
DEFAULT_MAX_CATEGORIES = 20
HISTOGRAM_RULE = "sturges-equal-width"


@dataclass(frozen=True, slots=True)
class DistributionBin:
    """One equal-width histogram bin; empty bins are included."""

    lower: float
    upper: float
    count: int


@dataclass(frozen=True, slots=True)
class CategoryCount:
    """One observed text value and its count."""

    value: str
    count: int


@dataclass(frozen=True, slots=True)
class ColumnDistribution:
    """Immutable single-column distribution summary for one partition."""

    column: str
    kind: str  # "histogram" | "categories" | "empty"
    observed_count: int
    missing_count: int
    rule: str
    bins: tuple[DistributionBin, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    categories: tuple[CategoryCount, ...] = ()
    other_count: int = 0


def summarize_column_distribution(
    records: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
    column: str,
    *,
    max_categories: int = DEFAULT_MAX_CATEGORIES,
) -> ColumnDistribution:
    """Summarize one column over complete records with fixed rules."""
    if (
        not isinstance(column, str)
        or not column.strip()
        or column != column.strip()
    ):
        raise DataDefinitionError("column must be a non-empty, trimmed string.")
    if type(max_categories) is not int or max_categories < 1:
        raise DataDefinitionError("max_categories must be a positive integer.")
    rows = tuple(records)
    if rows and all(column not in row for row in rows):
        raise DataDefinitionError(f"Column '{column}' is not present in the records.")

    observed: list[str] = []
    missing_count = 0
    for row in rows:
        value = row.get(column)
        if value is not None and not isinstance(value, str):
            raise DataDefinitionError(
                f"Column '{column}' contains a non-text value; "
                "distributions support text records only."
            )
        if value is None or value.strip().casefold() in _MISSING_TOKENS:
            missing_count += 1
        else:
            observed.append(value.strip())

    if not observed:
        return ColumnDistribution(
            column=column,
            kind="empty",
            observed_count=0,
            missing_count=missing_count,
            rule="no-observed-values",
        )

    numbers = _parse_numbers(observed)
    if numbers is not None:
        return _histogram(column, observed, numbers, missing_count)
    return _categories(column, observed, missing_count, max_categories)


def _parse_numbers(observed: tuple[str, ...] | list[str]) -> list[float] | None:
    """Return parsed finite numbers, or None if any value is non-numeric."""
    numbers: list[float] = []
    for value in observed:
        if not _NUMERIC.fullmatch(value):
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return numbers


def _histogram(
    column: str,
    observed: list[str],
    numbers: list[float],
    missing_count: int,
) -> ColumnDistribution:
    minimum = min(numbers)
    maximum = max(numbers)
    mean = math.fsum(numbers) / len(numbers)
    bin_count = min(HISTOGRAM_BIN_CAP, max(1, math.ceil(math.log2(len(numbers))) + 1))
    if minimum == maximum:
        bins = (DistributionBin(minimum, maximum, len(numbers)),)
    else:
        width = (maximum - minimum) / bin_count
        counts = [0] * bin_count
        for number in numbers:
            index = min(int((number - minimum) / width), bin_count - 1)
            counts[index] += 1
        bins = tuple(
            DistributionBin(
                lower=minimum + index * width,
                upper=minimum + (index + 1) * width if index < bin_count - 1 else maximum,
                count=counts[index],
            )
            for index in range(bin_count)
        )
    return ColumnDistribution(
        column=column,
        kind="histogram",
        observed_count=len(observed),
        missing_count=missing_count,
        rule=f"{HISTOGRAM_RULE};k={len(bins)}",
        bins=bins,
        minimum=minimum,
        maximum=maximum,
        mean=mean,
    )


def _categories(
    column: str,
    observed: list[str],
    missing_count: int,
    max_categories: int,
) -> ColumnDistribution:
    counts = Counter(observed)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    kept = tuple(
        CategoryCount(value, count) for value, count in ordered[:max_categories]
    )
    other_count = sum(count for _, count in ordered[max_categories:])
    return ColumnDistribution(
        column=column,
        kind="categories",
        observed_count=len(observed),
        missing_count=missing_count,
        rule=f"top-{max_categories}-by-count",
        categories=kept,
        other_count=other_count,
    )
