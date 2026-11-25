"""Tests for invoice arithmetic consistency detector."""

from decimal import Decimal
import pytest
from app.detectors.consistency.arithmetic import (
    parse_decimal_candidate,
    resolve_candidate_field,
    validate_invoice_arithmetic,
)


def test_parse_decimal_candidate():
    assert parse_decimal_candidate("1,000.50") == Decimal("1000.50")
    assert parse_decimal_candidate("₹ 50,000.00") == Decimal("50000.00")
    assert parse_decimal_candidate("-120.00") == Decimal("-120.00")
    assert parse_decimal_candidate("invalid") is None
    assert parse_decimal_candidate("") is None
    assert parse_decimal_candidate(None) is None


def test_resolve_candidate_field():
    # Unambiguous
    val, cands, status = resolve_candidate_field("total", {"total": ["1,000.00", "1000.00"]})
    assert val == Decimal("1000.00")
    assert status == "resolved"

    # Conflicting
    val, cands, status = resolve_candidate_field("total", {"total": ["1,000.00", "1,200.00"]})
    assert val is None
    assert status == "conflicting"

    # Missing
    val, cands, status = resolve_candidate_field("total", {"total": []})
    assert val is None
    assert status == "missing"


def test_validate_invoice_arithmetic_clean():
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": ["90.00"],
        "total": ["1,180.00"],
        "discount": [],
    }
    results = validate_invoice_arithmetic(fields)
    assert len(results) == 2
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "passed"
    assert tot_res.score == 0.0


def test_validate_invoice_arithmetic_with_discount():
    fields = {
        "subtotal": ["1,000.00"],
        "discount": ["100.00"],
        "cgst": ["81.00"],
        "sgst": ["81.00"],
        "total": ["1,062.00"],
    }
    results = validate_invoice_arithmetic(fields)
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "passed"
    assert tot_res.score == 0.0


def test_validate_invoice_arithmetic_mismatch():
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": ["90.00"],
        "total": ["1,500.00"],  # Expected 1,180.00
    }
    results = validate_invoice_arithmetic(fields)
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "suspicious"
    assert tot_res.score >= 0.75
    assert "discrepancy" in tot_res.evidence


def test_validate_invoice_arithmetic_missing_fields_inconclusive():
    fields = {
        "subtotal": [],
        "total": ["1,180.00"],
    }
    results = validate_invoice_arithmetic(fields)
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "inconclusive"


def test_validate_invoice_arithmetic_multiple_financial_candidates_inconclusive():
    fields = {
        "subtotal": ["1,000.00", "1,500.00"],
        "total": ["1,180.00"],
    }
    results = validate_invoice_arithmetic(fields)
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "inconclusive"
    assert tot_res.score == 0.0
    assert "Unresolved candidate ambiguity is treated as inconclusive" in tot_res.evidence


def test_validate_line_items_arithmetic_clean():
    fields = {
        "subtotal": ["1000.00"],
        "total": ["1000.00"],
        "_line_items": [
            {
                "description": "Item A",
                "quantity": "2",
                "unit_price": "300.00",
                "amount": "600.00",
                "page": 0,
            },
            {
                "description": "Item B",
                "quantity": "4",
                "unit_price": "100.00",
                "amount": "400.00",
                "page": 0,
            },
        ],
    }
    results = validate_invoice_arithmetic(fields)
    line_res = next(r for r in results if r.name == "invoice_line_items_arithmetic")
    assert line_res.status == "passed"
    assert line_res.score == 0.0


def test_validate_line_items_arithmetic_unit_price_mismatch():
    fields = {
        "subtotal": ["1000.00"],
        "_line_items": [
            {
                "description": "Bad item",
                "quantity": "2",
                "unit_price": "300.00",
                "amount": "999.00",  # Expected 600.00
                "page": 0,
            }
        ],
    }
    results = validate_invoice_arithmetic(fields)
    line_res = next(r for r in results if r.name == "invoice_line_items_arithmetic")
    assert line_res.status == "suspicious"
    assert "999.00" in line_res.evidence


def test_validate_line_items_sum_subtotal_mismatch():
    fields = {
        "subtotal": ["2000.00"],
        "_line_items": [
            {
                "description": "Item A",
                "quantity": "1",
                "unit_price": "500.00",
                "amount": "500.00",
                "page": 0,
            }
        ],
    }
    results = validate_invoice_arithmetic(fields)
    line_res = next(r for r in results if r.name == "invoice_line_items_arithmetic")
    assert line_res.status == "suspicious"
    assert "Sum of line items" in line_res.evidence


def test_validate_invoice_arithmetic_utgst_and_cess():
    fields = {
        "subtotal": ["10,000.00"],
        "discount": ["500.00"],
        "cgst": ["900.00"],
        "utgst": ["900.00"],
        "cess": ["200.00"],
        "total": ["11,500.00"],  # 10000 - 500 + 900 + 900 + 200
    }
    results = validate_invoice_arithmetic(fields)
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "passed"
    assert tot_res.score == 0.0


def test_validate_invoice_arithmetic_unreadable_tax_inconclusive():
    fields = {
        "subtotal": ["10,000.00"],
        "cgst": ["unreadable"],
        "total": ["11,800.00"],
    }
    results = validate_invoice_arithmetic(fields)
    tot_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert tot_res.status == "inconclusive"
    assert tot_res.score == 0.0
