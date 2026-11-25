"""Additional independent synthetic evaluation dataset for Kavach.

Generates 8 independent SAMPLE / TEST ONLY documents (4 clean, 4 tampered)
under ``dataset/eval_extra/`` without touching the baseline dataset in
``dataset/clean``, ``dataset/tampered``, or ``dataset/ground_truth``.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
import random
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from generate_samples import (
    IMG_HEIGHT,
    IMG_WIDTH,
    NativePdfPage,
    PDF_HEIGHT,
    PDF_RENDER_SCALE,
    PDF_WIDTH,
    WATERMARK_TEXT,
    _load_font,
    compute_valid_gstin,
    write_native_pdf,
)

ROOT = Path(__file__).resolve().parents[1]
EXTRA_ROOT = ROOT / "dataset" / "eval_extra"
CLEAN_DIR = EXTRA_ROOT / "clean"
TAMPERED_DIR = EXTRA_ROOT / "tampered"
GT_DIR = EXTRA_ROOT / "ground_truth"

SELLER_GSTIN = compute_valid_gstin("29ORION4321K1Z")
BUYER_GSTIN = compute_valid_gstin("27MERID8765M1Z")
# Flip last check char while keeping valid 15-char GSTIN structure
BAD_CHECKSUM_GSTIN = SELLER_GSTIN[:-1] + ("0" if SELLER_GSTIN[-1] != "0" else "1")


@dataclass
class ExtraInvoiceSpec:
    invoice_no: str
    date: str
    seller_gstin: str
    buyer_gstin: str
    ifsc: str
    place_of_supply: str
    subtotal: str
    cgst: str
    sgst: str
    igst: str
    grand_total: str
    tax_note: str


def build_extra_invoice_pdf(path: Path, spec: ExtraInvoiceSpec) -> dict[str, dict[str, int]]:
    page = NativePdfPage()
    regions: dict[str, dict[str, int]] = {}

    page.rect(36, 28, 523, 30, fill_rgb=(0.11, 0.20, 0.34))
    page.text(48, 37, WATERMARK_TEXT, size=10, bold=True, rgb=(0.95, 0.97, 1.0))
    page.text(430, 37, "TAX INVOICE", size=11, bold=True, rgb=(0.82, 0.92, 1.0))

    page.text(40, 74, "ORION LOGISTICS INDIA PVT LTD", size=14, bold=True)
    page.text(40, 93, "No. 18, Indiranagar 100ft Rd, Bengaluru 560038 (Fictional)", size=9, rgb=(0.35, 0.40, 0.48))
    gstin_box = page.text(40, 108, f"GSTIN: {spec.seller_gstin}", size=10, bold=True, mono=True)
    regions["seller_gstin"] = {
        "page": 0,
        "x": gstin_box["x"] - 8,
        "y": gstin_box["y"] - 4,
        "w": gstin_box["w"] + 20,
        "h": gstin_box["h"] + 8,
    }
    page.text(40, 123, f"IFSC: {spec.ifsc}", size=9, mono=True)

    page.rect(345, 72, 214, 68, fill_rgb=(0.97, 0.98, 0.99), stroke_rgb=(0.82, 0.85, 0.90))
    page.text(355, 80, f"Invoice no: {spec.invoice_no}", size=10, bold=True)
    page.text(355, 97, f"Date: {spec.date}", size=10)
    page.text(355, 114, f"Place of Supply: {spec.place_of_supply}", size=9, rgb=(0.35, 0.40, 0.48))

    page.rect(36, 152, 523, 56, stroke_rgb=(0.84, 0.87, 0.91))
    page.text(46, 160, "Billed To: MERIDIAN CLOUD SERVICES LLP (SAMPLE)", size=10, bold=True)
    page.text(46, 176, "Suite 12, Fictional Business Bay, Mumbai 400001", size=9, rgb=(0.35, 0.40, 0.48))
    page.text(46, 190, f"Buyer GSTIN: {spec.buyer_gstin}", size=9, mono=True)

    page.rect(36, 224, 523, 24, fill_rgb=(0.93, 0.95, 0.98), stroke_rgb=(0.80, 0.84, 0.89))
    page.text(46, 231, "Service / Item Description", size=9, bold=True)
    page.text(305, 231, "SAC/HSN", size=9, bold=True)
    page.text(380, 231, "Qty", size=9, bold=True)
    page.text(475, 231, "Amount (INR)", size=9, bold=True)

    if spec.subtotal == "20,000.00":
        line_items = [
            ("Managed Synthetic Freight Audit", "9965", "2", "12,000.00"),
            ("Telemetry Gateway Hardware (Sample)", "8517", "4", "8,000.00"),
        ]
    else:
        line_items = [
            ("Cloud Compliance Sandbox License", "9983", "1", "6,500.00"),
            ("Automated Ledger Reconciliation Pack", "9983", "1", "3,500.00"),
        ]

    y = 256
    for desc, hsn, qty, amt in line_items:
        page.text(46, y, desc, size=9)
        page.text(308, y, hsn, size=9, mono=True)
        page.text(384, y, qty, size=9, mono=True)
        page.text(480, y, amt, size=9, mono=True)
        page.line(36, y + 18, 559, y + 18)
        y += 26

    page.rect(36, 336, 523, 140, fill_rgb=(0.98, 0.99, 1.0), stroke_rgb=(0.82, 0.85, 0.90))
    page.text(46, 348, spec.tax_note, size=9, bold=True, rgb=(0.20, 0.26, 0.35))
    page.text(46, 368, "Independent evaluation sample — fictional transaction.", size=8, rgb=(0.45, 0.49, 0.56))

    page.text(340, 348, f"Subtotal: INR {spec.subtotal}", size=10, mono=True)
    cgst_box = page.text(340, 368, f"CGST: INR {spec.cgst}", size=10, mono=True)
    sgst_box = page.text(340, 386, f"SGST: INR {spec.sgst}", size=10, mono=True)
    igst_box = page.text(340, 404, f"IGST: INR {spec.igst}", size=10, mono=True)
    page.text(340, 422, "Discount: INR 0.00", size=10, mono=True)
    page.line(335, 442, 550, 442, rgb=(0.45, 0.50, 0.58), line_width=1.0)
    page.text(340, 449, f"Grand total: INR {spec.grand_total}", size=11, bold=True, mono=True)

    regions["tax_block"] = {
        "page": 0,
        "x": cgst_box["x"] - 10,
        "y": cgst_box["y"] - 6,
        "w": max(cgst_box["w"], sgst_box["w"], igst_box["w"]) + 28,
        "h": (igst_box["y"] + igst_box["h"] - cgst_box["y"]) + 14,
    }
    page.line(36, 760, 559, 760)
    page.text(36, 772, f"{WATERMARK_TEXT} | Kavach Extra Evaluation Set", size=8, rgb=(0.45, 0.50, 0.56))
    write_native_pdf(path, [page])
    return regions


def build_extra_bank_statement_pdf(path: Path) -> None:
    p1 = NativePdfPage()
    p2 = NativePdfPage()

    for idx, page in enumerate((p1, p2), start=1):
        page.rect(36, 28, 523, 30, fill_rgb=(0.11, 0.20, 0.34))
        page.text(48, 37, WATERMARK_TEXT, size=10, bold=True, rgb=(0.95, 0.97, 1.0))
        page.text(420, 37, f"ACCOUNT STATEMENT (Page {idx}/2)", size=9, bold=True, rgb=(0.82, 0.91, 1.0))

    p1.text(40, 74, "APEX SYNTHETIC BANK (EVALUATION BRANCH)", size=13, bold=True)
    p1.text(40, 94, "Account Holder: ORION LOGISTICS INDIA PVT LTD | A/C: 001122334455", size=9)
    p1.text(40, 109, "IFSC: APEX0009876 | Period: 01/11/2026 to 19/11/2026", size=9, mono=True)
    p1.text(40, 128, "Opening balance: INR 85,000.00", size=10, bold=True, mono=True)

    for page, start_y in ((p1, 155), (p2, 82)):
        page.rect(36, start_y, 523, 22, fill_rgb=(0.93, 0.95, 0.98), stroke_rgb=(0.80, 0.84, 0.89))
        page.text(44, start_y + 6, "Date", size=9, bold=True)
        page.text(120, start_y + 6, "Narration", size=9, bold=True)
        page.text(320, start_y + 6, "Debit (INR)", size=9, bold=True)
        page.text(398, start_y + 6, "Credit (INR)", size=9, bold=True)
        page.text(476, start_y + 6, "Balance (INR)", size=9, bold=True)

    rows_p1 = [
        ("03/11/2026", "NEFT Cloud Hosting Test", "5,000.00", "-", "80,000.00"),
        ("09/11/2026", "IMPS Client Retainer Demo", "-", "30,000.00", "110,000.00"),
    ]
    y = 185
    for dt, narr, deb, cred, bal in rows_p1:
        p1.text(44, y, dt, size=9, mono=True)
        p1.text(120, y, narr, size=9)
        p1.text(324, y, deb, size=9, mono=True)
        p1.text(402, y, cred, size=9, mono=True)
        p1.text(476, y, bal, size=9, mono=True)
        p1.line(36, y + 17, 559, y + 17)
        y += 26

    rows_p2 = [
        ("15/11/2026", "Sample Freight Settlement", "7,500.00", "-", "102,500.00"),
        ("19/11/2026", "Synthetic Rebate Credit", "-", "7,000.00", "109,500.00"),
    ]
    y = 112
    for dt, narr, deb, cred, bal in rows_p2:
        p2.text(44, y, dt, size=9, mono=True)
        p2.text(120, y, narr, size=9)
        p2.text(324, y, deb, size=9, mono=True)
        p2.text(402, y, cred, size=9, mono=True)
        p2.text(476, y, bal, size=9, mono=True)
        p2.line(36, y + 17, 559, y + 17)
        y += 26

    p2.rect(36, 185, 523, 40, fill_rgb=(0.97, 0.98, 0.99), stroke_rgb=(0.82, 0.85, 0.90))
    p2.text(46, 199, "Closing balance: INR 109,500.00", size=10, bold=True, mono=True)
    write_native_pdf(path, [p1, p2])


def render_extra_invoice_image(
    invoice_no: str,
    subtotal: str,
    cgst: str,
    sgst: str,
    grand_total: str,
) -> tuple[Image.Image, dict[str, dict[str, int]]]:
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(30, bold=True)
    f_h2 = _load_font(22, bold=True)
    f_body = _load_font(20)
    f_bold = _load_font(20, bold=True)
    f_mono = _load_font(20, mono=True)
    f_mono_bold = _load_font(22, bold=True, mono=True)
    f_small = _load_font(16)

    draw.rectangle((60, 50, IMG_WIDTH - 60, 118), fill=(26, 48, 82))
    draw.text((86, 70), WATERMARK_TEXT, fill=(240, 245, 255), font=f_bold)
    draw.text((IMG_WIDTH - 245, 70), "TAX INVOICE", fill=(195, 222, 255), font=f_h2)

    draw.text((70, 150), "ORION LOGISTICS INDIA PVT LTD", fill=(20, 28, 40), font=f_title)
    draw.text((70, 194), "Indiranagar 100ft Rd, Bengaluru 560038", fill=(90, 102, 118), font=f_body)
    draw.text((70, 226), f"GSTIN: {SELLER_GSTIN}", fill=(20, 28, 40), font=f_mono_bold)
    draw.text((70, 258), "IFSC: ORIN0004321", fill=(20, 28, 40), font=f_mono)

    draw.rectangle((760, 146, IMG_WIDTH - 60, 290), fill=(246, 248, 252), outline=(206, 214, 226), width=2)
    draw.text((785, 166), f"Invoice no: {invoice_no}", fill=(20, 28, 40), font=f_bold)
    draw.text((785, 202), "Date: 24/11/2026", fill=(20, 28, 40), font=f_body)
    draw.text((785, 238), "State: Karnataka (29)", fill=(90, 102, 118), font=f_body)

    draw.rectangle((60, 320, IMG_WIDTH - 60, 440), outline=(210, 218, 228), width=2)
    draw.text((82, 338), "Billed To: MERIDIAN CLOUD SERVICES LLP (SAMPLE)", fill=(20, 28, 40), font=f_bold)
    draw.text((82, 372), "Business Bay, Mumbai 400001", fill=(90, 102, 118), font=f_body)
    draw.text((82, 404), f"Buyer GSTIN: {BUYER_GSTIN}", fill=(20, 28, 40), font=f_mono)

    draw.rectangle((60, 720, IMG_WIDTH - 60, 1040), fill=(250, 251, 253), outline=(206, 214, 226), width=2)
    draw.text((82, 748), "GST Breakdown (9% CGST + 9% SGST)", fill=(45, 58, 78), font=f_bold)
    draw.text((82, 784), "Independent evaluation sample.", fill=(110, 120, 134), font=f_small)

    draw.text((710, 744), f"Subtotal: INR {subtotal}", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 784), f"CGST: INR {cgst}", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 824), f"SGST: INR {sgst}", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 864), "IGST: INR 0.00", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 904), "Discount: INR 0.00", fill=(25, 32, 42), font=f_mono)
    draw.line((700, 944, IMG_WIDTH - 80, 944), fill=(120, 132, 148), width=2)

    gt_rect = {"page": 0, "x": 695, "y": 954, "w": 475, "h": 68}
    draw.text((710, 968), f"Grand total: INR {grand_total}", fill=(15, 23, 42), font=f_mono_bold)

    draw.line((60, 1600, IMG_WIDTH - 60, 1600), fill=(210, 218, 228), width=2)
    draw.text((70, 1624), f"{WATERMARK_TEXT} | Kavach Extra Evaluation Set", fill=(110, 120, 134), font=f_small)
    return img, {"grand_total": gt_rect}


def write_gt(
    stem: str,
    relative_path: str,
    document_type: str,
    label: str,
    fmt: str,
    expected_anomalies: list[dict],
    affected_page: int | None,
    known_affected_regions: list[dict],
    page_dimensions: list[dict[str, int]],
    notes: str,
) -> dict:
    payload = {
        "filename": Path(relative_path).name,
        "relative_path": relative_path,
        "document_type": document_type,
        "label": label,
        "format": fmt,
        "synthetic_only": True,
        "watermark": WATERMARK_TEXT,
        "expected_anomalies": expected_anomalies,
        "affected_page": affected_page,
        "known_affected_regions": known_affected_regions,
        "page_dimensions": page_dimensions,
        "notes": notes,
    }
    (GT_DIR / f"{stem}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    random.seed(108)
    for d in (CLEAN_DIR, TAMPERED_DIR, GT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    pdf_dims = [{"page": 0, "width": PDF_WIDTH * PDF_RENDER_SCALE, "height": PDF_HEIGHT * PDF_RENDER_SCALE}]
    pdf_2p_dims = [
        {"page": 0, "width": PDF_WIDTH * PDF_RENDER_SCALE, "height": PDF_HEIGHT * PDF_RENDER_SCALE},
        {"page": 1, "width": PDF_WIDTH * PDF_RENDER_SCALE, "height": PDF_HEIGHT * PDF_RENDER_SCALE},
    ]
    img_dims = [{"page": 0, "width": IMG_WIDTH, "height": IMG_HEIGHT}]

    manifest: list[dict] = []

    # 1. Clean IGST PDF invoice
    build_extra_invoice_pdf(
        CLEAN_DIR / "extra_invoice_clean_igst.pdf",
        ExtraInvoiceSpec(
            invoice_no="EXT-2026-01",
            date="24/11/2026",
            seller_gstin=SELLER_GSTIN,
            buyer_gstin=BUYER_GSTIN,
            ifsc="ORIN0004321",
            place_of_supply="Maharashtra (27)",
            subtotal="20,000.00",
            cgst="0.00",
            sgst="0.00",
            igst="3,600.00",
            grand_total="23,600.00",
            tax_note="GST Breakdown (18% IGST Inter-State Supply)",
        ),
    )
    manifest.append(
        write_gt(
            stem="extra_invoice_clean_igst",
            relative_path="dataset/eval_extra/clean/extra_invoice_clean_igst.pdf",
            document_type="gst_invoice",
            label="clean",
            fmt="pdf",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=pdf_dims,
            notes="Independent clean inter-state IGST invoice.",
        )
    )

    # 2. Clean PNG invoice
    png_img, _ = render_extra_invoice_image("EXT-2026-02", "5,000.00", "450.00", "450.00", "5,900.00")
    png_img.save(CLEAN_DIR / "extra_invoice_clean_receipt.png", format="PNG")
    manifest.append(
        write_gt(
            stem="extra_invoice_clean_receipt",
            relative_path="dataset/eval_extra/clean/extra_invoice_clean_receipt.png",
            document_type="gst_invoice",
            label="clean",
            fmt="png",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=img_dims,
            notes="Independent clean PNG invoice.",
        )
    )

    # 3. Clean JPEG invoice
    jpg_img, _ = render_extra_invoice_image("EXT-2026-03", "15,000.00", "1,350.00", "1,350.00", "17,700.00")
    jpg_img.save(CLEAN_DIR / "extra_invoice_clean_photo.jpg", format="JPEG", quality=92)
    manifest.append(
        write_gt(
            stem="extra_invoice_clean_photo",
            relative_path="dataset/eval_extra/clean/extra_invoice_clean_photo.jpg",
            document_type="gst_invoice",
            label="clean",
            fmt="jpg",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=img_dims,
            notes="Independent clean JPEG invoice.",
        )
    )

    # 4. Clean 2-page bank statement
    build_extra_bank_statement_pdf(CLEAN_DIR / "extra_statement_clean_2p.pdf")
    manifest.append(
        write_gt(
            stem="extra_statement_clean_2p",
            relative_path="dataset/eval_extra/clean/extra_statement_clean_2p.pdf",
            document_type="bank_statement",
            label="clean",
            fmt="pdf",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=pdf_2p_dims,
            notes="Independent clean 2-page bank statement.",
        )
    )

    # 5. Tampered: Subtle GSTIN checksum mismatch
    gstin_reg = build_extra_invoice_pdf(
        TAMPERED_DIR / "extra_invoice_tampered_gstin_checksum.pdf",
        ExtraInvoiceSpec(
            invoice_no="EXT-2026-04",
            date="24/11/2026",
            seller_gstin=BAD_CHECKSUM_GSTIN,
            buyer_gstin=BUYER_GSTIN,
            ifsc="ORIN0004321",
            place_of_supply="Karnataka (29)",
            subtotal="10,000.00",
            cgst="900.00",
            sgst="900.00",
            igst="0.00",
            grand_total="11,800.00",
            tax_note="GST Breakdown (9% CGST + 9% SGST = 18%)",
        ),
    )
    manifest.append(
        write_gt(
            stem="extra_invoice_tampered_gstin_checksum",
            relative_path="dataset/eval_extra/tampered/extra_invoice_tampered_gstin_checksum.pdf",
            document_type="gst_invoice",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "invalid_gstin",
                    "description": f"Seller GSTIN '{BAD_CHECKSUM_GSTIN}' matches regex pattern but fails mod-36 check digit.",
                }
            ],
            affected_page=0,
            known_affected_regions=[{**gstin_reg["seller_gstin"], "description": "Altered GSTIN check digit"}],
            page_dimensions=pdf_dims,
            notes="Tampered GSTIN check digit test.",
        )
    )

    # 6. Tampered: Intra-state + Inter-state tax mix
    tax_reg = build_extra_invoice_pdf(
        TAMPERED_DIR / "extra_invoice_tampered_igst_mix.pdf",
        ExtraInvoiceSpec(
            invoice_no="EXT-2026-05",
            date="24/11/2026",
            seller_gstin=SELLER_GSTIN,
            buyer_gstin=BUYER_GSTIN,
            ifsc="ORIN0004321",
            place_of_supply="Karnataka (29)",
            subtotal="10,000.00",
            cgst="900.00",
            sgst="900.00",
            igst="1,800.00",
            grand_total="13,600.00",
            tax_note="GST Breakdown (9% CGST + 9% SGST = 18%)",
        ),
    )
    manifest.append(
        write_gt(
            stem="extra_invoice_tampered_igst_mix",
            relative_path="dataset/eval_extra/tampered/extra_invoice_tampered_igst_mix.pdf",
            document_type="gst_invoice",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "tax_inconsistency",
                    "description": "Applies both CGST+SGST (1,800.00) and IGST (1,800.00) simultaneously on 10,000.00 subtotal.",
                }
            ],
            affected_page=0,
            known_affected_regions=[{**tax_reg["tax_block"], "description": "Simultaneous CGST+SGST and IGST lines"}],
            page_dimensions=pdf_dims,
            notes="Conflicting intra-state and inter-state GST tax components.",
        )
    )

    # 7. Tampered: JPEG ELA splice
    base_buf = io.BytesIO()
    jpg_img.save(base_buf, format="JPEG", quality=95)
    base_buf.seek(0)
    ela_img = Image.open(base_buf).convert("RGB")
    splice_src, splice_boxes = render_extra_invoice_image("EXT-2026-06", "15,000.00", "1,350.00", "1,350.00", "27,700.00")
    sbox = splice_boxes["grand_total"]
    crop = splice_src.crop((sbox["x"], sbox["y"], sbox["x"] + sbox["w"], sbox["y"] + sbox["h"]))
    low_buf = io.BytesIO()
    crop.save(low_buf, format="JPEG", quality=30)
    low_buf.seek(0)
    ela_img.paste(Image.open(low_buf).convert("RGB"), (sbox["x"], sbox["y"]))
    ela_img.save(TAMPERED_DIR / "extra_invoice_tampered_visual_ela_splice.jpg", format="JPEG", quality=95)
    manifest.append(
        write_gt(
            stem="extra_invoice_tampered_visual_ela_splice",
            relative_path="dataset/eval_extra/tampered/extra_invoice_tampered_visual_ela_splice.jpg",
            document_type="gst_invoice",
            label="tampered",
            fmt="jpg",
            expected_anomalies=[
                {
                    "category": "visual",
                    "code": "ela_compression_splice",
                    "description": "Grand total region spliced at JPEG q=30 onto q=95 invoice.",
                },
                {
                    "category": "consistency",
                    "code": "grand_total_mismatch",
                    "description": "Grand total reads 27,700.00 instead of 17,700.00.",
                },
            ],
            affected_page=0,
            known_affected_regions=[{**sbox, "description": "JPEG splice over Grand total"}],
            page_dimensions=img_dims,
            notes="Independent visual ELA splice + total mismatch test.",
        )
    )

    # 8. Tampered: PNG Software Metadata
    png_meta_img, _ = render_extra_invoice_image("EXT-2026-07", "5,000.00", "450.00", "450.00", "5,900.00")
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("Software", "GIMP 2.10.36")
    png_info.add_text("Comment", "SAMPLE / TEST ONLY — Synthetic metadata test")
    png_meta_img.save(TAMPERED_DIR / "extra_invoice_tampered_metadata_gimp.png", format="PNG", pnginfo=png_info)
    manifest.append(
        write_gt(
            stem="extra_invoice_tampered_metadata_gimp",
            relative_path="dataset/eval_extra/tampered/extra_invoice_tampered_metadata_gimp.png",
            document_type="gst_invoice",
            label="tampered",
            fmt="png",
            expected_anomalies=[
                {
                    "category": "image_metadata",
                    "code": "editing_software_exif",
                    "description": "PNG tEXt Software chunk indicates 'GIMP 2.10.36'.",
                }
            ],
            affected_page=0,
            known_affected_regions=[],
            page_dimensions=img_dims,
            notes="Independent PNG metadata software tag test.",
        )
    )

    (GT_DIR / "manifest.json").write_text(
        json.dumps({"total_samples": len(manifest), "samples": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(manifest)} extra evaluation samples in dataset/eval_extra.")


if __name__ == "__main__":
    main()
