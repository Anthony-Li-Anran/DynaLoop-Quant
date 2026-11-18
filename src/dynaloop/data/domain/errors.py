"""Errors raised by Data domain definitions and access boundaries."""


class DataError(Exception):
    """Base class for errors owned by the Data module."""


class DataDefinitionError(DataError, ValueError):
    """Raised when a Data domain value is structurally invalid."""


class DataNotFoundError(DataError, LookupError):
    """Raised when a requested dataset or dataset version is unavailable."""


class DatasetVersionValidationError(DataDefinitionError):
    """Raised when DatasetVersion content or references are inconsistent."""


class DatasetSnapshotError(DataDefinitionError):
    """Raised when a snapshot contains invalid or inconsistent references."""


class DatasetVersionPublishError(DataError):
    """Base class for failures while preparing or publishing a version."""


class DatasetVersionPublishConflictError(DatasetVersionPublishError):
    """Raised when the expected Dataset Head no longer matches."""


class DatasetVersionCandidateNotFoundError(DatasetVersionPublishError, LookupError):
    """Raised when a requested unpublished version candidate does not exist."""


class DatasetVersionCandidateStateError(DatasetVersionPublishError):
    """Raised when a candidate is not in a state allowed for publication."""


class DatasetVersionIdentityConflictError(DatasetVersionPublishError):
    """Raised when a version reference is reused for a different definition."""


class QualityGateError(DatasetVersionPublishError):
    """Raised when an explicit quality gate fails and the version is retracted."""


class DatasetIdentityConflictError(DataError):
    """Raised when a dataset ID is reused for a different definition."""


class ContentIntegrityError(DataError):
    """Raised when staged or committed content fails integrity validation."""
