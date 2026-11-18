"""Immutable market environment definitions and external references."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum


class EnvironmentDefinitionError(ValueError):
    """Raised when a market environment definition is invalid."""


class EnvironmentType(Enum):
    """Supported market environment categories."""

    REAL = "real"
    SIMULATED = "simulated"


class ArtifactType(Enum):
    """External artifact categories that an environment may reference."""

    DATASET = "dataset"
    MODEL = "model"
    CALIBRATION = "calibration"


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise EnvironmentDefinitionError(f"{field_name} must be a non-empty, trimmed string.")
    return value


def _immutable_texts(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise EnvironmentDefinitionError(f"{field_name} must be a tuple or list of strings.")
    result = tuple(values)
    for value in result:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise EnvironmentDefinitionError(
                f"Each {field_name} entry must be a non-empty, trimmed string."
            )
    return result


@dataclass(frozen=True, slots=True)
class EnvironmentReference:
    """Explicit, stable reference to one environment definition version."""

    environment_id: str
    version: str

    def __post_init__(self) -> None:
        _require_identifier(self.environment_id, "environment_id")
        _require_identifier(self.version, "version")


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Optional left-closed, right-open range ``[start, end)``.

    Both endpoints must be dates or both must be timezone-aware datetimes.
    End must be later than start; endpoint values are not normalized.
    """

    start: date | datetime
    end: date | datetime

    def __post_init__(self) -> None:
        if not isinstance(self.start, date) or not isinstance(self.end, date):
            raise EnvironmentDefinitionError(
                "Time range start and end must both be dates or both be datetimes."
            )
        start_is_datetime = isinstance(self.start, datetime)
        end_is_datetime = isinstance(self.end, datetime)
        if start_is_datetime != end_is_datetime:
            raise EnvironmentDefinitionError(
                "Time range start and end must both be dates or both be datetimes."
            )
        if start_is_datetime:
            if self.start.utcoffset() is None or self.end.utcoffset() is None:
                raise EnvironmentDefinitionError("Datetime range endpoints must be timezone-aware.")
            ordered = self.end.astimezone(timezone.utc) > self.start.astimezone(timezone.utc)
        else:
            ordered = self.end > self.start
        if not ordered:
            raise EnvironmentDefinitionError("Time range end must be later than its start.")


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Reference to an externally owned artifact; does not resolve or load it."""

    artifact_type: ArtifactType
    artifact_id: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_type, ArtifactType):
            raise EnvironmentDefinitionError("artifact_type must be a supported ArtifactType.")
        _require_identifier(self.artifact_id, "artifact_id")
        _require_identifier(self.version, "version")


@dataclass(frozen=True, slots=True)
class EnvironmentDefinition:
    """Immutable description of a real or simulated market environment.

    Empty descriptive fields mean no information was provided; they do not
    assert that the environment has no conditions or limitations. External
    artifact references identify associations only and are not resolved.
    Creators must ensure that an environment ID and version always identify
    the same definition; no registry is maintained by this module.
    """

    environment_id: str
    version: str
    environment_type: EnvironmentType
    source: str | None = None
    time_range: TimeRange | None = None
    applicability: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    artifact_references: tuple[ArtifactReference, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.environment_id, "environment_id")
        _require_identifier(self.version, "version")
        if not isinstance(self.environment_type, EnvironmentType):
            raise EnvironmentDefinitionError(
                "environment_type must be a supported EnvironmentType."
            )
        if self.source is not None:
            _require_identifier(self.source, "source")
        if self.time_range is not None and not isinstance(self.time_range, TimeRange):
            raise EnvironmentDefinitionError("time_range must be a TimeRange or None.")

        object.__setattr__(self, "applicability", _immutable_texts(self.applicability, "applicability"))
        object.__setattr__(self, "limitations", _immutable_texts(self.limitations, "limitations"))

        if not isinstance(self.artifact_references, (tuple, list)):
            raise EnvironmentDefinitionError(
                "artifact_references must be a tuple or list of ArtifactReference values."
            )
        references = tuple(self.artifact_references)
        if any(not isinstance(reference, ArtifactReference) for reference in references):
            raise EnvironmentDefinitionError(
                "artifact_references entries must be ArtifactReference values."
            )
        object.__setattr__(self, "artifact_references", references)

    @property
    def reference(self) -> EnvironmentReference:
        """Return the identity and version used to reference this definition."""
        return EnvironmentReference(self.environment_id, self.version)


__all__ = [
    "ArtifactReference",
    "ArtifactType",
    "EnvironmentDefinition",
    "EnvironmentDefinitionError",
    "EnvironmentReference",
    "EnvironmentType",
    "TimeRange",
]
