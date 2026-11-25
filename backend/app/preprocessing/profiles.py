"""Deterministic document profiles; ambiguous input remains other."""
import re

PROFILES = {
    "invoice": ("invoice_arithmetic_consistency", "invoice_line_items_arithmetic", "tax_rate_arithmetic"),
    "receipt": ("invoice_arithmetic_consistency", "invoice_line_items_arithmetic"),
    "gst_certificate": ("gstin_validation", "certificate_state", "certificate_pan", "certificate_dates"),
    "bank_statement": ("bank_statement_balance_consistency", "calendar_date_validity"),
    "upi_statement": ("calendar_date_validity", "statement_amounts"),
    "other": (),
}

def classify(pages, fields, tables):
    text = "\n".join(p.get("text", "") for p in pages).lower()
    if re.search(r"\bform\s+gst\s+reg[- ]?06\b|\bregistration certificate\b", text) and re.search(r"\bgst\b|goods and services tax|gstin", text):
        return "gst_certificate", .95
    if re.search(r"\b(?:upi|phonepe|google pay|paytm)\b", text) and re.search(r"\b(?:statement|transaction history)\b", text):
        return "upi_statement", .9
    if tables.get("_bank_transactions") or re.search(r"\b(?:bank|account) statement\b", text):
        return "bank_statement", .9
    if re.search(r"\b(?:receipt|all inclusive|cash memo)\b", text) and not re.search(r"\btax invoice\b", text):
        return "receipt", .85
    if fields.get("invoice_number") or fields.get("invoice_date") or re.search(r"\binvoice\b", " ".join(text.splitlines()[:6])) or (fields.get("subtotal") and fields.get("total")):
        return "invoice", .85
    return "other", .0

def coverage(kind, findings):
    required = PROFILES[kind]
    statuses = {}
    for name in required:
        matches = [f for f in findings if f.name == name]
        if any(f.status == "suspicious" and f.confidence >= .5 for f in matches):
            statuses[name] = "suspicious"
        elif any(f.status == "passed" and f.confidence >= .5 for f in matches):
            statuses[name] = "passed"
        elif matches and all(f.status == "not_applicable" for f in matches):
            statuses[name] = "not_applicable"
        else:
            statuses[name] = "inconclusive"
    applicable = sum(s != "not_applicable" for s in statuses.values())
    verified = sum(s in ("passed", "suspicious") for s in statuses.values())
    return dict(required=applicable, verified=verified, checks=statuses, fraction=verified/applicable if applicable else 0.0)
