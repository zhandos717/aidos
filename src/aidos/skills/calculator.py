"""Калькулятор skill — математикалық есептеулер."""

import ast
import logging
import operator
import re

logger = logging.getLogger("aidos.skill.calculator")

# Осы паттерндер сәйкес келсе, skill іске қосылады
triggers = [
    r"\b(есепте|санап\s*бер|қанша\s*болады)\b",
    r"\d+\s*[+\-*/^]\s*\d+",
    r"\b(\d+)\s+(плюс|минус|бөлген|көбейтген)\s+(\d+)\b",
]

_KK_OPS = {
    "плюс": "+",
    "минус": "-",
    "бөлген": "/",
    "көбейтген": "*",
}

_EXPR_RE = re.compile(r"[\d\s\+\-\*/\(\)\.\^]+")

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"Unsupported: {node}")


def _normalize(query: str) -> str:
    q = query.lower()
    for kk, op in _KK_OPS.items():
        q = q.replace(kk, op)
    q = q.replace("^", "**")
    return q


def _extract_expr(text: str) -> str | None:
    match = _EXPR_RE.search(text)
    if match:
        expr = match.group().strip()
        if any(op in expr for op in "+-*/"):
            return expr
    return None


def handle(query: str) -> str:
    normalized = _normalize(query)
    expr = _extract_expr(normalized)

    if not expr:
        return "Өрнекті тани алмадым. Мысалы: '5 + 3' немесе '10 / 2'"

    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree.body)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        logger.info("Есептелді: '%s' = %s", expr.strip(), result)
        return f"{expr.strip()} = {result}"
    except ZeroDivisionError:
        return "Нөлге бөлуге болмайды."
    except Exception as exc:
        logger.error("Есептеу қатесі: %s", exc)
        return f"Есептеу қатесі: {exc}"
