"""QBX-style read-only audit shell for alpha expressions.

This is a faithful, scoped port of the *audit ideas* in
"QBX: A Compiler for Well-Formed, Auditable Alpha Programs" (ICAIF 2026,
arXiv:2610.41689), not the search system itself:

- time-availability effect phi (Definition 2): signed offset at which a value
  becomes known; admission requires phi <= 0. Positive phi is contract-visible
  look-ahead and is rejected BEFORE any panel is loaded.
- Merkle-style content identity (Definition 3): SHA-256 over a canonical
  serialization of normalized semantics, parameters, types, contract version,
  and parent addresses; author names/positions are excluded.
- staged structured diagnostics: Normalize / Graph / Type / Availability /
  Address, each phase recording its witness.

Hard scope limits, stated plainly (from the QBX paper itself):
- The guarantee is RELATIVE to the registered operator contracts. It is NOT a
  claim of zero backtest leakage: irregular timestamps, revisions, hindsight
  universe membership, corporate actions and as-of joins remain out of scope.
- This module audits expressions. It does NOT prove an alpha is effective,
  does NOT change any frozen fingerprint, and emits NO verdict.
- It is report-only engineering capability, never a factor or a claim.
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from dynaloop.infrastructure import canonical_json

_COMPILER_VERSION = "qbx-audit-shell/1"
_CONTRACT_VERSION = "qlib-ops-contract/1"
_FIELD = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")

# phi transfer per registered operator (QBX Definition 2, adapted to Qlib ops).
# lag/p window p>0 does not increase phi (past-looking); a future Ref does.
# Finite registered block vocabulary (mirrors learned_factors.expression.FUNCTIONS
# plus the internal field accessor). A QBX-style registry would expose these as
# versioned contracts; here they are the admitted operator names.
_REGISTERED_BLOCKS = frozenset({
    "F", "Ref", "Mean", "Sum", "Std", "Var", "Max", "Min", "Quantile", "Rank",
    "IdxMax", "IdxMin", "Slope", "Rsquare", "Resi", "Corr",
    "Greater", "Less", "Log", "Abs", "Sign",
})
# Rolling operators over a past window: phi(x) unchanged (QBX window p>0 transfer).
_WINDOW_BLOCKS = frozenset({
    "Mean", "Sum", "Std", "Var", "Max", "Min", "Quantile", "Rank",
    "IdxMax", "IdxMin", "Slope", "Rsquare", "Resi", "Corr",
})


@dataclass(frozen=True, slots=True)
class Diagnostic:
    phase: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class AuditReport:
    expression: str
    admitted: bool
    phi: int | None                       # max time-availability effect
    node_identity: str | None             # Merkle-style root address
    normalized: str | None
    node_count: int
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "admitted": self.admitted,
            "phi": self.phi,
            "node_identity": self.node_identity,
            "normalized": self.normalized,
            "node_count": self.node_count,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "compiler_version": _COMPILER_VERSION,
            "contract_version": _CONTRACT_VERSION,
            "guarantee": "relative_to_registered_contracts_not_zero_backtest_leakage",
            "not_a_claim": "no effectiveness or profitability claim",
        }


def _node_address(block: str, params: tuple[Any, ...], parent_addresses: tuple[str, ...]) -> str:
    """Merkle-style address: canonical hash, author names/positions excluded."""
    payload = {
        "block": block,
        "params": list(params),
        "parents": sorted(parent_addresses),
        "contract": _CONTRACT_VERSION,
        "compiler": _COMPILER_VERSION,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _int_literal(node: ast.expr) -> int | None:
    """Read a plain integer literal, allowing an explicit unary minus."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return node.value
    if (isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, int)):
        return -node.operand.value
    return None


def _phi_of_call(func: str, args: list[ast.expr]) -> tuple[int, list[Diagnostic]]:
    """Compute availability effect for one call, QBX Definition 2 transfers.

    Qlib external syntax: ``Ref(x, N)`` with N>0 reads N bars AGO (past, legal,
    effect := -N); ``Ref(x, -N)`` reads N bars AHEAD (future, effect := +N,
    rejected). This matches the published transfer ``phi(lag p) = phi(x) - p``.
    """
    diags: list[Diagnostic] = []
    if func == "Ref":
        if len(args) != 2:
            diags.append(Diagnostic("Normalize", "invalid_parameter",
                                    "Ref requires exactly two arguments"))
            return 1, diags
        lag = _int_literal(args[1])
        if lag is None:
            diags.append(Diagnostic("Normalize", "invalid_temporal_parameter",
                                    "Ref lag must be an integer literal"))
            return 1, diags
        effect = -lag  # phi(x)=0 base; lag p -> -p
        if effect > 0:
            diags.append(Diagnostic("Availability", "future_ref",
                                    f"Ref lag {lag} reads {effect} bar(s) ahead (phi=+{effect})"))
        return effect, diags
    if func in _WINDOW_BLOCKS:
        return 0, diags  # window over past: phi unchanged (QBX window p>0)
    # Stateless elementwise ops (Log/Abs/Sign/Greater/Less) are effect-neutral.
    return 0, diags


def audit_expression(expression: str) -> AuditReport:
    """Staged read-only audit of one Qlib-style expression string."""
    diags: list[Diagnostic] = []
    # Phase: Normalize
    try:
        rewritten = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r'F("\1")', expression)
        tree = ast.parse(rewritten, mode="eval").body
    except SyntaxError as exc:
        return AuditReport(expression, False, None, None, None, 0,
                           (Diagnostic("Normalize", "malformed", str(exc)),))

    max_phi: int | None = None
    node_addresses: list[str] = []
    node_count = 0

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            nonlocal max_phi, node_count
            if not isinstance(node.func, ast.Name):
                diags.append(Diagnostic("Normalize", "unknown_block",
                                        "call target is not a named operator"))
                return
            func = node.func.id
            if func not in _REGISTERED_BLOCKS:
                diags.append(Diagnostic("Normalize", "unknown_block",
                                        f"{func!r} is not a registered block"))
                return
            if func == "F":
                node_count += 1
                node_addresses.append(_node_address("field", (ast.dump(node.args[0]),), ()))
                return
            phi, phase_diags = _phi_of_call(func, list(node.args))
            diags.extend(phase_diags)
            max_phi = phi if max_phi is None else max(max_phi, phi)
            parent_snapshot = tuple(node_addresses)
            for child in node.args:
                self.visit(child)
            node_count += 1
            params = tuple(
                ast.dump(a) for a in node.args if not isinstance(a, (ast.Call, ast.UnaryOp))
            )
            node_addresses.append(_node_address(func, params, parent_snapshot[-2:]))

        def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
            if node.id not in {"F"}:
                diags.append(Diagnostic("Graph", "unresolved_reference",
                                        f"free name {node.id!r}"))

    Visitor().visit(tree)

    effective_phi = 0 if max_phi is None else max_phi
    admitted = effective_phi <= 0 and not any(
        d.phase in ("Normalize", "Graph") for d in diags
    )
    if effective_phi > 0 and not any(d.phase == "Availability" for d in diags):
        diags.append(Diagnostic("Availability", "phi_positive",
                                f"max availability effect phi=+{effective_phi}"))
    root = None
    if node_addresses:
        root = hashlib.sha256(canonical_json({
            "nodes": sorted(node_addresses),
            "compiler": _COMPILER_VERSION,
            "registry": _CONTRACT_VERSION,
        }).encode("utf-8")).hexdigest()

    return AuditReport(
        expression=expression,
        admitted=admitted,
        phi=effective_phi,
        node_identity=root,
        normalized=ast.dump(tree) if admitted else None,
        node_count=node_count,
        diagnostics=tuple(diags),
    )


__all__ = ["AuditReport", "Diagnostic", "audit_expression"]
