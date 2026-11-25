import re
from datetime import datetime
from app.schemas import DetectorResult
from app.detectors.consistency.gstin import GST_STATE_CODES, GSTIN_REGEX
from app.detectors.consistency.arithmetic import resolve_candidate_field, has_low_field_confidence, DEFAULT_ROUNDING_TOLERANCE

def finding(name, ok, evidence, confidence=.85):
    return DetectorResult(name=name,status="inconclusive" if ok is None else "passed" if ok else "suspicious",score=.8 if ok is False else 0,confidence=0 if ok is None else confidence,evidence=evidence)

def certificate(fields):
    pages=fields.get("_pages",[])
    text="\n".join(p.get("text","") for p in pages)
    # Native text is reliable for structural comparisons; OCR needs readable tokens.
    words=[w for p in pages if p.get("method")=="ocr" for w in p.get("words",[])]
    low=any(p.get("method")=="ocr" for p in pages) and (not words or sum(w.get("confidence") or 0 for w in words)/len(words)<.65)
    ids=fields.get("gstin",[])
    gst=ids[0] if len(ids)==1 and GSTIN_REGEX.fullmatch(ids[0]) else None
    def label(pattern):
        m=re.search(r"(?im)\b(?:"+pattern+r")[ \t]*:?[ \t]*(?:\n[ \t]*)?([^\n]+)",text)
        return m[1].strip() if m else ""
    address=label("address of principal place of business|principal place of business")
    constitution=label("constitution of business").lower()
    states=[code for code,state in GST_STATE_CODES.items() if re.search(r"\b"+re.escape(state)+r"\b",address,re.I)]
    state_ok=gst[:2] in states if gst and len(states)==1 and not low else None
    yield finding("certificate_state",state_ok,"Principal address state compared with GSTIN state code." if state_ok is not None else "Address state or reliable GSTIN unavailable.")
    mapping={"proprietorship":"P","individual":"P","company":"C","partnership":"F","firm":"F","huf":"H","trust":"T","association of persons":"A"}
    expected={v for k,v in mapping.items() if re.search(r"\b"+k+r"\b",constitution)}
    ok=gst[5] in expected if gst and len(expected)==1 and not low else None
    yield finding("certificate_pan",ok,"Embedded PAN constitution compared with declared constitution." if ok is not None else "Reliable constitution or PAN unavailable.")
    dates=[]
    for key in ("date of liability","validity from|valid from","date of issue"):
        raw=label(key)
        m=re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{4}-\d{2}-\d{2}",raw)
        value=None
        if m:
            for fmt in ("%d-%m-%Y","%d/%m/%Y","%Y-%m-%d"):
                try: value=datetime.strptime(m[0],fmt); break
                except ValueError: pass
        dates.append(value)
    ok=dates[0]<=dates[2] and dates[1]<=dates[2] if all(dates) and not low else None
    yield finding("certificate_dates",ok,"Liability and validity-from dates compared with issue date." if ok is not None else "Reliable labelled certificate dates unavailable.")

def inclusive(fields):
    keys=("subtotal","total","cgst","sgst","igst","utgst","cess")
    vals={k:resolve_candidate_field(k,fields) for k in keys}
    if has_low_field_confidence(fields,keys) or any(v[2]=="conflicting" for v in vals.values()) or any(vals[k][2]!="resolved" for k in ("subtotal","total")) or not any(vals[k][2]=="resolved" for k in keys[2:]):
        return finding("invoice_arithmetic_consistency",None,"Inclusive receipt taxable amount, tax or total not reliably extracted.")
    expected=vals["subtotal"][0]+sum(vals[k][0] or 0 for k in keys[2:])
    total=vals["total"][0]
    return finding("invoice_arithmetic_consistency",abs(expected-total)<=DEFAULT_ROUNDING_TOLERANCE,f"Inclusive tax reconciliation: taxable plus tax = {expected}; total = {total}.")


def statement_amounts(fields):
    """Validate transaction amount tokens on UPI/payment statements without running balance columns."""
    pages = fields.get("_pages", [])
    text = "\n".join(p.get("text", "") for p in pages)
    amounts = re.findall(r"(?im)\b(?:debit|credit|paid|received)\b[^\n]{0,30}?\b(\d+(?:,\d{3})*(?:\.\d{1,2})?)\b", text)
    if not amounts:
        return finding("statement_amounts", None, "No readable transaction amount entries extracted from statement.")
    parsed = []
    for raw in amounts:
        try:
            val = float(raw.replace(",", ""))
            if val < 0:
                return finding("statement_amounts", False, f"Negative transaction amount '{raw}' found in statement.")
            parsed.append(val)
        except ValueError:
            return finding("statement_amounts", None, f"Unparseable transaction amount '{raw}' in statement.")
    return finding("statement_amounts", True, f"Verified {len(parsed)} non-negative statement transaction amount(s).")
