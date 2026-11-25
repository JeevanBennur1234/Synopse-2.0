"""Synthetic dataset generator for Kavach (Synapse 2.0).

Generates clearly labelled SAMPLE / TEST ONLY business documents (invoices and
bank statements) in PDF, PNG, and JPEG formats across ``dataset/clean`` and
``dataset/tampered``, along with ground-truth annotations in
``dataset/ground_truth``.

Uses only Python standard library + Pillow + NumPy so it works cleanly across
all team environments without extra dependencies.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
CLEAN_DIR = ROOT / "dataset" / "clean"
TAMPERED_DIR = ROOT / "dataset" / "tampered"
GT_DIR = ROOT / "dataset" / "ground_truth"

WATERMARK_TEXT = "SAMPLE / TEST ONLY — SYNTHETIC DATA"
PDF_WIDTH = 595
PDF_HEIGHT = 842
PDF_RENDER_SCALE = 2  # Matches backend PyMuPDF fitz.Matrix(2, 2)
IMG_WIDTH = 1240
IMG_HEIGHT = 1754

GSTIN_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def compute_valid_gstin(prefix_14: str) -> str:
    """Compute a mathematically valid 15-char synthetic GSTIN from a 14-char prefix."""
    if len(prefix_14) != 14:
        raise ValueError("prefix_14 must be 14 characters")
    total = 0
    for idx, ch in enumerate(prefix_14):
        code = GSTIN_ALPHABET.index(ch)
        factor = 1 if idx % 2 == 0 else 2
        product = code * factor
        total += (product // 36) + (product % 36)
    check_code = (36 - (total % 36)) % 36
    return prefix_14 + GSTIN_ALPHABET[check_code]


VALID_SELLER_GSTIN = compute_valid_gstin("29KAVCH1234F1Z")
VALID_BUYER_GSTIN = compute_valid_gstin("27SYNTH5678G1Z")
INVALID_GSTIN = "99INVALID1234Z0"


def _load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.ImageFont:
    candidates = []
    if mono:
        candidates = [
            "C:/Windows/Fonts/courbd.ttf" if bold else "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class NativePdfPage:
    """Minimal vector/text PDF page builder with top-left coordinate helpers."""

    def __init__(self, width: int = PDF_WIDTH, height: int = PDF_HEIGHT) -> None:
        self.width = width
        self.height = height
        self.commands: list[str] = []

    def rect(
        self,
        x: float,
        y_top: float,
        w: float,
        h: float,
        fill_rgb: tuple[float, float, float] | None = None,
        stroke_rgb: tuple[float, float, float] | None = None,
        line_width: float = 0.8,
    ) -> None:
        y_pdf = self.height - y_top - h
        parts = []
        if fill_rgb is not None:
            parts.append(f"{fill_rgb[0]:.3f} {fill_rgb[1]:.3f} {fill_rgb[2]:.3f} rg")
        if stroke_rgb is not None:
            parts.append(f"{stroke_rgb[0]:.3f} {stroke_rgb[1]:.3f} {stroke_rgb[2]:.3f} RG")
            parts.append(f"{line_width:.2f} w")
        parts.append(f"{x:.2f} {y_pdf:.2f} {w:.2f} {h:.2f} re")
        if fill_rgb is not None and stroke_rgb is not None:
            parts.append("B")
        elif fill_rgb is not None:
            parts.append("f")
        else:
            parts.append("S")
        self.commands.append(" ".join(parts))

    def line(
        self,
        x1: float,
        y1_top: float,
        x2: float,
        y2_top: float,
        rgb: tuple[float, float, float] = (0.78, 0.82, 0.88),
        line_width: float = 0.7,
    ) -> None:
        y1 = self.height - y1_top
        y2 = self.height - y2_top
        self.commands.append(
            f"{rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} RG {line_width:.2f} w "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S"
        )

    def text(
        self,
        x: float,
        y_top: float,
        value: str,
        size: int = 10,
        bold: bool = False,
        mono: bool = False,
        rgb: tuple[float, float, float] = (0.10, 0.13, 0.18),
    ) -> dict[str, int]:
        """Draw text using top-left baseline offset and return rendered 2x bbox."""
        font_ref = "/F3" if mono else ("/F2" if bold else "/F1")
        y_baseline = self.height - y_top - size
        self.commands.append(
            f"BT {font_ref} {size} Tf {rgb[0]:.3f} {rgb[1]:.3f} {rgb[2]:.3f} rg "
            f"1 0 0 1 {x:.2f} {y_baseline:.2f} Tm ({_pdf_escape(value)}) Tj ET"
        )
        approx_w = max(12, int(round(len(value) * size * 0.56)))
        approx_h = max(12, int(round(size * 1.4)))
        return {
            "x": int(round(x * PDF_RENDER_SCALE)),
            "y": int(round(y_top * PDF_RENDER_SCALE)),
            "w": int(round(approx_w * PDF_RENDER_SCALE)),
            "h": int(round(approx_h * PDF_RENDER_SCALE)),
        }


def write_native_pdf(path: Path, pages: list[NativePdfPage]) -> None:
    """Serialize NativePdfPage instances to a valid multi-page PDF 1.4 file."""
    objects: list[bytes] = []

    def add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    # Reserve 1 (Catalog) and 2 (Pages)
    add_obj(b"")
    add_obj(b"")
    font_regular = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_bold = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    font_mono = add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    page_ids: list[int] = []
    for page in pages:
        stream_data = "\n".join(page.commands).encode("latin-1", errors="replace")
        content_id = add_obj(
            f"<< /Length {len(stream_data)} >>\nstream\n".encode("ascii")
            + stream_data
            + b"\nendstream"
        )
        page_id = add_obj(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page.width} {page.height}] "
                f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R /F3 {font_mono} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{idx} 0 obj\n".encode("ascii"))
        buf.write(obj)
        buf.write(b"\nendobj\n")

    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        buf.write(f"{off:010d} 00000 n \n".encode("ascii"))
    buf.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(buf.getvalue())


@dataclass
class InvoiceSpec:
    invoice_no: str
    date: str
    seller_gstin: str
    buyer_gstin: str
    ifsc: str
    subtotal: str
    cgst: str
    sgst: str
    igst: str
    discount: str
    grand_total: str
    tax_note: str = "GST Breakdown (9% CGST + 9% SGST = 18%)"
    anomaly_target: str | None = None  # "grand_total" | "gstin" | "tax" | None


def build_invoice_pdf(path: Path, spec: InvoiceSpec) -> dict[str, dict[str, int]]:
    """Build a crisp native-text GST invoice PDF and return key rendered regions."""
    page = NativePdfPage()
    regions: dict[str, dict[str, int]] = {}

    # Top banner
    page.rect(36, 28, 523, 30, fill_rgb=(0.09, 0.16, 0.28))
    page.text(48, 37, WATERMARK_TEXT, size=10, bold=True, rgb=(0.95, 0.97, 1.0))
    page.text(438, 37, "TAX INVOICE", size=11, bold=True, rgb=(0.80, 0.90, 1.0))

    # Seller & Invoice Metadata
    page.text(40, 74, "KAVACH TEST SUPPLIES PVT LTD", size=14, bold=True)
    page.text(40, 93, "Plot 42, Synthetic Tech Park, Bengaluru 560001 (Fictional Address)", size=9, rgb=(0.35, 0.40, 0.48))
    gstin_box = page.text(40, 108, f"GSTIN: {spec.seller_gstin}", size=10, bold=True, mono=True)
    regions["seller_gstin"] = {
        "page": 0,
        "x": gstin_box["x"] - 8,
        "y": gstin_box["y"] - 4,
        "w": gstin_box["w"] + 20,
        "h": gstin_box["h"] + 8,
    }
    page.text(40, 123, f"IFSC: {spec.ifsc}", size=9, mono=True)

    page.rect(355, 72, 204, 68, fill_rgb=(0.97, 0.98, 0.99), stroke_rgb=(0.82, 0.85, 0.90))
    page.text(365, 80, f"Invoice no: {spec.invoice_no}", size=10, bold=True)
    page.text(365, 97, f"Date: {spec.date}", size=10)
    page.text(365, 114, "Place of Supply: Karnataka (29)", size=9, rgb=(0.35, 0.40, 0.48))

    # Buyer block
    page.rect(36, 152, 523, 56, stroke_rgb=(0.84, 0.87, 0.91))
    page.text(46, 160, "Billed To: BHARAT DEMO LOGISTICS LLP (SAMPLE CUSTOMER)", size=10, bold=True)
    page.text(46, 176, "Unit 9, Fictional Industrial Area, Pune 411001", size=9, rgb=(0.35, 0.40, 0.48))
    page.text(46, 190, f"Buyer GSTIN: {spec.buyer_gstin}", size=9, mono=True)

    # Line items header
    page.rect(36, 224, 523, 24, fill_rgb=(0.93, 0.95, 0.98), stroke_rgb=(0.80, 0.84, 0.89))
    page.text(46, 231, "Item Description", size=9, bold=True)
    page.text(285, 231, "HSN", size=9, bold=True)
    page.text(350, 231, "Qty", size=9, bold=True)
    page.text(410, 231, "Rate (INR)", size=9, bold=True)
    page.text(485, 231, "Amount (INR)", size=9, bold=True)

    items = [
        ("Synthetic Server Rack Enclosure", "8537", "2", "3,200.00", "6,400.00"),
        ("Demo Fiber Patch Kit (10m)", "8544", "4", "650.00", "2,600.00"),
        ("Test Calibration Service (Mock)", "9987", "1", "1,000.00", "1,000.00"),
    ]
    y_row = 256
    for desc, hsn, qty, rate, amt in items:
        page.text(46, y_row, desc, size=9)
        page.text(285, y_row, hsn, size=9, mono=True)
        page.text(354, y_row, qty, size=9, mono=True)
        page.text(412, y_row, rate, size=9, mono=True)
        page.text(488, y_row, amt, size=9, mono=True)
        page.line(36, y_row + 18, 559, y_row + 18)
        y_row += 26

    # Tax & Totals block (formatted on clean lines for backend fields.py regexes!)
    page.rect(36, 355, 523, 140, fill_rgb=(0.98, 0.99, 1.0), stroke_rgb=(0.82, 0.85, 0.90))
    page.text(46, 366, spec.tax_note, size=9, bold=True, rgb=(0.20, 0.26, 0.35))
    page.text(46, 386, "Payment Terms: Synthetic Test Invoice Only — Not for Tax Filing", size=8, rgb=(0.45, 0.49, 0.56))

    sub_box = page.text(340, 366, f"Subtotal: INR {spec.subtotal}", size=10, mono=True)
    cgst_box = page.text(340, 386, f"CGST: INR {spec.cgst}", size=10, mono=True)
    sgst_box = page.text(340, 404, f"SGST: INR {spec.sgst}", size=10, mono=True)
    page.text(340, 422, f"IGST: INR {spec.igst}", size=10, mono=True)
    page.text(340, 440, f"Discount: INR {spec.discount}", size=10, mono=True)
    page.line(335, 459, 550, 459, rgb=(0.45, 0.50, 0.58), line_width=1.0)
    gt_box = page.text(340, 466, f"Grand total: INR {spec.grand_total}", size=11, bold=True, mono=True)

    regions["tax_block"] = {
        "page": 0,
        "x": min(cgst_box["x"], sgst_box["x"]) - 10,
        "y": cgst_box["y"] - 6,
        "w": max(cgst_box["w"], sgst_box["w"]) + 24,
        "h": (sgst_box["y"] + sgst_box["h"] - cgst_box["y"]) + 14,
    }
    regions["grand_total"] = {
        "page": 0,
        "x": gt_box["x"] - 10,
        "y": gt_box["y"] - 6,
        "w": gt_box["w"] + 28,
        "h": gt_box["h"] + 12,
    }
    _ = sub_box

    # Footer
    page.line(36, 760, 559, 760)
    page.text(36, 772, f"{WATERMARK_TEXT} | Generated for Kavach Hackathon Testing", size=8, rgb=(0.45, 0.50, 0.56))
    write_native_pdf(path, [page])
    return regions


def build_bank_statement_pdf(path: Path, tamper_balance: bool = False) -> dict[str, dict[str, int]]:
    """Build a 2-page synthetic bank statement PDF (clean or balance-tampered)."""
    p1 = NativePdfPage()
    p2 = NativePdfPage()

    for idx, page in enumerate((p1, p2), start=1):
        page.rect(36, 28, 523, 30, fill_rgb=(0.08, 0.18, 0.30))
        page.text(48, 37, WATERMARK_TEXT, size=10, bold=True, rgb=(0.95, 0.97, 1.0))
        page.text(420, 37, f"ACCOUNT STATEMENT (Page {idx}/2)", size=9, bold=True, rgb=(0.82, 0.91, 1.0))

    # Account details on Page 1
    p1.text(40, 74, "SYNTHETIC NATIONAL BANK (DEMO BRANCH)", size=13, bold=True)
    p1.text(40, 94, "Account Holder: KAVACH TEST SUPPLIES PVT LTD | Account No: 000099887766", size=9)
    p1.text(40, 109, "IFSC: SYNB0001234 | Period: 01/11/2026 to 20/11/2026", size=9, mono=True)
    p1.text(40, 128, "Opening balance: INR 150,000.00", size=10, bold=True, mono=True)

    # Table headers on both pages
    for page, start_y in ((p1, 155), (p2, 82)):
        page.rect(36, start_y, 523, 22, fill_rgb=(0.93, 0.95, 0.98), stroke_rgb=(0.80, 0.84, 0.89))
        page.text(44, start_y + 6, "Date", size=9, bold=True)
        page.text(120, start_y + 6, "Narration", size=9, bold=True)
        page.text(320, start_y + 6, "Debit (INR)", size=9, bold=True)
        page.text(398, start_y + 6, "Credit (INR)", size=9, bold=True)
        page.text(476, start_y + 6, "Balance (INR)", size=9, bold=True)

    rows_p1 = [
        ("02/11/2026", "NEFT Demo Vendor Payment", "12,500.00", "-", "137,500.00"),
        ("05/11/2026", "IMPS Synthetic Client Receipt", "-", "45,000.00", "182,500.00"),
        ("08/11/2026", "Office Utility Mock AutoDebit", "4,500.00", "-", "178,000.00"),
        ("11/11/2026", "RTGS Sample Settlement", "-", "22,000.00", "200,000.00"),
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

    p1.text(40, 772, f"{WATERMARK_TEXT} | Continued on Page 2", size=8, rgb=(0.45, 0.50, 0.56))

    # Page 2 rows
    tampered_bal_2 = "198,000.00" if tamper_balance else "188,000.00"
    closing_bal = "194,500.00" if tamper_balance else "184,500.00"
    rows_p2 = [
        ("14/11/2026", "Test Cloud Hosting Charge", "12,000.00", "-", tampered_bal_2),
        ("17/11/2026", "Synthetic Tax Refund Credit", "-", "6,500.00", "194,500.00" if tamper_balance else "194,500.00"),
        ("20/11/2026", "Mock Courier Invoice Payment", "10,000.00", "-", closing_bal),
    ]
    if tamper_balance:
        # Make row 2 carry forward consistently with tampered row 1 so inconsistency pinpoints row 1
        rows_p2[1] = ("17/11/2026", "Synthetic Tax Refund Credit", "-", "6,500.00", "204,500.00")

    regions: dict[str, dict[str, int]] = {}
    y = 112
    for idx, (dt, narr, deb, cred, bal) in enumerate(rows_p2):
        p2.text(44, y, dt, size=9, mono=True)
        p2.text(120, y, narr, size=9)
        p2.text(324, y, deb, size=9, mono=True)
        p2.text(402, y, cred, size=9, mono=True)
        bal_box = p2.text(476, y, bal, size=9, mono=True)
        if idx == 0:
            regions["tampered_row"] = {
                "page": 1,
                "x": bal_box["x"] - 10,
                "y": bal_box["y"] - 6,
                "w": bal_box["w"] + 20,
                "h": bal_box["h"] + 12,
            }
        p2.line(36, y + 17, 559, y + 17)
        y += 26

    p2.rect(36, 210, 523, 40, fill_rgb=(0.97, 0.98, 0.99), stroke_rgb=(0.82, 0.85, 0.90))
    p2.text(46, 224, f"Closing balance: INR {closing_bal}", size=10, bold=True, mono=True)
    p2.text(40, 772, f"{WATERMARK_TEXT} | End of Synthetic Statement", size=8, rgb=(0.45, 0.50, 0.56))

    write_native_pdf(path, [p1, p2])
    return regions


def _draw_stamp(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Draw a high-detail synthetic authorization stamp for visual/ORB richness."""
    blue = (24, 64, 148)
    draw.ellipse((cx - 82, cy - 52, cx + 82, cy + 52), outline=blue, width=4)
    draw.ellipse((cx - 72, cy - 42, cx + 72, cy + 42), outline=blue, width=2)
    f_sm = _load_font(15, bold=True)
    f_xs = _load_font(12, bold=True)
    draw.text((cx - 56, cy - 26), "KAVACH TEST", fill=blue, font=f_sm)
    draw.text((cx - 46, cy - 4), "SAMPLE SEAL", fill=blue, font=f_xs)
    draw.text((cx - 38, cy + 16), "2026-11-25", fill=blue, font=f_xs)
    # Crosshatch tick marks for distinct local features
    for angle_off in range(-60, 65, 20):
        draw.line((cx + angle_off, cy - 40, cx + angle_off + 6, cy - 32), fill=blue, width=2)
        draw.line((cx + angle_off, cy + 32, cx + angle_off + 6, cy + 40), fill=blue, width=2)


def render_invoice_image(
    grand_total: str = "11,800.00",
    invoice_no: str = "INV-2026-101",
    include_stamp: bool = True,
) -> tuple[Image.Image, dict[str, dict[str, int]]]:
    """Render a high-resolution raster invoice image and return region coordinates."""
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    f_title = _load_font(30, bold=True)
    f_h2 = _load_font(22, bold=True)
    f_body = _load_font(20)
    f_bold = _load_font(20, bold=True)
    f_mono = _load_font(20, mono=True)
    f_mono_bold = _load_font(22, bold=True, mono=True)
    f_small = _load_font(16)

    # Banner
    draw.rectangle((60, 50, IMG_WIDTH - 60, 118), fill=(22, 41, 72))
    draw.text((86, 70), WATERMARK_TEXT, fill=(240, 245, 255), font=f_bold)
    draw.text((IMG_WIDTH - 245, 70), "TAX INVOICE", fill=(195, 222, 255), font=f_h2)

    # Header
    draw.text((70, 150), "KAVACH TEST SUPPLIES PVT LTD", fill=(20, 28, 40), font=f_title)
    draw.text((70, 194), "Plot 42, Synthetic Tech Park, Bengaluru 560001", fill=(90, 102, 118), font=f_body)
    draw.text((70, 226), f"GSTIN: {VALID_SELLER_GSTIN}", fill=(20, 28, 40), font=f_mono_bold)
    draw.text((70, 258), "IFSC: SYNB0001234", fill=(20, 28, 40), font=f_mono)

    draw.rectangle((760, 146, IMG_WIDTH - 60, 290), fill=(246, 248, 252), outline=(206, 214, 226), width=2)
    draw.text((785, 166), f"Invoice no: {invoice_no}", fill=(20, 28, 40), font=f_bold)
    draw.text((785, 202), "Date: 25/11/2026", fill=(20, 28, 40), font=f_body)
    draw.text((785, 238), "State: Karnataka (29)", fill=(90, 102, 118), font=f_body)

    # Buyer
    draw.rectangle((60, 320, IMG_WIDTH - 60, 440), outline=(210, 218, 228), width=2)
    draw.text((82, 338), "Billed To: BHARAT DEMO LOGISTICS LLP (SAMPLE)", fill=(20, 28, 40), font=f_bold)
    draw.text((82, 372), "Unit 9, Fictional Industrial Area, Pune 411001", fill=(90, 102, 118), font=f_body)
    draw.text((82, 404), f"Buyer GSTIN: {VALID_BUYER_GSTIN}", fill=(20, 28, 40), font=f_mono)

    # Table
    draw.rectangle((60, 470, IMG_WIDTH - 60, 524), fill=(236, 241, 248), outline=(198, 208, 220), width=2)
    draw.text((82, 486), "Item Description", fill=(20, 28, 40), font=f_bold)
    draw.text((640, 486), "HSN", fill=(20, 28, 40), font=f_bold)
    draw.text((760, 486), "Qty", fill=(20, 28, 40), font=f_bold)
    draw.text((880, 486), "Rate", fill=(20, 28, 40), font=f_bold)
    draw.text((1030, 486), "Amount", fill=(20, 28, 40), font=f_bold)

    rows = [
        ("Synthetic Server Rack Enclosure", "8537", "2", "3,200.00", "6,400.00"),
        ("Demo Fiber Patch Kit (10m)", "8544", "4", "650.00", "2,600.00"),
        ("Test Calibration Service (Mock)", "9987", "1", "1,000.00", "1,000.00"),
    ]
    y = 548
    for desc, hsn, qty, rate, amt in rows:
        draw.text((82, y), desc, fill=(25, 32, 42), font=f_body)
        draw.text((640, y), hsn, fill=(25, 32, 42), font=f_mono)
        draw.text((766, y), qty, fill=(25, 32, 42), font=f_mono)
        draw.text((880, y), rate, fill=(25, 32, 42), font=f_mono)
        draw.text((1030, y), amt, fill=(25, 32, 42), font=f_mono)
        draw.line((60, y + 40, IMG_WIDTH - 60, y + 40), fill=(224, 230, 238), width=2)
        y += 62

    # Totals box
    draw.rectangle((60, 760, IMG_WIDTH - 60, 1080), fill=(250, 251, 253), outline=(206, 214, 226), width=2)
    draw.text((82, 788), "GST Breakdown (9% CGST + 9% SGST)", fill=(45, 58, 78), font=f_bold)
    draw.text((82, 824), "Not a real financial instrument.", fill=(110, 120, 134), font=f_small)

    draw.text((710, 784), "Subtotal: INR 10,000.00", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 824), "CGST: INR 900.00", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 864), "SGST: INR 900.00", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 904), "IGST: INR 0.00", fill=(25, 32, 42), font=f_mono)
    draw.text((710, 944), "Discount: INR 0.00", fill=(25, 32, 42), font=f_mono)
    draw.line((700, 984, IMG_WIDTH - 80, 984), fill=(120, 132, 148), width=2)

    gt_rect = {"page": 0, "x": 695, "y": 994, "w": 475, "h": 68}
    draw.text((710, 1008), f"Grand total: INR {grand_total}", fill=(15, 23, 42), font=f_mono_bold)

    stamp_rect = {"page": 0, "x": 115, "y": 905, "w": 180, "h": 120}
    if include_stamp:
        _draw_stamp(draw, 205, 965)

    draw.line((60, 1600, IMG_WIDTH - 60, 1600), fill=(210, 218, 228), width=2)
    draw.text((70, 1624), f"{WATERMARK_TEXT} | Kavach Dataset", fill=(110, 120, 134), font=f_small)
    return img, {"grand_total": gt_rect, "stamp": stamp_rect}


def add_scan_effects(img: Image.Image, rng: np.random.Generator, sigma: float = 3.5, angle: float = -0.5) -> Image.Image:
    """Apply subtle scanner tilt, warm paper tint, and uniform Gaussian noise."""
    rotated = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(248, 246, 240))
    arr = np.asarray(rotated, dtype=np.float32)
    noise = rng.normal(0.0, sigma, size=arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy, mode="RGB").filter(ImageFilter.GaussianBlur(radius=0.35))


def scanned_pdf_rendered_dims(
    img_w: int = IMG_WIDTH,
    img_h: int = IMG_HEIGHT,
    resolution: int = 150,
    scale: int = PDF_RENDER_SCALE,
) -> tuple[int, int]:
    """Return PyMuPDF 2x rendered pixel dimensions for an image-embedded PDF."""
    pt_w = img_w * 72.0 / resolution
    pt_h = img_h * 72.0 / resolution
    return math.ceil(pt_w * scale - 0.001), math.ceil(pt_h * scale - 0.001)


def transform_scanned_pdf_box(
    box: dict[str, int],
    angle: float,
    src_w: int = IMG_WIDTH,
    src_h: int = IMG_HEIGHT,
    resolution: int = 150,
    scale: int = PDF_RENDER_SCALE,
) -> dict[str, int]:
    """Transform source-image box through PIL rotation and 2x PDF rendering."""
    cx, cy = src_w / 2.0, src_h / 2.0
    theta = math.radians(-angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    corners = [
        (box["x"], box["y"]),
        (box["x"] + box["w"], box["y"]),
        (box["x"], box["y"] + box["h"]),
        (box["x"] + box["w"], box["y"] + box["h"]),
    ]
    rot_pts = [
        (cx + (px - cx) * cos_t - (py - cy) * sin_t, cy + (px - cx) * sin_t + (py - cy) * cos_t)
        for px, py in corners
    ]
    rx0 = max(0.0, min(p[0] for p in rot_pts))
    ry0 = max(0.0, min(p[1] for p in rot_pts))
    rx1 = min(float(src_w), max(p[0] for p in rot_pts))
    ry1 = min(float(src_h), max(p[1] for p in rot_pts))

    out_w, out_h = scanned_pdf_rendered_dims(src_w, src_h, resolution=resolution, scale=scale)
    sx, sy = out_w / src_w, out_h / src_h
    return {
        "page": box["page"],
        "x": int(round(rx0 * sx)),
        "y": int(round(ry0 * sy)),
        "w": max(1, int(round((rx1 - rx0) * sx))),
        "h": max(1, int(round((ry1 - ry0) * sy))),
    }


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
    random.seed(42)
    rng = np.random.default_rng(42)

    for directory in (CLEAN_DIR, TAMPERED_DIR, GT_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    pdf_dims = [{"page": 0, "width": PDF_WIDTH * PDF_RENDER_SCALE, "height": PDF_HEIGHT * PDF_RENDER_SCALE}]
    pdf_2p_dims = [
        {"page": 0, "width": PDF_WIDTH * PDF_RENDER_SCALE, "height": PDF_HEIGHT * PDF_RENDER_SCALE},
        {"page": 1, "width": PDF_WIDTH * PDF_RENDER_SCALE, "height": PDF_HEIGHT * PDF_RENDER_SCALE},
    ]
    img_dims = [{"page": 0, "width": IMG_WIDTH, "height": IMG_HEIGHT}]

    # 1. Clean native GST invoice PDF
    build_invoice_pdf(
        CLEAN_DIR / "invoice_clean_gst_01.pdf",
        InvoiceSpec(
            invoice_no="INV-2026-001",
            date="25/11/2026",
            seller_gstin=VALID_SELLER_GSTIN,
            buyer_gstin=VALID_BUYER_GSTIN,
            ifsc="SYNB0001234",
            subtotal="10,000.00",
            cgst="900.00",
            sgst="900.00",
            igst="0.00",
            discount="0.00",
            grand_total="11,800.00",
        ),
    )
    manifest.append(
        write_gt(
            stem="invoice_clean_gst_01",
            relative_path="dataset/clean/invoice_clean_gst_01.pdf",
            document_type="gst_invoice",
            label="clean",
            fmt="pdf",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=pdf_dims,
            notes="Clean synthetic native-text GST invoice with valid GSTIN and consistent arithmetic.",
        )
    )

    # 2. Clean PNG and JPEG invoices
    clean_img, _ = render_invoice_image(grand_total="11,800.00", invoice_no="INV-2026-002")
    clean_img.save(CLEAN_DIR / "invoice_clean_01.png", format="PNG")
    clean_img.save(CLEAN_DIR / "invoice_clean_01.jpg", format="JPEG", quality=92)
    manifest.append(
        write_gt(
            stem="invoice_clean_01_png",
            relative_path="dataset/clean/invoice_clean_01.png",
            document_type="gst_invoice",
            label="clean",
            fmt="png",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=img_dims,
            notes="Clean synthetic PNG GST invoice for OCR and image pipeline testing.",
        )
    )
    manifest.append(
        write_gt(
            stem="invoice_clean_01_jpg",
            relative_path="dataset/clean/invoice_clean_01.jpg",
            document_type="gst_invoice",
            label="clean",
            fmt="jpg",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=img_dims,
            notes="Clean synthetic JPEG GST invoice for ELA baseline and OCR testing.",
        )
    )

    # 3. Clean scanned-style PDF
    scanned_w, scanned_h = scanned_pdf_rendered_dims(IMG_WIDTH, IMG_HEIGHT, resolution=150)
    scanned_pdf_dims = [{"page": 0, "width": scanned_w, "height": scanned_h}]
    scanned_clean = add_scan_effects(clean_img, rng, sigma=3.0, angle=-0.5)
    scanned_clean.save(CLEAN_DIR / "invoice_scanned_clean_01.pdf", format="PDF", resolution=150)
    manifest.append(
        write_gt(
            stem="invoice_scanned_clean_01",
            relative_path="dataset/clean/invoice_scanned_clean_01.pdf",
            document_type="gst_invoice_scanned",
            label="clean",
            fmt="pdf",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=scanned_pdf_dims,
            notes="Clean scanned-style image PDF (forces OCR extraction path).",
        )
    )

    # 4. Clean 2-page synthetic bank statement PDF
    build_bank_statement_pdf(CLEAN_DIR / "bank_statement_clean_01.pdf", tamper_balance=False)
    manifest.append(
        write_gt(
            stem="bank_statement_clean_01",
            relative_path="dataset/clean/bank_statement_clean_01.pdf",
            document_type="bank_statement",
            label="clean",
            fmt="pdf",
            expected_anomalies=[],
            affected_page=None,
            known_affected_regions=[],
            page_dimensions=pdf_2p_dims,
            notes="Clean 2-page synthetic bank statement with consistent running balances.",
        )
    )

    # 5. Tampered: Inconsistent grand total PDF
    gt_regions = build_invoice_pdf(
        TAMPERED_DIR / "invoice_tampered_grand_total.pdf",
        InvoiceSpec(
            invoice_no="INV-2026-102",
            date="25/11/2026",
            seller_gstin=VALID_SELLER_GSTIN,
            buyer_gstin=VALID_BUYER_GSTIN,
            ifsc="SYNB0001234",
            subtotal="10,000.00",
            cgst="900.00",
            sgst="900.00",
            igst="0.00",
            discount="0.00",
            grand_total="19,800.00",
            anomaly_target="grand_total",
        ),
    )
    manifest.append(
        write_gt(
            stem="invoice_tampered_grand_total",
            relative_path="dataset/tampered/invoice_tampered_grand_total.pdf",
            document_type="gst_invoice",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "grand_total_mismatch",
                    "description": "Subtotal (10,000.00) + CGST (900.00) + SGST (900.00) = 11,800.00, but Grand total reads 19,800.00.",
                }
            ],
            affected_page=0,
            known_affected_regions=[{**gt_regions["grand_total"], "description": "Altered Grand total value"}],
            page_dimensions=pdf_dims,
            notes="Consistency test: inflated grand total.",
        )
    )

    # 6. Tampered: Invalid GSTIN PDF
    gstin_regions = build_invoice_pdf(
        TAMPERED_DIR / "invoice_tampered_invalid_gstin.pdf",
        InvoiceSpec(
            invoice_no="INV-2026-103",
            date="25/11/2026",
            seller_gstin=INVALID_GSTIN,
            buyer_gstin=VALID_BUYER_GSTIN,
            ifsc="SYNB0001234",
            subtotal="10,000.00",
            cgst="900.00",
            sgst="900.00",
            igst="0.00",
            discount="0.00",
            grand_total="11,800.00",
            anomaly_target="gstin",
        ),
    )
    manifest.append(
        write_gt(
            stem="invoice_tampered_invalid_gstin",
            relative_path="dataset/tampered/invoice_tampered_invalid_gstin.pdf",
            document_type="gst_invoice",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "invalid_gstin",
                    "description": f"Seller GSTIN '{INVALID_GSTIN}' fails Indian GSTIN structure/state-code/checksum rules.",
                }
            ],
            affected_page=0,
            known_affected_regions=[{**gstin_regions["seller_gstin"], "description": "Invalid Seller GSTIN"}],
            page_dimensions=pdf_dims,
            notes="Consistency test: malformed GSTIN with invalid state code 99 and pattern.",
        )
    )

    # 7. Tampered: Inconsistent tax amounts PDF
    tax_regions = build_invoice_pdf(
        TAMPERED_DIR / "invoice_tampered_tax_mismatch.pdf",
        InvoiceSpec(
            invoice_no="INV-2026-104",
            date="25/11/2026",
            seller_gstin=VALID_SELLER_GSTIN,
            buyer_gstin=VALID_BUYER_GSTIN,
            ifsc="SYNB0001234",
            subtotal="10,000.00",
            cgst="1,400.00",
            sgst="900.00",
            igst="0.00",
            discount="0.00",
            grand_total="12,300.00",
            anomaly_target="tax",
        ),
    )
    manifest.append(
        write_gt(
            stem="invoice_tampered_tax_mismatch",
            relative_path="dataset/tampered/invoice_tampered_tax_mismatch.pdf",
            document_type="gst_invoice",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "tax_inconsistency",
                    "description": "Declared 9% CGST + 9% SGST on 10,000.00 should be 900.00 each, but CGST is 1,400.00 (asymmetric with SGST 900.00).",
                }
            ],
            affected_page=0,
            known_affected_regions=[{**tax_regions["tax_block"], "description": "Asymmetric CGST/SGST tax lines"}],
            page_dimensions=pdf_dims,
            notes="Consistency test: CGST and SGST mismatch against declared 9% + 9% rate.",
        )
    )

    # 8. Tampered: 2-page bank statement with running balance inconsistency
    bank_regions = build_bank_statement_pdf(TAMPERED_DIR / "bank_statement_tampered_balance.pdf", tamper_balance=True)
    manifest.append(
        write_gt(
            stem="bank_statement_tampered_balance",
            relative_path="dataset/tampered/bank_statement_tampered_balance.pdf",
            document_type="bank_statement",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "running_balance_mismatch",
                    "description": "Page 2 row 1 (14/11/2026): previous balance 200,000.00 minus debit 12,000.00 should be 188,000.00, but reads 198,000.00.",
                }
            ],
            affected_page=1,
            known_affected_regions=[{**bank_regions["tampered_row"], "description": "Inconsistent running balance on page 2"}],
            page_dimensions=pdf_2p_dims,
            notes="Multi-page consistency test: running balance inflated by 10,000.00 on page 2.",
        )
    )

    # 9. Tampered: Scanned-style PDF with altered Grand Total
    tampered_scan_base, scan_boxes = render_invoice_image(grand_total="18,800.00", invoice_no="INV-2026-105")
    tampered_scan = add_scan_effects(tampered_scan_base, rng, sigma=3.5, angle=-0.6)
    tampered_scan.save(TAMPERED_DIR / "invoice_scanned_tampered_total.pdf", format="PDF", resolution=150)
    transformed_scan_box = transform_scanned_pdf_box(scan_boxes["grand_total"], angle=-0.6)
    manifest.append(
        write_gt(
            stem="invoice_scanned_tampered_total",
            relative_path="dataset/tampered/invoice_scanned_tampered_total.pdf",
            document_type="gst_invoice_scanned",
            label="tampered",
            fmt="pdf",
            expected_anomalies=[
                {
                    "category": "consistency",
                    "code": "grand_total_mismatch",
                    "description": "Scanned invoice Grand total reads 18,800.00 instead of 11,800.00.",
                }
            ],
            affected_page=0,
            known_affected_regions=[{**transformed_scan_box, "description": "Altered Grand total on scanned invoice"}],
            page_dimensions=scanned_pdf_dims,
            notes="Scanned-style PDF requiring OCR to detect grand total arithmetic discrepancy.",
        )
    )

    # 10. Visual Tampering Sample A: JPEG ELA splice (Member 2)
    ela_base, ela_boxes = render_invoice_image(grand_total="11,800.00", invoice_no="INV-2026-201")
    ela_buf = io.BytesIO()
    ela_base.save(ela_buf, format="JPEG", quality=95)
    ela_buf.seek(0)
    ela_img = Image.open(ela_buf).convert("RGB")

    # Create a visibly recompressed splice patch at low quality (q=40) with altered total
    splice_source, _ = render_invoice_image(grand_total="31,800.00", invoice_no="INV-2026-201")
    box = ela_boxes["grand_total"]
    crop = splice_source.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))
    low_q_buf = io.BytesIO()
    crop.save(low_q_buf, format="JPEG", quality=35)
    low_q_buf.seek(0)
    spliced_patch = Image.open(low_q_buf).convert("RGB")
    ela_img.paste(spliced_patch, (box["x"], box["y"]))
    ela_img.save(TAMPERED_DIR / "invoice_tampered_visual_ela.jpg", format="JPEG", quality=95)
    manifest.append(
        write_gt(
            stem="invoice_tampered_visual_ela",
            relative_path="dataset/tampered/invoice_tampered_visual_ela.jpg",
            document_type="gst_invoice",
            label="tampered",
            fmt="jpg",
            expected_anomalies=[
                {
                    "category": "visual",
                    "code": "ela_compression_splice",
                    "description": "Grand total region pasted from a lower-quality JPEG (q=35) onto a q=95 invoice.",
                },
                {
                    "category": "consistency",
                    "code": "grand_total_mismatch",
                    "description": "Altered Grand total reads 31,800.00 instead of 11,800.00.",
                },
            ],
            affected_page=0,
            known_affected_regions=[{**box, "description": "JPEG splice over Grand total"}],
            page_dimensions=img_dims,
            notes="Member 2 ELA test sample: localized compression history mismatch over Grand total.",
        )
    )

    # 11. Visual Tampering Sample B: Copy-Move cloned stamp (Member 2)
    cm_img, cm_boxes = render_invoice_image(grand_total="11,800.00", invoice_no="INV-2026-202", include_stamp=True)
    sbox = cm_boxes["stamp"]
    stamp_crop = cm_img.crop((sbox["x"], sbox["y"], sbox["x"] + sbox["w"], sbox["y"] + sbox["h"]))
    clone_dest = (385, 905)
    cm_img.paste(stamp_crop, clone_dest)
    cm_img.save(TAMPERED_DIR / "invoice_tampered_visual_copy_move.png", format="PNG")
    manifest.append(
        write_gt(
            stem="invoice_tampered_visual_copy_move",
            relative_path="dataset/tampered/invoice_tampered_visual_copy_move.png",
            document_type="gst_invoice",
            label="tampered",
            fmt="png",
            expected_anomalies=[
                {
                    "category": "visual",
                    "code": "copy_move_clone",
                    "description": "Authorization stamp cloned verbatim from left block to center-left block.",
                }
            ],
            affected_page=0,
            known_affected_regions=[
                {**sbox, "description": "Original stamp source region"},
                {
                    "page": 0,
                    "x": clone_dest[0],
                    "y": clone_dest[1],
                    "w": sbox["w"],
                    "h": sbox["h"],
                    "description": "Cloned copy-move stamp region",
                },
            ],
            page_dimensions=img_dims,
            notes="Member 2 Copy-Move test sample: exact pixel clone of textured authorization stamp.",
        )
    )

    # 12. Visual Tampering Sample C: Local Noise Inconsistency (Member 2)
    noise_base, n_boxes = render_invoice_image(grand_total="11,800.00", invoice_no="INV-2026-203")
    noise_bg = add_scan_effects(noise_base, rng, sigma=4.5, angle=0.0)
    # Create an overly noisy synthetic patch over a larger area covering multiple 48x48 blocks
    patch_box = {"page": 0, "x": 680, "y": 980, "w": 500, "h": 140}
    patch_src, _ = render_invoice_image(grand_total="41,800.00", invoice_no="INV-2026-203")
    patch_crop = patch_src.crop(
        (patch_box["x"], patch_box["y"], patch_box["x"] + patch_box["w"], patch_box["y"] + patch_box["h"])
    )
    patch_arr = np.asarray(patch_crop, dtype=np.float32)
    high_noise = rng.normal(0.0, 16.0, size=patch_arr.shape)
    patch_noisy = Image.fromarray(np.clip(patch_arr + high_noise, 0, 255).astype(np.uint8), mode="RGB")
    noise_bg.paste(patch_noisy, (patch_box["x"], patch_box["y"]))
    noise_bg.save(TAMPERED_DIR / "invoice_tampered_visual_noise.png", format="PNG")
    _ = n_boxes
    manifest.append(
        write_gt(
            stem="invoice_tampered_visual_noise",
            relative_path="dataset/tampered/invoice_tampered_visual_noise.png",
            document_type="gst_invoice",
            label="tampered",
            fmt="png",
            expected_anomalies=[
                {
                    "category": "visual",
                    "code": "noise_inconsistency",
                    "description": "Grand total region exhibits elevated sensor/grain noise (sigma=16) vs page background (sigma=4.5).",
                },
                {
                    "category": "consistency",
                    "code": "grand_total_mismatch",
                    "description": "Altered Grand total reads 41,800.00 instead of 11,800.00.",
                },
            ],
            affected_page=0,
            known_affected_regions=[{**patch_box, "description": "High-noise spliced patch over Grand total"}],
            page_dimensions=img_dims,
            notes="Member 2 Noise Inconsistency test sample: >= 48x48 block noise outlier over Grand total.",
        )
    )

    # 13. Visual/Metadata Sample D: EXIF Software & Timestamp Mismatch (Member 2)
    meta_img, meta_boxes = render_invoice_image(grand_total="11,800.00", invoice_no="INV-2026-204")
    exif = Image.Exif()
    exif[0x0131] = "Adobe Photoshop CC 2024 (Windows)"  # Software
    exif[0x0132] = "2026:11:24 18:30:00"  # DateTime
    exif[0x9003] = "2026:11:20 10:00:00"  # DateTimeOriginal (>24h earlier)
    meta_img.save(TAMPERED_DIR / "invoice_tampered_metadata_edited.jpg", format="JPEG", quality=92, exif=exif)
    _ = meta_boxes
    manifest.append(
        write_gt(
            stem="invoice_tampered_metadata_edited",
            relative_path="dataset/tampered/invoice_tampered_metadata_edited.jpg",
            document_type="gst_invoice",
            label="tampered",
            fmt="jpg",
            expected_anomalies=[
                {
                    "category": "image_metadata",
                    "code": "editing_software_exif",
                    "description": "EXIF Software tag indicates 'Adobe Photoshop CC 2024 (Windows)' with >24h DateTime vs DateTimeOriginal gap.",
                }
            ],
            affected_page=0,
            known_affected_regions=[],
            page_dimensions=img_dims,
            notes="Member 2 Image Metadata test sample: EXIF editing software keyword and timestamp discrepancy.",
        )
    )

    (GT_DIR / "manifest.json").write_text(
        json.dumps({"total_samples": len(manifest), "samples": manifest}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {len(manifest)} synthetic test documents and ground-truth annotations.")


if __name__ == "__main__":
    main()
