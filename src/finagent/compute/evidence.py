"""Bounded expression evaluation over registered numeric evidence, never host code."""

import ast
import json
from decimal import Decimal, localcontext
from hashlib import sha256

from finagent.schemas import Citation, DerivedLocator, ValueRef


def evaluate(expression: str, values: dict[str, tuple[Decimal, str]]) -> tuple[Decimal, str]:
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 80 or len(expression) > 1000:
        raise ValueError("Expression exceeds size budget")

    def visit(node):
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            value = Decimal(str(node.value))
            if abs(value) > 1_000_000:
                raise ValueError(
                    "Method constant exceeds limit; financial values must use evidence"
                )
            return value, "1"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value, unit = visit(node.operand)
            return (-value if isinstance(node.op, ast.USub) else value), unit
        if isinstance(node, ast.BinOp):
            left, lu = visit(node.left)
            right, ru = visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if lu != ru:
                    raise ValueError("Addition/subtraction require compatible units")
                return (left + right if isinstance(node.op, ast.Add) else left - right), lu
            if isinstance(node.op, ast.Mult):
                if lu != "1" and ru != "1":
                    raise ValueError("Multiplication of two dimensional values is unsupported")
                return left * right, ru if lu == "1" else lu
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("Denominator is zero; result is missing, not zero")
                if ru == "1":
                    return left / right, lu
                if lu == ru:
                    return left / right, "1"
                raise ValueError("Division requires matching units or a scalar denominator")
        raise ValueError("Only evidence names, bounded constants and + - * / are allowed")

    with localcontext() as context:
        context.prec = 34
        return visit(tree.body)


def compute_evidence(deps, expression: str, inputs: dict[str, str], output_unit: str = "ratio"):
    if not inputs or len(inputs) > 20 or not all(k.isidentifier() for k in inputs):
        raise ValueError("Provide 1..20 named evidence inputs")
    used = {n.id for n in ast.walk(ast.parse(expression, mode="eval")) if isinstance(n, ast.Name)}
    if used != set(inputs):
        raise ValueError(
            "Every supplied input must be used; no unrelated evidence or unknown names"
        )
    citations = {}
    values = {}
    for name, cid in inputs.items():
        if cid not in deps.allowed_citation_ids:
            raise ValueError("Input citation must be registered in this run")
        citation = deps.store.get_citation(cid)
        if citation is None or citation.value is None:
            raise ValueError("Input must have a numeric value; narrative numbers are not inferred")
        if citation.source.source_type == "xbrl":
            if deps.store.lookup_xbrl_value(citation) != citation.value.amount:
                raise ValueError("Input does not match original XBRL fact")
        elif citation.source.source_type != "derived":
            raise ValueError("Unsupported numeric evidence type")
        else:
            replay_computation(deps.store, citation.citation_id)
        citations[name] = citation
        values[name] = citation.value.amount, citation.value.unit
    # Display percentages are dimensionless too; preserve their original values/units
    # in the record, but permit subtracting reported margins to obtain percentage points.
    evaluated_values = {
        name: (value, "1" if unit in {"ratio", "percent", "percentage_points"} else unit)
        for name, (value, unit) in values.items()
    }
    result, unit = evaluate(expression, evaluated_values)
    if output_unit in {"percent", "percentage_points", "days", "ratio"}:
        if unit != "1":
            raise ValueError(
                "Requested output must be dimensionless before semantic unit annotation"
            )
        unit = output_unit
    elif output_unit != unit:
        raise ValueError("Output unit does not match expression unit")
    ids = list(dict.fromkeys(inputs.values()))
    record = {
        "expression": expression,
        "inputs": inputs,
        "input_values": {
            name: {"value": str(value), "unit": u} for name, (value, u) in values.items()
        },
        "result": str(result),
        "unit": unit,
        "precision": 34,
        "verification": "expression_replayed_not_metric_semantics_audited",
    }
    raw = json.dumps(record, sort_keys=True)
    first = next(iter(citations.values()))
    source = first.source.model_copy(
        update={"source_type": "derived", "title": "Evidence computation"}
    )
    locator = DerivedLocator(operation=expression, input_citation_ids=ids)
    citation = Citation(
        citation_id="D" + sha256(raw.encode()).hexdigest()[:16].upper(),
        source=source,
        locator=locator,
        value=ValueRef(amount=result, unit=unit),
    )
    with deps.store.transaction() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS computations "
            "(citation_id TEXT PRIMARY KEY, record_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO computations VALUES (?,?)", (citation.citation_id, raw)
        )
    deps.store.register_citation(citation)
    return citation, record


def replay_computation(store, cid: str, seen=None):
    seen = set() if seen is None else seen
    if cid in seen or len(seen) > 20:
        raise ValueError("Cyclic or excessive computation dependencies")
    seen = seen | {cid}
    with store.connect() as connection:
        row = connection.execute(
            "SELECT record_json FROM computations WHERE citation_id=?", (cid,)
        ).fetchone()
    if row is None:
        raise ValueError("Computation record is missing")
    record = json.loads(row["record_json"])
    values = {}
    for name, input_id in record["inputs"].items():
        c = store.get_citation(input_id)
        if c is None or c.value is None:
            raise ValueError("Computation input is missing")
        if c.source.source_type == "derived":
            replay_computation(store, input_id, seen)
        elif c.source.source_type != "xbrl" or store.lookup_xbrl_value(c) != c.value.amount:
            raise ValueError("Computation input no longer matches source")
        values[name] = c.value.amount, c.value.unit
        if record["input_values"][name] != {"value": str(c.value.amount), "unit": c.value.unit}:
            raise ValueError("Computation input version changed")
    value, _ = evaluate(
        record["expression"],
        {
            name: (v, "1" if u in {"ratio", "percent", "percentage_points"} else u)
            for name, (v, u) in values.items()
        },
    )
    c = store.get_citation(cid)
    if (
        c is None
        or c.value is None
        or value != Decimal(record["result"])
        or value != c.value.amount
    ):
        raise ValueError("Computation replay mismatch")
    if c.value.unit != record["unit"]:
        raise ValueError("Computation unit mismatch")
    return value
