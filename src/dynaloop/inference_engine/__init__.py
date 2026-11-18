"""Inference Engine: seeded group sampling of factor candidates.

Stage 2. A ``SamplingRequest`` plus a frozen ``ExplorationPolicy`` drive a
registered ``CandidateGenerator``; the output ``CandidateBatch`` is the
``f1..fN`` group consumed by Research Engine and Training Engine.
"""

from dynaloop.inference_engine.sampling import (
    SAMPLING_SCHEMA_VERSION,
    CandidateBatch,
    InferenceEngine,
    SamplingRequest,
)

__all__ = [
    "SAMPLING_SCHEMA_VERSION",
    "CandidateBatch",
    "InferenceEngine",
    "SamplingRequest",
]
