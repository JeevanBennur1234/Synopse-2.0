"""Conservative extraction for explicit, simple table layouts."""
import re

from app.preprocessing.fields import word_rows

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

    invoice_rows, present, incomplete = _coordinate_invoice_rows(pages)
    if invoice_rows and not incomplete:
        out["_line_items"] = invoice_rows
        warnings = [warning for warning in warnings if not warning.startswith("_line_items:")]
    elif incomplete:
        out.pop("_line_items", None)
        warnings.append("Invoice table contains incomplete or ambiguous numeric rows.")
    if any(page.get("text", "").strip() or page.get("words") for page in pages):
        out["_line_items_present"] = present or bool(out.get("_line_items")) or any(
            warning.startswith("_line_items:") for warning in warnings
        )
    return out, warnings


TABLE_HEADERS = {
    "description": "description", "item": "description", "particulars": "description",
    "qty": "quantity", "quantity": "quantity", "rate": "unit_price",
    "price": "unit_price", "amount": "amount", "hsn": "identifier",
    "sac": "identifier", "sac/hsn": "identifier", "hsn/sac": "identifier",
}


def _coordinate_invoice_rows(pages):
    """Read explicitly headed invoice tables, including amount-only layouts."""
    items = []
    present = incomplete = False
    for page in pages:
        columns = []
        rows = word_rows(page.get("words", []), 0.8 if page.get("method") == "ocr" else 0.45)
        if page.get("method") == "ocr":
            rows = _merge_numeric_fragments(rows)
        details = None
        for row in rows:
            tokens = [word["text"].casefold().strip(":") for word in row]
            headers = [(TABLE_HEADERS[token], word["x"]) for token, word in zip(tokens, row)
                       if token in TABLE_HEADERS]
            names = {name for name, _ in headers}
            if {"description", "amount"} <= names and headers[0][0] == "description":
                present = True
                columns = [(name, x) for name, x in headers if name != "description"]
                continue
            if re.search(r"\b(?:sub\s*total|taxable (?:value|amount)|grand total|"
                         r"cgst|sgst|igst|utgst|cess|discount)\b", " ".join(tokens)):
                if details and len(details) > 1:
                    present = True
                    items.extend(details)
                columns = []
                details = None
                continue
            if not columns:
                if re.fullmatch(r"(?:service|item|line item|product|billing) (?:details?|description)", " ".join(tokens)):
                    details = []
                elif details is not None and len(row) > 1 and re.fullmatch(NUM, tokens[-1]) and any(
                    token.isalpha() for token in tokens[:-1]
                ):
                    amount = row[-1]
                    bbox = [amount[k] for k in ("x", "y", "w", "h")]
                    if details and abs(bbox[0] + bbox[2] - sum(details[-1]["bbox"][::2])) > amount["h"]:
                        present = incomplete = True
                        details = None
                    else:
                        details.append(dict(
                            description=" ".join(w["text"] for w in row[:-1]),
                            amount=amount["text"], page=page["page"], bbox=bbox,
                            confidence=amount.get("confidence"),
                        ))
                elif details:
                    present = incomplete = True
                    details = None
                continue
            first_x = columns[0][1]
            desc = []
            cells = {}
            for word in row:
                if word["x"] < first_x - word["h"]:
                    desc.append(word["text"])
                elif re.fullmatch(NUM, word["text"]):
                    col = min(columns, key=lambda entry: abs(word["x"] - entry[1]))[0]
                    if col != "identifier":
                        cells.setdefault(col, []).append(word)
            if not cells:
                continue
            required = {name for name, _ in columns if name != "identifier"}
            if not desc or any(len(cells.get(name, ())) != 1 for name in required):
                incomplete = True
                continue
            numeric = {name: value[0] for name, value in cells.items()}
            amount = numeric["amount"]
            confidence = [w["confidence"] for w in numeric.values() if w.get("confidence") is not None]
            items.append(dict(
                {name: w["text"] for name, w in numeric.items()},
                description=" ".join(desc), page=page["page"],
                bbox=[amount[k] for k in ("x", "y", "w", "h")],
                confidence=min(confidence) if confidence else None,
            ))
        if details:
            present = incomplete = True
    return items, present, incomplete


def _merge_numeric_fragments(rows):
    """Restore isolated OCR cells within the preceding text row's vertical extent."""
    merged = []
    for row in rows:
        if merged and all(re.fullmatch(NUM, word["text"]) for word in row):
            previous = merged[-1]
            bottom = max(word["y"] + word["h"] for word in previous)
            top = min(word["y"] for word in previous)
            if any(not re.fullmatch(NUM, word["text"]) for word in previous) and all(
                top <= word["y"] <= bottom for word in row
            ):
                merged[-1] = sorted(previous + row, key=lambda word: word["x"])
                continue
        merged.append(row)
    return merged
