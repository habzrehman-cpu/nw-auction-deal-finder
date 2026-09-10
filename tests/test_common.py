from tracker.common import extract_postcode, parse_money, infer_status, is_north_west, opportunity_score

def test_postcode():
    assert extract_postcode('10 Grantham Street, Blackburn BB2 4BZ') == 'BB2 4BZ'

def test_money():
    assert parse_money('Guide Price £55,000') == 55000
    assert parse_money('£2.5M+') == 2500000

def test_status():
    assert infer_status('Lot 3 Sold Prior') == 'Sold Prior'
    assert infer_status('No Bids') == 'No Bids'

def test_geo():
    assert is_north_west('Blackburn, Lancashire BB2 4BZ')
    assert not is_north_west('Brighton BN1 4NH')

def test_score():
    assert opportunity_score({'status':'Available post-auction','property_type':'Commercial','raw_text':'vacant redevelopment','guide_price':100000}) >= 8
