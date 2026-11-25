import pytest
import fitz
from PIL import Image, ImageDraw, ImageFont
from app.preprocessing.document import process, extract
from app.preprocessing.fields import locate

def test_fields():
    f=extract("GSTIN: 29INVALID123\nInvoice no: TEST-1\nSubtotal: 1000\nCGST: 90\nSGST: 90\nGrand total: \u20b91,180.00\nIFSC: BAD123\nDate: 25/11/2026")
    assert f["gstin"]==["29INVALID123"]
    assert f["ifsc"]==["BAD123"]
    assert f["total"]==["1,180.00"]
    assert f["cgst"]==["90"]
    assert f["dates"]==["25/11/2026"]
    assert extract("CGST: 9%")["cgst"]==[]

@pytest.mark.parametrize("suffix",[".png",".jpg",".pdf"])
def test_real_ocr(tmp_path,suffix):
    im=Image.new("RGB",(1200,500),"white")
    draw=ImageDraw.Draw(im)
    font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",48)
    draw.text((50,50),"SAMPLE TEST ONLY\nInvoice no: TEST-1\nGrand total: 1180",font=font,fill="black",spacing=20)
    source=tmp_path/("original"+suffix)
    if suffix==".pdf":
        im.save(source,"PDF",resolution=144)
    else:
        im.save(source)
    pages,fields,warnings=process(source)
    assert pages[0]["method"]=="ocr",warnings
    assert fields["total"]==["1180"],pages[0]["text"]
    assert locate(pages,fields)["total"]
    assert all(w["x"]>=0 and w["y"]>=0 for w in pages[0]["words"])



def test_native_holdout_word_layout_amounts():
    import json
    from pathlib import Path
    from app.preprocessing.fields import extract_native_amounts

    baseline = Path(__file__).resolve().parents[2] / "dataset/holdout/single_run.jsonl"
    rows = {r["file"]: r for r in map(json.loads, baseline.read_text().splitlines())}
    for name, subtotal, tax, grand in (
        ("05_total.pdf", "12,000.00", "1,080.00", "16,860.00"),
        ("06_gstin.pdf", "12,500.00", "1,125.00", "14,750.00"),
    ):
        amounts = extract_native_amounts(rows[name]["result"]["pages"])
        assert amounts == {"subtotal": [subtotal], "cgst": [tax], "sgst": [tax], "total": [grand]}



def test_native_amounts_separate_rows_and_neighboring_columns():
    from app.preprocessing.fields import extract_native_amounts

    def word(text, x, y, width=40):
        return dict(text=text, x=x, y=y, w=width, h=12)

    words = [
        word("Taxable", 20, 30), word("Amount", 65, 30),
        word("CGST", 220, 30), word("9%", 265, 30),
        word("1,000.00", 40, 48), word("90.00", 221, 48),
        word("Grand", 21, 83), word("Total", 67, 83), word("1,180.00", 143, 83),
    ]
    assert extract_native_amounts([dict(method="native_pdf", width=400, words=words)]) == {
        "subtotal": ["1,000.00"], "cgst": ["90.00"], "total": ["1,180.00"],
    }


def test_invoice_table_coordinates_native_and_ocr():
    from app.preprocessing.tables import extract_tables

    words = [
        dict(text=text, x=x, y=y, w=30, h=12, confidence=confidence)
        for text, x, y, confidence in (
            ("Description", 25, 20, 0.97), ("Qty", 170, 20, 0.97),
            ("Rate", 260, 20, 0.97), ("Amount", 350, 20, 0.97),
            ("Inspection", 25, 40, 0.98), ("2", 170, 40, 0.94),
            ("70.00", 260, 40, 0.80), ("140.00", 350, 40, 0.92),
            ("Subtotal", 250, 65, 0.98), ("140.00", 350, 65, 0.99),
        )
    ]
    for method in ("native_pdf", "ocr"):
        fields, _ = extract_tables([dict(page=0, method=method, text="", words=words)])
        item, = fields["_line_items"]
        assert (item["description"], item["quantity"], item["unit_price"], item["amount"]) == (
            "Inspection", "2", "70.00", "140.00",
        )
        assert item["confidence"] == 0.80



def test_optional_invoice_structures_are_not_applicable_when_absent():
    from app.detectors.consistency.arithmetic import validate_invoice_arithmetic
    from app.detectors.consistency.tax import validate_tax_consistency
    from app.preprocessing.tables import extract_tables

    page = dict(text="Invoice\nSubtotal: 180.00\nTotal: 180.00", words=[])
    tables, _ = extract_tables([page])
    fields = dict(tables, subtotal=["180.00"], total=["180.00"], _pages=[page])
    assert [x.status for x in validate_invoice_arithmetic(fields)] == ["passed", "not_applicable"]
    assert validate_tax_consistency(fields)[-1].status == "not_applicable"
    page["text"] += "\nCGST: unreadable"
    assert validate_tax_consistency(fields)[-1].status == "inconclusive"


def test_unreadable_labelled_line_items_are_inconclusive():
    from app.detectors.consistency.arithmetic import validate_invoice_arithmetic
    from app.preprocessing.tables import extract_tables

    words = [dict(text=text, x=x, y=20, w=38, h=12)
             for text, x in (("Description", 12), ("Qty", 170), ("Amount", 350))]
    tables, _ = extract_tables([dict(page=0, method="ocr", text="Description Qty Amount", words=words)])
    assert tables["_line_items_present"] is True
    assert validate_invoice_arithmetic(tables)[-1].status == "inconclusive"
