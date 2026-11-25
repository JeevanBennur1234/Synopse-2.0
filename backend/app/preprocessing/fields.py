import re

AMOUNT = r"(?:INR|Rs\.?|\u20b9)?[ \t]*([0-9][0-9,]*(?:\.[0-9]{1,2})?)(?![\d.%])"
def extract(text):
    patterns = {
        "gstin": r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]\b",
        "dates": r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",
        "ifsc": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
        "invoice_number": r"(?im)\binvoice[ \t]*(?:no\.?|number|#)[ \t]*:?[ \t]*([\w/-]+)",
    }
    for key,label in {"total":r"grand total|invoice total|total amount|total","subtotal":r"sub[ \t]*total|taxable value","cgst":"CGST","sgst":"SGST","igst":"IGST","discount":"discount","opening_balance":"opening balance","closing_balance":"closing balance"}.items():
        patterns[key]=r"(?im)^[ \t]*(?:"+label+r")[ \t]*:?[ \t]*"+AMOUNT+r"[ \t]*$"
    result={k:list(dict.fromkeys(re.findall(v,text))) for k,v in patterns.items()}
    for key,label in [("gstin","GSTIN"),("ifsc","IFSC")]:
        candidates=re.findall(r"(?im)\b"+label+r"(?:[ \t]+(?:no\.?|code))?[ \t]*:?[ \t]+([A-Z0-9-]{3,30})\b",text)
        result[key]=list(dict.fromkeys(result[key]+[v.upper() for v in candidates]))
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
                        matches.append({"value":value,"page":page["page"],"x":word["x"],"y":word["y"],"w":word["w"],"h":word["h"],"confidence":word["confidence"]})
        out[key]=matches
    return out
