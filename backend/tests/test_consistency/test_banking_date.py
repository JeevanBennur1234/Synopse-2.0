"""Tests for date and banking consistency detector."""

from decimal import Decimal
import pytest
from app.detectors.consistency.banking_date import (
    parse_and_validate_date,
    validate_date_and_banking,
)


def test_parse_and_validate_date_leap_year():
    # 2024 is a leap year -> Feb 29 is valid
    dt, err = parse_and_validate_date("29/02/2024")
    assert err is None
    assert dt is not None
    assert dt.year == 2024 and dt.month == 2 and dt.day == 29

    # 2023 is not a leap year -> Feb 29 is invalid
    dt, err = parse_and_validate_date("29/02/2023")
    assert dt is None
    assert err is not None
    assert "Invalid day 29" in err


def test_parse_and_validate_date_impossible_dates():
    # April has only 30 days
    dt, err = parse_and_validate_date("31/04/2026")
    assert dt is None
    assert "Invalid day 31" in err

    # Month 13 is invalid
    dt, err = parse_and_validate_date("15/13/2026")
    assert dt is None
    assert "Invalid month 13" in err


def test_validate_date_and_banking_calendar_clean():
    fields = {"dates": ["25/11/2026", "01/01/2026"]}
    results = validate_date_and_banking(fields)
    cal_res = next(r for r in results if r.name == "calendar_date_validity")
    assert cal_res.status == "passed"
    assert cal_res.score == 0.0


def test_validate_date_and_banking_calendar_invalid():
    fields = {"dates": ["31/04/2026"]}
    results = validate_date_and_banking(fields)
    cal_res = next(r for r in results if r.name == "calendar_date_validity")
    assert cal_res.status == "suspicious"
    assert "Calendar date defect" in cal_res.evidence


def test_validate_date_chronology_clean():
    fields = {
        "invoice_date": ["10/11/2026"],
        "due_date": ["25/11/2026"],
    }
    results = validate_date_and_banking(fields)
    chr_res = next(r for r in results if r.name == "date_chronology")
    assert chr_res.status == "passed"
    assert chr_res.score == 0.0


def test_validate_date_chronology_due_before_invoice():
    fields = {
        "invoice_date": ["25/11/2026"],
        "due_date": ["10/11/2026"],
    }
    results = validate_date_and_banking(fields)
    chr_res = next(r for r in results if r.name == "date_chronology")
    assert chr_res.status == "suspicious"
    assert "precedes invoice date" in chr_res.evidence
    assert "unusual date ordering alone does not prove fraud" in chr_res.evidence


def test_validate_ifsc_clean():
    fields = {"ifsc": ["HDFC0001234"]}
    results = validate_date_and_banking(fields)
    ifsc_res = next(r for r in results if r.name == "ifsc_validation")
    assert ifsc_res.status == "passed"
    assert ifsc_res.score == 0.0


def test_validate_ifsc_invalid():
    fields = {"ifsc": ["HDFC1001234"]}  # 5th char must be '0'
    results = validate_date_and_banking(fields)
    ifsc_res = next(r for r in results if r.name == "ifsc_validation")
    assert ifsc_res.status == "suspicious"
    assert "violates 11-character structural pattern" in ifsc_res.evidence


def test_validate_bank_transactions_clean():
    fields = {
        "opening_balance": ["10000.00"],
        "closing_balance": ["9500.00"],
        "_bank_transactions": [
            {
                "date": "25/11/2026",
                "description": "Payment",
                "debit": "500.00",
                "credit": "0.00",
                "balance": "9500.00",
                "page": 0,
            }
        ],
    }
    results = validate_date_and_banking(fields)
    bank_res = next(r for r in results if r.name == "bank_statement_balance_consistency")
    assert bank_res.status == "passed"
    assert bank_res.score == 0.0


def test_validate_bank_transactions_running_balance_mismatch():
    fields = {
        "opening_balance": ["10000.00"],
        "closing_balance": ["9500.00"],
        "_bank_transactions": [
            {
                "date": "25/11/2026",
                "description": "Payment",
                "debit": "500.00",
                "credit": "0.00",
                "balance": "8000.00",  # Expected 9500.00
                "page": 0,
            }
        ],
    }
    results = validate_date_and_banking(fields)
    bank_res = next(r for r in results if r.name == "bank_statement_balance_consistency")
    assert bank_res.status == "suspicious"
    assert "previous balance 10000.00" in bank_res.evidence
