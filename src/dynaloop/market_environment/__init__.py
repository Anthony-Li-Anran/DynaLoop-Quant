"""Market Environment: frozen definitions, registry, Wake/Sleep runtime, proxy.

Stage 3 adds the environment registry and runtime layer, a real (Wake) and a
simulated (Sleep) environment instance, a replaceable resampled backtest proxy
with uncertainty estimates, and a known-magnitude bias injection for
controlled experiments. Wake reuses stage 1's deterministic evaluations; the
backtest engine and Data module are untouched.
"""

from dynaloop.market_environment.definitions import (
    ArtifactReference,
    ArtifactType,
    EnvironmentDefinition,
    EnvironmentDefinitionError,
    EnvironmentReference,
    EnvironmentType,
    TimeRange,
)
from dynaloop.market_environment.feedback import (
    FEEDBACK_SCHEMA_VERSION,
    BiasReport,
    SimulatedEstimation,
    SimulationFeedback,
    compare_estimates,
    expected_bias_shift,
)
from dynaloop.market_environment.observations import (
    FrozenWindow,
    WakeObservation,
    factor_group_key,
    require_same_window,
    wake_observations,
)
from dynaloop.market_environment.proxy import (
    BOOTSTRAP_CLASSES,
    PROXY_SCHEMA_VERSION,
    BacktestProxy,
    BiasInjection,
    ProxyCalibration,
    ProxyConfig,
    ProxyError,
    ResampledBacktestProxy,
    proxy_library_versions,
)
from dynaloop.market_environment.registry import (
    ENVIRONMENT_SCHEMA_VERSION,
    EnvironmentRegistry,
    EnvironmentRegistryError,
    definition_payload,
)
from dynaloop.market_environment.runtime import (
    EnvironmentRuntimeError,
    EnvironmentRuntime,
    RealEnvironment,
    RuntimeSession,
    SimulatedEnvironment,
)

__all__ = [
    "BOOTSTRAP_CLASSES",
    "ENVIRONMENT_SCHEMA_VERSION",
    "FEEDBACK_SCHEMA_VERSION",
    "PROXY_SCHEMA_VERSION",
    "ArtifactReference",
    "ArtifactType",
    "BacktestProxy",
    "BiasInjection",
    "BiasReport",
    "EnvironmentDefinition",
    "EnvironmentDefinitionError",
    "EnvironmentReference",
    "EnvironmentRegistry",
    "EnvironmentRegistryError",
    "EnvironmentRuntime",
    "EnvironmentRuntimeError",
    "EnvironmentType",
    "FrozenWindow",
    "ProxyCalibration",
    "ProxyConfig",
    "ProxyError",
    "RealEnvironment",
    "ResampledBacktestProxy",
    "RuntimeSession",
    "SimulatedEnvironment",
    "SimulatedEstimation",
    "SimulationFeedback",
    "TimeRange",
    "WakeObservation",
    "compare_estimates",
    "definition_payload",
    "expected_bias_shift",
    "factor_group_key",
    "proxy_library_versions",
    "require_same_window",
    "wake_observations",
]
