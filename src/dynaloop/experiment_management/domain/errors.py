"""Errors raised by Experiment Management domain and service boundaries."""


class ExperimentManagementError(Exception):
    """Base error for Experiment Management."""


class ExperimentDefinitionError(ExperimentManagementError, ValueError):
    """Raised when an experiment, run, or result definition is invalid."""


class ExperimentNotFoundError(ExperimentManagementError, LookupError):
    """Raised when an experiment or run cannot be found."""


class ExperimentIdentityConflictError(ExperimentManagementError):
    """Raised when an existing experiment ID is reused for another definition."""


class ExperimentRunConflictError(ExperimentManagementError):
    """Raised when an existing run ID or result is reused."""


class ExperimentRunTransitionError(ExperimentManagementError):
    """Raised when a run state transition is invalid."""
