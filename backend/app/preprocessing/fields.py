import re

AMOUNT = r"(?:INR|Rs\.?|\u20b9)?[ \t]*([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?![\d.%])"
def extract(text):
    patterns = {
        "gstin": r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b",
        "dates": r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
        "ifsc": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
        "invoice_number": r"(?im)\binvoice[ \t]*(?:no\.?|number|#)[ \t]*:?[ \t]*([\w/-]+)",
    }
    for key,label in {"total":r"grand total|invoice total|net total|total amount|total","subtotal":r"sub[ \t]*total|taxable value|taxable amount","cgst":"CGST","sgst":"SGST","igst":"IGST","utgst":"UTGST","cess":"cess","discount":"discount","opening_balance":"opening balance","closing_balance":"closing balance"}.items():
        rate = r"(?:[ \t]*\([ \t]*\d+(?:\.\d+)?[ \t]*%[ \t]*\))?" if key in {"cgst", "sgst", "utgst", "igst", "cess"} else ""
        patterns[key]=r"(?im)^[ \t]*(?:"+label+r")"+rate+r"[ \t]*:?[ \t]*"+AMOUNT+r"[ \t]*$"
    date = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})"
    for key,label in {"invoice_date":"invoice date","due_date":"due date"}.items():
        patterns[key]=r"(?im)^\s*"+label+r"[ \t]*:?[ \t]*"+date
    patterns["tax_rate"]=r"(?im)^[ \t]*(?:GST rate|tax rate)[ \t]*:?[ \t]*(\d+(?:\.\d+)?)%"
    for key,label in {"supplier_state":"supplier state","place_of_supply":"place of supply"}.items():
        patterns[key]=r"(?im)^[ \t]*"+label+r"[ \t]*:[ \t]*([^\r\n]+)"
    result={k:list(dict.fromkeys(re.findall(v,text))) for k,v in patterns.items()}
    for key,label in [("gstin","GSTIN"),("ifsc","IFSC")]:
        candidates=re.findall(r"(?im)\b"+label+r"(?:[ \t]+(?:no\.?|code))?[ \t]*:?[ \t]+([A-Z0-9-]{3,30})\b",text)
        result[key]=list(dict.fromkeys(result[key]+[v.upper() for v in candidates]))
    # Recover explicitly labelled amounts embedded in OCR lines.
    for key,label in {"subtotal":r"sub[ \t]*total|taxable value|taxable amount","cgst":"CGST","sgst":"SGST","igst":"IGST"}.items():
        values=re.findall(r"(?im)\b(?:"+label+r")[ \t]*:[ \t]*"+AMOUNT+r"[ \t]*$",text)
        result[key]=list(dict.fromkeys(result[key]+values))
    # Named-month dates (e.g. "27 Oct, 2026", "Nov 24, 2026") for statements and receipts.
    named_date = r"\b(?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*,?\s+\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b"
    result["dates"] = list(dict.fromkeys(result["dates"] + re.findall(named_date, text, re.I)))
    # Label-anchored extraction for GST certificates (never auto-correcting characters).
    for cert_key, cert_label in {
        "registration_number": r"registration\s*number",
        "legal_name": r"legal\s*name",
        "principal_address": r"address\s*of\s*principal\s*place\s*of\s*business|principal\s*place\s*of\s*business",
        "constitution": r"constitution\s*of\s*business",
    }.items():
        vals = re.findall(r"(?im)\b(?:" + cert_label + r")[ \t]*:?[ \t]*(?:\n[ \t]*)?([^\n]{2,120})", text)
        cleaned = [v.strip() for v in vals if v.strip()]
        if cleaned:
            result[cert_key] = list(dict.fromkeys(cleaned))
    return result

def locate(pages, fields):
    # Only exact word matches; ambiguous occurrences remain separate.
    out={}
    for key,values in fields.items():
        matches=[]
        for page in pages:
            for word in page["words"]:
                for value in values:
                    if word["text"].strip(":;()").casefold()==value.casefold():
                        matches.append({"value":value,"page":page["page"],"x":word["x"],"y":word["y"],"w":word["w"],"h":word["h"],"bbox":[word["x"],word["y"],word["w"],word["h"]],"confidence":word["confidence"]})
        out[key]=matches
    return out

# Longer aliases take priority over generic "total" and "taxable" tokens.
AMOUNT_LABELS = {
    "grand total": "total", "invoice total": "total", "total amount": "total",
    "sub total": "subtotal", "subtotal": "subtotal", "taxable amount": "subtotal",
    "taxable value": "subtotal", "cgst": "cgst", "sgst": "sgst", "igst": "igst",
    "utgst": "utgst", "cess": "cess", "discount": "discount", "total": "total",
}
NUMBER_CELL = re.compile(r"(?:INR|Rs\.?|\u20b9)?[ \t]*(-?\d[\d,]*(?:\.\d{1,2})?)", re.I)


def word_rows(words, vertical_tolerance=0.45):
    """Group rendered words by vertical center, independently of PDF text order."""
    rows = []
    for word in sorted(words, key=lambda w: (w["y"] + w["h"] / 2, w["x"])):
        center = word["y"] + word["h"] / 2
        if rows:
            anchor = rows[-1][0]
            if abs(center - anchor["y"] - anchor["h"] / 2) <= max(3, min(word["h"], anchor["h"]) * vertical_tolerance):
                rows[-1].append(word)
                continue
        rows.append([word])
    return [sorted(row, key=lambda w: w["x"]) for row in rows]


def extract_native_amounts(pages):
    fields = {}
    for page in pages:
        if page.get("method") != "native_pdf":
            continue
        rows = word_rows(page.get("words", []))
        for idx, row in enumerate(rows):
            tokens = [w["text"].casefold().strip(":") for w in row]
            labels = []
            i = 0
            while i < len(row):
                pair = " ".join(tokens[i:i + 2])
                end = i + (2 if pair in AMOUNT_LABELS else 1)
                key = AMOUNT_LABELS.get(pair if end == i + 2 else tokens[i])
                if key:
                    labels.append((i, end, key))
                i = end

            for index, (start, end, key) in enumerate(labels):
                left = row[start]["x"]
                last = row[end - 1]
                right = last["x"] + last["w"]
                limit = row[labels[index + 1][0]]["x"] if index + 1 < len(labels) else page["width"]
                height = row[start]["h"]
                candidates = []
                for word in row[end:]:
                    match = NUMBER_CELL.fullmatch(word["text"])
                    if match and right <= word["x"] < limit:
                        candidates.append((word["x"] - right, match[1]))
                if not candidates and idx + 1 < len(rows):
                    below = rows[idx + 1]
                    gap = below[0]["y"] - row[start]["y"]
                    if 0 < gap <= 2.5 * height:
                        for word in below:
                            match = NUMBER_CELL.fullmatch(word["text"])
                            if match and left - height <= word["x"] < min(limit, right + 2 * height):
                                # Prefer alignment with the label's right edge, then its left edge.
                                align = min(abs(word["x"] + word["w"] - right), abs(word["x"] - left))
                                candidates.append((align, match[1]))
                if candidates:
                    fields.setdefault(key, []).append(min(candidates)[1])
    return {key: list(dict.fromkeys(values)) for key, values in fields.items()}
