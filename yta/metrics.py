"""Fills {{ ... }} placeholders in a script with numbers computed from the data.

The writing task never types a number. It writes, for example:

    Prices rose {{ pct_change(cpi, "2000", "2024") | pct }} since 2000.

and this module computes the value from the downloaded series and spells it for narration
("eighty-one percent" is left to the voice; we output "81 percent").
Only a small whitelist of functions and arithmetic is allowed.
"""
from __future__ import annotations

import ast
import re

from .data import Series

PLACEHOLDER = re.compile(r"\{\{\s*(.+?)\s*\}\}")


class MetricError(ValueError):
    pass


def _s(x) -> Series:
    if not isinstance(x, Series):
        raise MetricError("expected a data series name as the first argument")
    return x


def _pair(s, start, end):
    s = _s(s)
    return s.at(start)[1], s.at(end)[1]


def _years(s, start, end) -> float:
    from .data import parse_date

    a = _s(s).at(start)[0] if start == "latest" else parse_date(start)
    b = _s(s).at(end)[0] if end == "latest" else parse_date(end, True)
    return (b - a).days / 365.25


def _trend_per_year(s, start=None, end=None) -> float:
    """Slope of a straight line through the yearly averages: how much the series rises per year on trend."""
    pts = _s(s).between(start, end).yearly_mean().points
    if len(pts) < 3:
        raise MetricError("need at least 3 years of data for a trend")
    xs = [d.year for d, _ in pts]
    ys = [v for _, v in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys)) / sum((a - mx) ** 2 for a in xs)


def _payment(principal, rate_percent, years) -> float:
    r, n = rate_percent / 100 / 12, int(round(years * 12))
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def paired_years(x, y, start=None, end=None) -> list[tuple[int, float, float]]:
    """(year, x, y) for every year both series cover, using yearly averages. Shared with the scatter chart."""
    xs = {d.year: v for d, v in _s(x).between(start, end).yearly_mean().points}
    ys = {d.year: v for d, v in _s(y).between(start, end).yearly_mean().points}
    years = sorted(set(xs) & set(ys))
    if len(years) < 3:
        raise MetricError("need at least 3 years where both series have data")
    return [(yr, xs[yr], ys[yr]) for yr in years]


def linear_fit(x, y, start=None, end=None) -> tuple[float, float, float]:
    """Least-squares line y = a + b*x on yearly averages. Returns (intercept, slope, r_squared)."""
    pts = paired_years(x, y, start, end)
    n = len(pts)
    mx = sum(p[1] for p in pts) / n
    my = sum(p[2] for p in pts) / n
    sxx = sum((p[1] - mx) ** 2 for p in pts)
    syy = sum((p[2] - my) ** 2 for p in pts)
    sxy = sum((p[1] - mx) * (p[2] - my) for p in pts)
    if sxx == 0 or syy == 0:
        raise MetricError("one of the series doesn't change, so there is no relationship to measure")
    slope = sxy / sxx
    return my - slope * mx, slope, sxy * sxy / (sxx * syy)


def _correlation(x, y, start=None, end=None) -> float:
    _, slope, r2 = linear_fit(x, y, start, end)
    return (r2 ** 0.5) * (1 if slope >= 0 else -1)


FUNCTIONS = {
    "value": lambda s, when: _s(s).at(when)[1],
    "first": lambda s, start=None, end=None: _s(s).between(start, end).first[1],
    "latest": lambda s: _s(s).last[1],
    "latest_year": lambda s: _s(s).last[0].year,
    "change": lambda s, start, end: (lambda a, b: b - a)(*_pair(s, start, end)),
    "pct_change": lambda s, start, end: (lambda a, b: (b - a) / a)(*_pair(s, start, end)),
    "ratio": lambda s, start, end: (lambda a, b: b / a)(*_pair(s, start, end)),
    "cagr": lambda s, start, end: (lambda a, b: (b / a) ** (1 / _years(s, start, end)) - 1)(*_pair(s, start, end)),
    "highest": lambda s, start=None, end=None: max(v for _, v in _s(s).between(start, end).points),
    "lowest": lambda s, start=None, end=None: min(v for _, v in _s(s).between(start, end).points),
    "year_of_highest": lambda s, start=None, end=None: max(_s(s).between(start, end).points, key=lambda p: p[1])[0].year,
    "year_of_lowest": lambda s, start=None, end=None: min(_s(s).between(start, end).points, key=lambda p: p[1])[0].year,
    # money maths
    "grow": lambda amount, rate, years: amount * (1 + rate) ** years,
    "compound": lambda monthly, rate, years: (
        monthly * 12 * years if rate == 0 else monthly * (((1 + rate) ** (years) - 1) / ((1 + rate) ** (1 / 12) - 1))
    ),
    # simple models, on yearly averages (the scatter chart draws the same fit)
    "correlation": _correlation,
    "slope": lambda x, y, start=None, end=None: linear_fit(x, y, start, end)[1],
    "r_squared": lambda x, y, start=None, end=None: linear_fit(x, y, start, end)[2],
    "trend_per_year": lambda s, start=None, end=None: _trend_per_year(s, start, end),
    # monthly payment on a loan: rate is a yearly percentage as FRED quotes it (6.5 means 6.5%)
    "payment": lambda principal, rate_percent, years: _payment(principal, rate_percent, years),
    "in_todays_money": lambda amount, cpi, then: amount * _s(cpi).last[1] / _s(cpi).at(then)[1],
}


def _words_number(x: float) -> str:
    ax = abs(x)
    if ax >= 1e12:
        return f"{x / 1e12:.1f} trillion".replace(".0 ", " ")
    if ax >= 1e9:
        return f"{x / 1e9:.1f} billion".replace(".0 ", " ")
    if ax >= 1e6:
        return f"{x / 1e6:.1f} million".replace(".0 ", " ")
    if ax >= 100:
        return f"{x:,.0f}"
    if ax >= 10:
        return f"{x:.0f}"
    return f"{x:.1f}".rstrip("0").rstrip(".")


FORMATS = {
    "usd": lambda x: f"{_words_number(x)} dollars",
    "usd_cents": lambda x: f"{x:.2f} dollars",
    "pct": lambda x: f"{_words_number(x * 100)} percent",
    "pct1": lambda x: f"{x * 100:.1f} percent",
    "pts": lambda x: f"{_words_number(x)} percentage points",
    "num": _words_number,
    "times": lambda x: f"{x:.1f} times".replace(".0 ", " "),
    "year": lambda x: f"{int(x)}",
    "years": lambda x: f"{x:.0f} years",
}


class _Evaluator(ast.NodeVisitor):
    def __init__(self, series: dict[str, Series]):
        self.series = series

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float, str)):
            return node.value
        raise MetricError("only numbers and strings are allowed")

    def visit_Name(self, node):
        if node.id in self.series:
            return self.series[node.id]
        raise MetricError(f"unknown data series '{node.id}'")

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            raise MetricError(f"unknown function; allowed: {', '.join(sorted(FUNCTIONS))}")
        args = [self.visit(a) for a in node.args]
        kwargs = {k.arg: self.visit(k.value) for k in node.keywords}
        try:
            return FUNCTIONS[node.func.id](*args, **kwargs)
        except (TypeError, ZeroDivisionError) as exc:
            raise MetricError(f"{node.func.id}(): {exc}") from exc

    def visit_BinOp(self, node):
        a, b = self.visit(node.left), self.visit(node.right)
        ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b}
        if type(node.op) not in ops:
            raise MetricError("only + - * / are allowed")
        return ops[type(node.op)]()

    def visit_Compare(self, node):
        left = self.visit(node.left)
        ops = {ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b, ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b}
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in ops:
                raise MetricError("only > >= < <= comparisons are allowed")
            right = self.visit(comp)
            if not ops[type(op)](left, right):
                return 0.0
            left = right
        return 1.0

    def visit_UnaryOp(self, node):
        if isinstance(node.op, ast.USub):
            return -self.visit(node.operand)
        raise MetricError("only unary minus is allowed")

    def generic_visit(self, node):
        raise MetricError(f"'{type(node).__name__}' is not allowed in a placeholder")


def evaluate(expr: str, series: dict[str, Series]) -> float:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise MetricError(f"cannot read '{expr}'") from exc
    value = _Evaluator(series).visit(tree)
    if not isinstance(value, (int, float)):
        raise MetricError(f"'{expr}' does not give a number")
    return float(value)


def fill(text: str, series: dict[str, Series]) -> str:
    def repl(m):
        body = m.group(1)
        expr, _, fmt = body.partition("|")
        fmt = fmt.strip() or "num"
        if fmt not in FORMATS:
            raise MetricError(f"unknown format '{fmt}'; allowed: {', '.join(FORMATS)}")
        try:
            return FORMATS[fmt](evaluate(expr.strip(), series))
        except ValueError as exc:
            raise MetricError(f"{{{{ {body} }}}}: {exc}") from exc

    return PLACEHOLDER.sub(repl, text)


_TYPED_NUMBER = re.compile(r"\d[\d,.]*")


def typed_numbers(text: str) -> list[str]:
    """Numbers written directly in the script instead of computed. Years (1900-2099) are allowed."""
    stripped = PLACEHOLDER.sub(" ", text)
    bad = []
    for m in _TYPED_NUMBER.finditer(stripped):
        token = m.group(0).rstrip(".,")
        if re.fullmatch(r"(19|20)\d\d", token):
            continue
        bad.append(token)
    return bad
