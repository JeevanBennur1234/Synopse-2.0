"""Tests for tax consistency detector."""

from decimal import Decimal
import pytest
from app.detectors.consistency.tax import validate_tax_consistency


def test_tax_symmetry_clean():
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": ["90.00"],
    }
    results = validate_tax_consistency(fields)
    sym_res = next(r for r in results if r.name == "cgst_sgst_symmetry")
    assert sym_res.status == "passed"
    assert sym_res.score == 0.0


def test_tax_symmetry_mismatch():
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": ["100.00"],
    }
    results = validate_tax_consistency(fields)
    sym_res = next(r for r in results if r.name == "cgst_sgst_symmetry")
    assert sym_res.status == "suspicious"
    assert "Asymmetric intra-state GST amounts" in sym_res.evidence


def test_tax_symmetry_unpaired_cgst_inconclusive():
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": [],
    }
    results = validate_tax_consistency(fields)
    sym_res = next(r for r in results if r.name == "cgst_sgst_symmetry")
    assert sym_res.status == "inconclusive"
    assert sym_res.score == 0.0
    assert "Incomplete OCR field extraction" in sym_res.evidence


def test_tax_symmetry_utgst_support():
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "utgst": ["90.00"],
    }
    results = validate_tax_consistency(fields)
    sym_res = next(r for r in results if r.name == "cgst_sgst_symmetry")
    assert sym_res.status == "passed"
    assert sym_res.score == 0.0


def test_tax_mixed_rates_inconclusive():
    # Subtotal 1000 with 112 tax (e.g. mixed 5% and 18% items)
    fields = {
        "subtotal": ["1,000.00"],
        "cgst": ["56.00"],
        "sgst": ["56.00"],
    }
    results = validate_tax_consistency(fields)
    rate_res = next(r for r in results if r.name == "tax_rate_arithmetic")
    assert rate_res.status == "inconclusive"
    assert rate_res.score == 0.0
    assert "Mixed-rate line items" in rate_res.evidence


def test_tax_jurisdiction_both_igst_and_intra_state_suspicious():
    fields = {
        "cgst": ["90.00"],
        "sgst": ["90.00"],
        "igst": ["180.00"],
    }
    results = validate_tax_consistency(fields)
    jur_res = next(r for r in results if r.name == "gst_jurisdiction_consistency")
    assert jur_res.status == "suspicious"
    assert "Simultaneous presence" in jur_res.evidence


def test_tax_jurisdiction_explicit_location_matching():
    # Intra-state supply
    fields = {
        "cgst": ["90.00"],
        "sgst": ["90.00"],
        "supplier_state": ["Karnataka"],
        "place_of_supply": ["Karnataka"],
    }
    results = validate_tax_consistency(fields)
    jur_res = next(r for r in results if r.name == "gst_jurisdiction_consistency")
    assert jur_res.status == "passed"
    assert "intra-state supply" in jur_res.evidence


def test_tax_jurisdiction_explicit_location_mismatch():
    # Intra-state taxes for inter-state supply
    fields = {
        "cgst": ["90.00"],
        "sgst": ["90.00"],
        "supplier_state": ["Karnataka"],
        "place_of_supply": ["Maharashtra"],
    }
    results = validate_tax_consistency(fields)
    jur_res = next(r for r in results if r.name == "gst_jurisdiction_consistency")
    assert jur_res.status == "suspicious"
    assert "differs from place of supply" in jur_res.evidence


def test_tax_jurisdiction_missing_locations_inconclusive():
    fields = {
        "cgst": ["90.00"],
        "sgst": ["90.00"],
    }
    results = validate_tax_consistency(fields)
    jur_res = next(r for r in results if r.name == "gst_jurisdiction_consistency")
    assert jur_res.status == "inconclusive"
    assert "place of supply is not inferred from GSTIN alone" in jur_res.evidence


def test_tax_rate_arithmetic_explicit_rate_matches():
    fields = {
        "subtotal": ["1000.00"],
        "tax_rate": ["18%"],
        "cgst": ["90.00"],
        "sgst": ["90.00"],
    }
    results = validate_tax_consistency(fields)
    rate_res = next(r for r in results if r.name == "tax_rate_arithmetic")
    assert rate_res.status == "passed"
    assert rate_res.score == 0.0


def test_tax_rate_arithmetic_explicit_rate_mismatch():
    fields = {
        "subtotal": ["1000.00"],
        "tax_rate": ["18%"],
        "cgst": ["50.00"],
        "sgst": ["50.00"],  # Total 100 instead of 180
    }
    results = validate_tax_consistency(fields)
    rate_res = next(r for r in results if r.name == "tax_rate_arithmetic")
    assert rate_res.status == "suspicious"
    assert "Tax amount discrepancy" in rate_res.evidence


def test_tax_rate_no_explicit_rate_does_not_assume_18():
    # 5% tax invoice
    fields = {
        "subtotal": ["1000.00"],
        "cgst": ["25.00"],
        "sgst": ["25.00"],
    }
    results = validate_tax_consistency(fields)
    rate_res = next(r for r in results if r.name == "tax_rate_arithmetic")
    assert rate_res.status == "passed"
    assert "standard GST slab 5.0%" in rate_res.evidence
