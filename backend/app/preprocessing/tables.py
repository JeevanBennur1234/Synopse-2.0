"""Conservative extraction for explicit, simple table layouts."""
import re

NUM = r"-?\d[\d,]*(?:\.\d+)?"
DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})"

DEFAULT_STOP_PATTERNS = (
    r"closing balance:",
    r"opening balance:",
    r"total\s+(?:debits|credits)",
    r"end of statement",
    r"statement summary",
    r"page\s+\d+\s+of\s+\d+",
)


def extract_tables(pages, stop_patterns: tuple[str, ...] | None = None):
    out, warnings = {}, []
    active_stops = DEFAULT_STOP_PATTERNS if stop_patterns is None else stop_patterns

    for key, header, pattern, names in [
        ("_line_items", r"(?:description|item).*?(?:qty|quantity).*?(?:unit price|rate).*?amount", rf"(.+?)\s+({NUM})\s+({NUM})\s+({NUM})", ("description", "quantity", "unit_price", "amount")),
        ("_bank_transactions", r"date.*?(?:description|particulars).*?debit.*?credit.*?balance", rf"({DATE})\s+(.+?)\s+({NUM}|-)\s+({NUM}|-)\s+({NUM})", ("date", "description", "debit", "credit", "balance")),
    ]:
        rows = []
        active = False
        uncertain = False
        for page in pages:
            for line in page["text"].splitlines():
                line = line.strip()
                if re.search(header, line, re.I):
                    active = True
                    continue
                if not active or not line:
                    continue
                if re.match(r"(?i)(?:sub\s*total|grand total|total|closing balance|opening balance|CGST|SGST|IGST|UTGST|cess|discount)\b", line):
                    active = False
                    continue
                m = re.fullmatch(pattern, line)
                if not m:
                    if re.search(r"\d", line):
                        uncertain = True
                    continue
                row = dict(zip(names, m.groups()), page=page["page"])
                if key == "_bank_transactions":
                    for k in ("debit", "credit"):
                        if row[k] == "-":
                            row[k] = "0"
                if page.get("method") == "ocr":
                    uncertain = True
                rows.append(row)
        if rows and not uncertain:
            out[key] = rows
        elif uncertain:
            warnings.append(f"{key}: ambiguous or OCR table layout; structured validation withheld.")

    if "_bank_transactions" not in out:
        rows = []
        valid = True
        seen_header = False
        for page in pages:
            lines = [l.strip() for l in page["text"].splitlines() if l.strip()]
            header = next(
                (
                    i
                    for i in range(len(lines) - 4)
                    if re.fullmatch("Date", lines[i], re.I)
                    and re.fullmatch("Narration|Description|Particulars", lines[i + 1], re.I)
                    and all(
                        re.fullmatch(k + r"(?: \(INR\))?", lines[i + j], re.I)
                        for j, k in [(2, "Debit"), (3, "Credit"), (4, "Balance")]
                    )
                ),
                None,
            )
            if header is not None:
                seen_header = True
                i = header + 5
            elif seen_header:
                # Carry column layout forward onto continuation pages lacking repeated headers.
                i = next((idx for idx, ln in enumerate(lines) if re.fullmatch(DATE, ln)), len(lines))
                if i >= len(lines):
                    continue
            else:
                continue

            if page.get("method") != "native_pdf":
                valid = False
                continue

            while i < len(lines):
                if any(re.match(pat, lines[i], re.I) for pat in active_stops):
                    break
                if not re.fullmatch(DATE, lines[i]):
                    if any(re.fullmatch(DATE, lines[j]) for j in range(i + 1, len(lines))):
                        valid = False
                    break
                if (
                    i + 4 >= len(lines)
                    or not all(re.fullmatch(NUM + "|-", v) for v in lines[i + 2 : i + 4])
                    or not re.fullmatch(NUM, lines[i + 4])
                ):
                    valid = False
                    break
                row = dict(
                    date=lines[i],
                    description=lines[i + 1],
                    debit="0" if lines[i + 2] == "-" else lines[i + 2],
                    credit="0" if lines[i + 3] == "-" else lines[i + 3],
                    balance=lines[i + 4],
                    page=page["page"],
                )
                candidates = [w for w in page.get("words", []) if w["text"] == row["balance"]]
                if len(candidates) == 1:
                    w = candidates[0]
                    row["bbox"] = [w[k] for k in ("x", "y", "w", "h")]
                rows.append(row)
                i += 5

        if seen_header and valid and rows:
            out["_bank_transactions"] = rows
        elif seen_header:
            warnings.append("Bank table layout incomplete; running balance validation withheld.")

    return out, warnings
