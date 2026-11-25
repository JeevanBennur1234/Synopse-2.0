import io, re, os
from pathlib import Path
import fitz
from PIL import Image, ImageOps
import pytesseract

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

def ocr(image, index):
    data = pytesseract.image_to_data(ImageOps.autocontrast(image.convert("L")), output_type=pytesseract.Output.DICT, timeout=20)
    words = []
    for i, text in enumerate(data["text"]):
        if text.strip():
            words.append(dict(text=text, page=index, x=data["left"][i], y=data["top"][i], w=data["width"][i], h=data["height"][i], confidence=max(0, float(data["conf"][i]))/100))
    return words

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
