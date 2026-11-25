from pathlib import Path
import hashlib, io, json, random, secrets
import fitz
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

out = Path("dataset/holdout_b")
out.mkdir()
seed = secrets.randbits(64)
rng = random.Random(seed)
samples = []
font = ImageFont.truetype("arial.ttf", 29)

def gst(prefix):
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = [alphabet.index(c) * (2 - i % 2) for i, c in enumerate(reversed(prefix))]
    return prefix + alphabet[-sum(d // 36 + d % 36 for d in digits) % 36]

def invoice():
    doc = fitz.open()
    page = doc.new_page(width=620, height=790)
    page.draw_rect((28, 26, 591, 95), color=None, fill=(.92, .96, .94))
    def text(x,y,value): page.insert_text((x,y),str(value),fontsize=12)
    text(44,53,"MOSS CIRCUIT LAB / SYNTHETIC TEST")
    text(44,76,f"Invoice No: MC-{rng.randrange(100000,999999)}")
    original = gst(f"29AABFM{rng.randrange(1000,9999)}Q1Z")
    text(44,130,f"GSTIN: {original}")
    text(380,130,"Place of Supply: Karnataka")
    text(44,160,"Invoice Date: 07/10/2025")
    text(380,160,"IFSC: HDFC0006472")
    for x,label in zip((45,275,365,485),("Description","Qty","Rate","Amount")):
        text(x,214,label)
    subtotal=0
    for row,name in enumerate(("Calibrate oscillator","Inspect terminal rack","Document load curve")):
        qty,rate=rng.randint(2,7),rng.randrange(10,70)*100
        amount=qty*rate
        subtotal+=amount
        for x,value in zip((45,275,365,485),(name,qty,f"{rate:,.2f}",f"{amount:,.2f}")):
            text(x,245+27*row,value)
    tax=subtotal*9//100
    total=subtotal+2*tax
    for y,(label,value) in zip((390,444,498,552),(("Taxable Amount",subtotal),("CGST (9%)",tax),("SGST (9%)",tax),("Grand Total",total))):
        text(425,y,label)
        text(425,y+20,f"{value:,.2f}")
    text(45,722,"Synthetic test data. No payment due.")
    doc.set_metadata(dict(producer="Synthetic fixture",creationDate="D:20251007100000Z",modDate="D:20251007120000Z"))
    return doc,dict(subtotal=subtotal,tax=tax,total=total,gstin=original)

def image(doc):
    pix=doc[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
    return Image.frombytes("RGB",(pix.width,pix.height),pix.samples)

def jpeg(im,quality):
    buf=io.BytesIO()
    im.save(buf,format="JPEG",quality=quality)
    return buf.getvalue()

def save_pdf(doc,name):
    doc.save(out/name)
    doc.close()

def record(name,case,label,**extra):
    samples.append(dict(file=name,case=case,label=label,sha256=hashlib.sha256((out/name).read_bytes()).hexdigest(),**extra))

def replace(page, old, new):
    rect=page.search_for(old)[0]
    page.add_redact_annot(rect,fill=(1,1,1))
    page.apply_redactions()
    page.insert_text((rect.x0,rect.y1-3.6),new,fontsize=12)
    return list(rect)

doc,_=invoice();save_pdf(doc,"01_erp.pdf");record("01_erp.pdf","native separate-line invoice","clean")
doc,_=invoice(); im=image(doc);doc.close()
ImageEnhance.Brightness(im).enhance(.94).rotate(-4,expand=True,fillcolor=(120,113,106)).save(out/"02_photo_proxy.jpg",quality=84)
record("02_photo_proxy.jpg","simulated photographed printout","clean")
doc,_=invoice();im=image(doc);doc.close()
doc=fitz.open();p=doc.new_page(width=620,height=790);p.insert_image(p.rect,stream=jpeg(im.convert("L"),80))
save_pdf(doc,"03_scan.pdf");record("03_scan.pdf","image-only scanned PDF proxy","clean")
doc=fitz.open(); balance=36400
for i in range(2):
    p=doc.new_page(width=620,height=790)
    p.insert_text((44,56),f"MOSS CREDIT UNION / SYNTHETIC BANK STATEMENT {i+1}/2")
    p.insert_text((44,80),f"Opening Balance: {balance:,.2f}")
    for x,t in zip((45,148,340,422,510),("Date","Description","Debit","Credit","Balance")):p.insert_text((x,122),t)
    for j in range(6):
        v=rng.randrange(300,1900); debit=j%2==0; balance+=-v if debit else v
        for x,t in zip((45,148,340,422,510),(f"{i*6+j+1:02}/10/2025","Clearing "+str(rng.randrange(10000,99999)),f"{v:,.2f}" if debit else "0.00","0.00" if debit else f"{v:,.2f}",f"{balance:,.2f}")):p.insert_text((x,152+j*29),t,fontsize=10)
    p.insert_text((45,390),f"Closing Balance: {balance:,.2f}")
save_pdf(doc,"04_bank.pdf");record("04_bank.pdf","two-page bank statement","clean")
doc,_=invoice(); image(doc).save(out/"05_raster.png");doc.close();record("05_raster.png","clean invoice raster","clean")
doc,v=invoice(); new=v["total"]+rng.randrange(110,450)*10
box=replace(doc[0],f'{v["total"]:,.2f}',f"{new:,.2f}")
save_pdf(doc,"06_total.pdf");record("06_total.pdf","edited total","tampered",old=v["total"],new=new,region=box,space="pdf_points")
for filename,valid in (("07_gst_bad_checksum.pdf",False),("08_gst_needs_registry.pdf",True)):
    doc,v=invoice(); old=v["gstin"]
    new=gst(f"29AABFR{rng.randrange(1000,9999)}P1Z") if valid else old[:-1]+("1" if old[-1]=="0" else "0")
    box=replace(doc[0],old,new)
    save_pdf(doc,filename)
    record(filename,"valid swap needs registry" if valid else "invalid GSTIN checksum","tampered",old=old,new=new,region=box,space="pdf_points",needs_registry=valid)
doc,recipient=invoice();base=image(doc);doc.close()
doc,donor=invoice(); donor_image=image(doc);doc.close()
assert donor["subtotal"]!=recipient["subtotal"]
patch=(830,750,1200,1167)
base.paste(donor_image.crop(patch),patch[:2]);base.save(out/"09_patch.png")
record("09_patch.png","pasted totals conflict with intact item rows","tampered",old=recipient,new=donor,region=patch,space="pixels")
doc,_=invoice(); md=doc.metadata.copy();md.update(producer="Image editor",modDate="D:20251006120000Z");doc.set_metadata(md)
save_pdf(doc,"10_metadata.pdf");record("10_metadata.pdf","metadata timestamp inversion","tampered",old="2025-10-07T12:00Z",new="2025-10-06T12:00Z")
for filename,quality,ink in (("11_splice_clear.jpg",90,20),("12_splice_degraded.jpg",48,150)):
    doc,v=invoice();base=image(doc);doc.close()
    patch=(838,1113,1022,1155)
    crop=Image.new("RGB",(patch[2]-patch[0],patch[3]-patch[1]),"white")
    new=v["total"]+rng.randrange(100,400)*10
    ImageDraw.Draw(crop).text((10,1),f"{new:,.2f}",font=font,fill=(ink,)*3)
    with Image.open(io.BytesIO(jpeg(crop,quality-12))) as low:base.paste(low,patch[:2])
    base.save(out/filename,quality=quality)
    record(filename,"re-saved JPEG splice","tampered",old=v["total"],new=new,region=patch,space="pixels",jpeg_quality=quality,ink_intensity=ink)
assert len(samples)==12 and sum(x["label"]=="clean" for x in samples)==5
(out/"ground_truth.json").write_text(json.dumps(dict(seed=seed,synthetic=True,samples=samples),indent=2),encoding="utf-8")
print("Generated only",seed,len(samples))
