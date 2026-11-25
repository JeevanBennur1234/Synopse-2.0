import io, re, os
from pathlib import Path
import fitz
from PIL import Image, ImageOps
import pytesseract
import time
import cv2
import numpy as np

MAX_PAGES = 30
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
if os.environ.get("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
elif Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists():
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def validate(data: bytes) -> str:
    try:
        if data.startswith(b"%PDF-"):
            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise ValueError("Password-protected PDF is not supported")
                if not 1 <= len(doc) <= MAX_PAGES:
                    raise ValueError(f"PDF has {len(doc)} pages; allowed range is 1-{MAX_PAGES}")
                for page in doc:
                    if page.rect.width * page.rect.height * 4 > MAX_PIXELS:
                        raise ValueError("PDF page too large")
            return ".pdf"
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("PNG", "JPEG") or im.width * im.height > MAX_PIXELS:
                raise ValueError("Only PNG/JPEG images up to 20 megapixels are supported")
            suffix = ".png" if im.format == "PNG" else ".jpg"
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.load()
        return suffix
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unreadable or corrupt document; upload a valid PDF, PNG or JPEG") from exc

def _ocr_pass(image, index, config='', timeout=20):
    data = pytesseract.image_to_data(ImageOps.autocontrast(image.convert("L")), output_type=pytesseract.Output.DICT, config=config, timeout=timeout)
    words = []
    for i, text in enumerate(data["text"]):
        if text.strip():
            words.append(dict(text=text, page=index, x=data["left"][i], y=data["top"][i], w=data["width"][i], h=data["height"][i], confidence=max(0, float(data["conf"][i]))/100))
    return words

def _scale_words(words, scale):
    if scale == 1.0:
        return words
    scaled = []
    for word in words:
        w = dict(word)
        for key in ("x", "y", "w", "h"):
            w[key] = max(1 if key in ("w", "h") else 0, round(w[key] / scale))
        scaled.append(w)
    return scaled


def _merge_tokens_by_confidence(base_words, cand_words):
    """Keep the higher-confidence token when two passes overlap spatially, without inflating confidence."""
    if not base_words:
        return cand_words
    if not cand_words:
        return base_words
    merged = list(base_words)
    for cw in cand_words:
        cx = cw["x"] + cw["w"] * 0.5
        cy = cw["y"] + cw["h"] * 0.5
        matched_idx = None
        for idx, bw in enumerate(merged):
            if bw["x"] <= cx <= bw["x"] + bw["w"] and bw["y"] <= cy <= bw["y"] + bw["h"]:
                matched_idx = idx
                break
        if matched_idx is not None:
            if cw["confidence"] > merged[matched_idx]["confidence"]:
                merged[matched_idx] = cw
        else:
            merged.append(cw)
    return merged


def ocr(image, index):
    start = time.monotonic()
    original = _ocr_pass(image, index)
    def quality(words):
        return sum(w["confidence"] for w in words) / max(1, len(words))
    if quality(original) >= 0.72 and len(original) >= 15:
        return original

    scale = min(3.0, max(1.0, 1600 / max(image.size)))
    gray_base = np.asarray(image.convert("L"))
    if scale > 1.0:
        gray_base = cv2.resize(gray_base, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Candidate 1: Denoise + CLAHE (--psm 6)
    denoised = cv2.fastNlMeansDenoising(gray_base, None, 7, 7, 21)
    clahe_img = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    # Candidate 2: Local adaptive threshold for shadowed/watermarked images (--psm 6 / --psm 4)
    thresh_img = cv2.adaptiveThreshold(
        clahe_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
    )

    candidates = [
        (clahe_img, "--psm 6"),
        (thresh_img, "--psm 6"),
        (clahe_img, "--psm 4"),
    ]
    best = original
    for img_arr, psm in candidates:
        remaining = 4.5 - (time.monotonic() - start)
        if remaining < 0.6:
            break
        try:
            pass_words = _scale_words(_ocr_pass(Image.fromarray(img_arr), index, psm, remaining), scale)
        except (RuntimeError, pytesseract.TesseractError):
            continue
        if len(pass_words) >= max(5, int(len(original) * 0.7)) and quality(pass_words) > quality(best):
            best = pass_words
        elif len(pass_words) >= max(5, int(len(original) * 0.7)) and quality(pass_words) >= quality(best) - 0.03:
            best = _merge_tokens_by_confidence(best, pass_words)
    return best

from app.preprocessing.fields import extract, extract_native_amounts

def process(source: Path):
    pages, warnings = [], []
    def add(image, index, words=None, text=None):
        image.save(source.parent / f"page-{index}.png")
        method = "native_pdf"
        if not words:
            method = "ocr"
            try:
                words = ocr(image, index)
            except (pytesseract.TesseractNotFoundError, RuntimeError, pytesseract.TesseractError):
                words = []
                warnings.append(f"Page {index}: OCR unavailable or failed")
            text = " ".join(w["text"] for w in words)
            # Preserve line breaks for field extraction using OCR text output.
            if words:
                lines = {}
                for w in words:
                    key = next((k for k in lines if abs(k-w["y"]) <= max(3,w["h"]//2)), w["y"])
                    lines.setdefault(key, []).append(w)
                text = "\n".join(" ".join(w["text"] for w in sorted(lines[k], key=lambda x:x["x"])) for k in sorted(lines))
        if not words:
            warnings.append(f"Page {index}: no readable text")
        elif method == "ocr" and sum(w["confidence"] for w in words)/len(words) < 0.6:
            warnings.append(f"Page {index}: low OCR confidence")
        pages.append(dict(page=index,width=image.width,height=image.height,text=text or "",words=words,method=method))
    if source.suffix == ".pdf":
        with fitz.open(source) as doc:
            for i,p in enumerate(doc):
                pix=p.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                image=Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
                words=[]
                for x0,y0,x1,y1,t,*_ in p.get_text("words"):
                    rect=fitz.Rect(x0,y0,x1,y1)*p.rotation_matrix
                    words.append(dict(text=t,page=i,x=round(rect.x0*2),y=round(rect.y0*2),w=max(1,round(rect.width*2)),h=max(1,round(rect.height*2)),confidence=None))
                add(image,i,words,p.get_text())
    else:
        with Image.open(source) as im:
            add(im.convert("RGB"),0)
    fields = extract("\n".join(p["text"] for p in pages))
    for key, values in extract_native_amounts(pages).items():
        ocr_values = extract("\n".join(p["text"] for p in pages if p["method"] == "ocr"))[key]
        fields[key] = list(dict.fromkeys(values + ocr_values))
    return pages, fields, warnings
