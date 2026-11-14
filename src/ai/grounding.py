"""Check that every number in an agent's answer came from that run's tool results.

This is a string-level traceability check, not semantic verification. It cannot
catch a correctly sourced number used to support a wrong claim, nor a false
statement that contains no numbers.
"""
import re

MONTHS = (
    "January|February|March|April|May|June|July|August|September|"
    "October|November|December"
)

# Spans masked before numbers are extracted. Each is counted and reported,
# because anything masked is a place an unsupported number could hide.
MASK_PATTERNS = {
    "dates": [
        re.compile(r"\d{4}-\d{2}-\d{2}"),
        re.compile(rf"(?:{MONTHS})\s+\d{{1,2}}(?:,)?\s*\d{{4}}"),
        re.compile(rf"(?:{MONTHS})\s+\d{{1,2}}\b"),
        re.compile(rf"\b\d{{1,2}}\s+(?:{MONTHS})"),
        re.compile(rf"(?:{MONTHS})\s+\d{{4}}"),
        # "09, 11, 12, 16, and 18 March". The lookbehind keeps this off the
        # fractional part of a decimal, so "0.3, 0.2" is not read as a day list.
        re.compile(r"(?<![\d.])\d{1,2},\s*(?=and\b|\d{1,2}\b)"),
    ],
    # Only at the start of a line: "1." or "2)". Never mid-sentence.
    "ordinals": [re.compile(r"^[ \t]*\d+[.)](?=\s)", re.M)],
}

NUMBER_RE = re.compile(r"(-?\d[\d,]*\.?\d*)\s*(%?)")

COMPLEMENT_KEY_HINTS = ("significance", "confidence")

DIRECT = "direct"
PERCENT = "percent"
COMPLEMENT = "complement"
ABSOLUTE = "absolute_value"

# Preferred reporting order when a claim matches several ways.
MATCH_PRECEDENCE = (DIRECT, PERCENT, COMPLEMENT, ABSOLUTE)


def numeric_fields(payload, prefix: str = "") -> list[tuple[str, float]]:
    """Flatten tool output into (key_path, value) pairs. Booleans are not numbers."""
    fields: list[tuple[str, float]] = []

    if isinstance(payload, bool):
        return fields
    if isinstance(payload, (int, float)):
        return [(prefix, float(payload))]
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            fields.extend(numeric_fields(value, child))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            fields.extend(numeric_fields(value, f"{prefix}[{index}]"))

    return fields


def string_values(payload) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        return [s for value in payload.values() for s in string_values(value)]
    if isinstance(payload, list):
        return [s for value in payload for s in string_values(value)]
    return []


def evidence_fields(result: dict) -> list[tuple[str, float]]:
    fields: list[tuple[str, float]] = []
    for entry in result.get("evidence", []):
        tool = entry.get("tool", "")
        for key, value in numeric_fields(entry.get("result")):
            fields.append((f"{tool}.{key}" if key else tool, value))
    return fields


def evidence_strings(result: dict) -> set[str]:
    return {
        s
        for entry in result.get("evidence", [])
        for s in string_values(entry.get("result"))
    }


def significant_figures(raw: str) -> int:
    digits = raw.lstrip("-").replace(",", "").replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def mask_spans(answer: str) -> tuple[str, dict]:
    """Blank out spans that must not be read as risk figures, counting each."""
    masked = answer
    counts = {}
    for name, patterns in MASK_PATTERNS.items():
        total = 0
        for pattern in patterns:
            def blank(match):
                nonlocal total
                total += 1
                return " " * len(match.group(0))

            masked = pattern.sub(blank, masked)
        counts[name] = total
    return masked, counts


def line_of(answer: str, index: int) -> str:
    start = answer.rfind("\n", 0, index) + 1
    end = answer.find("\n", index)
    return answer[start: end if end != -1 else len(answer)].strip()


def extract_claims(answer: str) -> tuple[list[dict], dict]:
    masked, masked_counts = mask_spans(answer)

    claims = []
    for match in NUMBER_RE.finditer(masked):
        raw = match.group(1).rstrip(".,")
        if not raw or raw == "-":
            continue
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue

        decimals = len(raw.split(".")[1]) if "." in raw else 0
        claims.append(
            {
                "text": raw + match.group(2),
                "value": value,
                "decimals": decimals,
                "significant_figures": significant_figures(raw),
                "line": line_of(answer, match.start()),
            }
        )
    return claims, masked_counts


def _within_precision(candidate: float, claim_value: float, decimals: int) -> bool:
    """A claim stated to d decimal places admits half a unit in the last place."""
    return abs(candidate - claim_value) <= 0.5 * 10 ** (-decimals)


def match_claim(claim: dict, fields: list[tuple[str, float]]) -> list[dict]:
    """Every way this claim is supported by the run's evidence."""
    decimals = claim["decimals"]
    value = claim["value"]
    matches = []

    for key, evidence_value in fields:
        kinds = []

        if _within_precision(evidence_value, value, decimals):
            kinds.append(DIRECT)
        if _within_precision(evidence_value * 100, value, decimals):
            kinds.append(PERCENT)

        # A confidence level is one minus a significance level. Only fields that
        # say so by name may be read that way.
        if any(hint in key.lower() for hint in COMPLEMENT_KEY_HINTS):
            if _within_precision((1 - evidence_value) * 100, value, decimals) or (
                _within_precision(1 - evidence_value, value, decimals)
            ):
                kinds.append(COMPLEMENT)

        if not kinds and (
            _within_precision(abs(evidence_value), abs(value), decimals)
            or _within_precision(abs(evidence_value * 100), abs(value), decimals)
        ):
            kinds.append(ABSOLUTE)

        if kinds:
            best = min(kinds, key=MATCH_PRECEDENCE.index)
            matches.append({"kind": best, "key": key, "value": evidence_value})

    return matches


def is_weak(claim: dict) -> bool:
    """Low-precision claims match too easily to count as strong evidence."""
    return claim["decimals"] == 0 or claim["significant_figures"] < 2


def quoted_dates(answer: str) -> set[str]:
    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", answer))
    for match in re.finditer(
        rf"({'|'.join(months)})\s+(\d{{1,2}}),\s*(\d{{4}})", answer
    ):
        month = months.index(match.group(1)) + 1
        dates.add(f"{match.group(3)}-{month:02d}-{int(match.group(2)):02d}")
    return dates


def audit_grounding(result: dict) -> dict:
    """Report which numbers in the final answer trace to this run's tool results."""
    answer = result.get("answer") or ""
    fields = evidence_fields(result)
    strings = evidence_strings(result)

    claims, masked_counts = extract_claims(answer)

    grounded, weak, ungrounded = [], [], []
    for claim in claims:
        matches = match_claim(claim, fields)
        record = dict(claim)
        record["matches"] = len({m["value"] for m in matches})
        record["matched_by"] = (
            min((m["kind"] for m in matches), key=MATCH_PRECEDENCE.index)
            if matches
            else None
        )
        record["source"] = matches[0]["key"] if matches else None

        if not matches:
            ungrounded.append(record)
        elif is_weak(claim):
            weak.append(record)
        else:
            grounded.append(record)

    dates = quoted_dates(answer)
    unmatched_dates = sorted(d for d in dates if d not in strings)

    return {
        "claims": len(claims),
        "grounded": len(grounded),
        "weak": len(weak),
        "ungrounded": len(ungrounded),
        "is_grounded": not ungrounded and not unmatched_dates,
        "masked": masked_counts,
        "dates_checked": len(dates),
        "unmatched_dates": unmatched_dates,
        "grounded_claims": grounded,
        "weak_claims": weak,
        "ungrounded_claims": ungrounded,
    }


def format_grounding_audit(audit: dict) -> str:
    lines = [
        "Grounding Check:",
        f"  Numeric claims:     {audit['claims']}",
        f"  Strongly grounded:  {audit['grounded']}",
        f"  Weak (low precision): {audit['weak']}",
        f"  Ungrounded:         {audit['ungrounded']}",
        f"  Dates checked:      {audit['dates_checked']} "
        f"(unmatched: {len(audit['unmatched_dates'])})",
        "  Masked spans:       "
        + ", ".join(f"{k}={v}" for k, v in sorted(audit["masked"].items())),
    ]

    if audit["ungrounded_claims"]:
        lines.append("  Not traceable to this run's tool results:")
        for claim in audit["ungrounded_claims"]:
            lines.append(f"    {claim['text']}  <- {claim['line'][:90]}")

    if audit["unmatched_dates"]:
        lines.append("  Dates not present in tool results:")
        lines += [f"    {d}" for d in audit["unmatched_dates"]]

    return "\n".join(lines)
