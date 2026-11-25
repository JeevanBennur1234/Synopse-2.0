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
