import re

AMOUNT = r"(?:INR|Rs\.?|\u20b9)?[ \t]*([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?![\d.%])"
def extract(text):
    patterns = {
        "gstin": r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b",
        "dates": r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
        "ifsc": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
        "invoice_number": r"(?im)\binvoice[ \t]*(?:no\.?|number|#)[ \t]*:?[ \t]*([\w/-]+)",
    }
    for key,label in {"total":r"grand total|invoice total|total amount|total","subtotal":r"sub[ \t]*total|taxable value","cgst":"CGST","sgst":"SGST","igst":"IGST","utgst":"UTGST","cess":"cess","discount":"discount","opening_balance":"opening balance","closing_balance":"closing balance"}.items():
        patterns[key]=r"(?im)^[ \t]*(?:"+label+r")[ \t]*:?[ \t]*"+AMOUNT+r"[ \t]*$"
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
    for key,label in {"subtotal":r"sub[ \t]*total|taxable value","cgst":"CGST","sgst":"SGST","igst":"IGST"}.items():
        values=re.findall(r"(?im)\b(?:"+label+r")[ \t]*:[ \t]*"+AMOUNT+r"[ \t]*$",text)
        result[key]=list(dict.fromkeys(result[key]+values))
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
