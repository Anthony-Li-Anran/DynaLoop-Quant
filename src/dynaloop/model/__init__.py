"""Model: pluggable candidate generators and the factor expression grammar.

Stage 2. Expression trees are built with DEAP's typed primitive sets and
gplearn's function-set declarations; every emitted string is re-parsed by
``research_engine`` before it becomes a ``FactorCandidate``. ``CandidateGenerator``
is the public replacement point for a future LM-based generator.
"""

from dynaloop.model.grammar import (
    DEFAULT_DEPTH,
    DEFAULT_METHOD,
    DEFAULT_NUMERIC_PRIMITIVES,
    DEFAULT_TEMPLATES,
    GRAMMAR_SCHEMA_VERSION,
    SERIES,
    WINDOW,
    FactorGrammar,
    FactorTemplate,
    GrammarError,
    Primitive,
    PrimitiveSet,
    TemplateInstance,
    available_templates,
    build_primitive_set,
    default_grammar,
    describe_primitive_set,
    function_set,
    generate_expression,
    primitive_arg_types,
    template_choice_keys,
)
from dynaloop.model.generators import (
    GENERATOR_REGISTRY,
    GENERATOR_SCHEMA_VERSION,
    CandidateGenerator,
    GeneratedCandidate,
    GenerationRequest,
    GrammarCandidateGenerator,
    TemplateCandidateGenerator,
    build_generator,
    register_generator,
)

__all__ = [
    "BrainConfig",
    "LoopedTransformer",
    "DEFAULT_DEPTH",
    "DEFAULT_METHOD",
    "DEFAULT_NUMERIC_PRIMITIVES",
    "DEFAULT_TEMPLATES",
    "GENERATOR_REGISTRY",
    "GENERATOR_SCHEMA_VERSION",
    "GRAMMAR_SCHEMA_VERSION",
    "SERIES",
    "WINDOW",
    "CandidateGenerator",
    "FactorGrammar",
    "FactorTemplate",
    "GeneratedCandidate",
    "GenerationRequest",
    "GrammarCandidateGenerator",
    "GrammarError",
    "Primitive",
    "PrimitiveSet",
    "TemplateCandidateGenerator",
    "TemplateInstance",
    "available_templates",
    "build_generator",
    "build_primitive_set",
    "default_grammar",
    "describe_primitive_set",
    "function_set",
    "generate_expression",
    "primitive_arg_types",
    "register_generator",
    "template_choice_keys",
]


def __getattr__(name):
    if name in {"BrainConfig", "LoopedTransformer"}:
        from dynaloop.model import brain
        return getattr(brain, name)
    raise AttributeError(name)
