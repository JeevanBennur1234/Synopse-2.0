"""Conservative extraction for explicit, simple table layouts."""
import re
NUM = r"-?\d[\d,]*(?:\.\d+)?"
DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})"
def extract_tables(pages):
    out, warnings = {}, []
    for key, header, pattern, names in [
        ("_line_items", r"(?:description|item).*?(?:qty|quantity).*?(?:unit price|rate).*?amount", rf"(.+?)\s+({NUM})\s+({NUM})\s+({NUM})", ("description","quantity","unit_price","amount")),
        ("_bank_transactions", r"date.*?(?:description|particulars).*?debit.*?credit.*?balance", rf"({DATE})\s+(.+?)\s+({NUM}|-)\s+({NUM}|-)\s+({NUM})", ("date","description","debit","credit","balance"))
    ]:
        rows=[]; active=False; uncertain=False
        for page in pages:
            for line in page["text"].splitlines():
                line=line.strip()
                if re.search(header,line,re.I):
                    active=True
                    continue
                if not active or not line: continue
                if re.match(r"(?i)(?:sub\s*total|grand total|total|closing balance|opening balance|CGST|SGST|IGST|UTGST|discount)\b",line):
                    active=False
                    continue
                m=re.fullmatch(pattern,line)
                if not m:
                    if re.search(r"\d",line): uncertain=True
                    continue
                row=dict(zip(names,m.groups()),page=page["page"])
                if key=="_bank_transactions":
                    for k in ("debit","credit"):
                        if row[k]=="-": row[k]="0"
                if page.get("method")=="ocr":
                    uncertain=True
                rows.append(row)
        if rows and not uncertain:
            out[key]=rows
        elif uncertain:
            warnings.append(f"{key}: ambiguous or OCR table layout; structured validation withheld.")
    return out,warnings

