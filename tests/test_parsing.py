from tracker.scrapers import _lot

def test_auctionhouse_line():
    x=_lot('Auction House NW','https://example.com','Lot 4 *Guide | £90,000 (plus fees) 3 Bed Terraced House 20 Charter Avenue, Warrington, Cheshire WA5 0DJ','/lot/4','Live')
    assert x is not None
    assert x.postcode == 'WA5 0DJ'
    assert x.guide_price == 90000
    assert x.area == 'Cheshire'

def test_unsold_line():
    x=_lot('Auction House NW','https://example.com','Lot 30 - AVAILABLE POST AUCTION *Guide | £130,000 2 Bed Detached House 1 Test Road, Bolton, Greater Manchester BL1 1AA','/lot/30','Available post-auction')
    assert x.status == 'Available post-auction'
