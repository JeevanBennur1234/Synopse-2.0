from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app.preprocessing.tables import extract_tables

def test_multiline_bank_layout():
    page=dict(page=0,method='native_pdf',text='Date\nNarration\nDebit (INR)\nCredit (INR)\nBalance (INR)\n01/01/2026\nDeposit\n-\n100\n200')
    assert extract_tables([page])[0]['_bank_transactions'][0]['balance']=='200'
    page['text']+='\n02/01/2026\nIncomplete'
    assert '_bank_transactions' not in extract_tables([page])[0]


def test_multipage_bank_layout_carries_forward_without_page2_header():
    from app.detectors.consistency.banking_date import validate_date_and_banking

    p0 = dict(
        page=0,
        method='native_pdf',
        text='Date\nNarration\nDebit (INR)\nCredit (INR)\nBalance (INR)\n01/01/2026\nDeposit\n-\n500\n1500',
    )
    p1_clean = dict(
        page=1,
        method='native_pdf',
        text='ACCOUNT STATEMENT Page 2\n02/01/2026\nRent\n300\n-\n1200\nClosing balance: 1200',
    )
    tables_clean, _ = extract_tables([p0, p1_clean])
    assert len(tables_clean['_bank_transactions']) == 2
    assert tables_clean['_bank_transactions'][1]['page'] == 1
    res_clean = validate_date_and_banking(
        {'opening_balance': ['1000'], 'closing_balance': ['1200'], **tables_clean}
    )
    bal_clean = next(r for r in res_clean if r.name == 'bank_statement_balance_consistency')
    assert bal_clean.status == 'passed'

    p1_tampered = dict(
        page=1,
        method='native_pdf',
        text='ACCOUNT STATEMENT Page 2\n02/01/2026\nRent\n300\n-\n1900\nClosing balance: 1900',
    )
    tables_bad, _ = extract_tables([p0, p1_tampered])
    res_bad = validate_date_and_banking(
        {'opening_balance': ['1000'], 'closing_balance': ['1900'], **tables_bad}
    )
    bal_bad = next(r for r in res_bad if r.name == 'bank_statement_balance_consistency')
    assert bal_bad.status == 'suspicious'

def test_bank_samples():
    c=TestClient(app)
    for folder,name,expected in [('clean','bank_statement_clean_01.pdf',False),('tampered','bank_statement_tampered_balance.pdf',True)]:
        p=Path(__file__).resolve().parents[2]/'dataset'/folder/name
        r=c.post('/analyze',files={'file':(name,p.read_bytes())});r.raise_for_status()
        j=c.get('/result/'+r.json()['job_id']).json()
        f=next(f for f in j['findings'] if f['name']=='bank_statement_balance_consistency')
        assert f['status']==('suspicious' if expected else 'passed')
        assert j['review_required']==expected


def test_exact_stamp_clone():
    from app.detectors.visual.copy_move import CopyMoveDetector
    from PIL import Image, ImageDraw
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"test.png"
        im=Image.new("RGB",(900,700),"white"); draw=ImageDraw.Draw(im)
        draw.ellipse((100,100,240,210),outline="black",width=5)
        draw.line((130,150,200,170),fill="black",width=6)
        im.paste(im.crop((90,90,250,220)),(500,350));im.save(p)
        assert CopyMoveDetector().analyze(p,[p],{})[0].status=="suspicious"
