import json
from pathlib import Path

from tracker.companies_house import CompaniesHouseClient, build_company_intelligence
from tracker.db import Database
from tracker.intelligence import build_vendor_story, deal_readiness
from tracker.legal import analyse_legal_documents, compare_legal_documents
from tracker.geo import MotorwayNetwork


class FakeCHResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return self._payload


class FakeCHSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
    def get(self, url, params=None, auth=None, timeout=None):
        self.calls.append((url, params, auth))
        if url.endswith('/company/01234567'):
            return FakeCHResponse({
                'company_name': 'NORTH WEST ASSETS LIMITED',
                'company_number': '01234567',
                'company_status': 'administration',
                'type': 'ltd',
                'date_of_creation': '2010-01-02',
                'registered_office_address': {'address_line_1': '1 Market Street', 'locality': 'Manchester', 'postal_code': 'M1 1AA'},
                'accounts': {'overdue': True, 'next_due': '2026-09-30'},
                'confirmation_statement': {'overdue': False},
                'sic_codes': ['68100'],
            })
        if url.endswith('/company/01234567/officers'):
            return FakeCHResponse({'items': [
                {'name': 'DOE, Jane', 'officer_role': 'director', 'appointed_on': '2021-02-03'},
                {'name': 'OLD, Joe', 'officer_role': 'director', 'resigned_on': '2020-01-01'},
            ]})
        if url.endswith('/company/01234567/charges'):
            return FakeCHResponse({'items': [
                {'status': 'outstanding', 'created_on': '2024-01-10', 'persons_entitled': [{'name': 'EXAMPLE BANK PLC'}], 'classification': {'description': 'Legal charge'}},
                {'status': 'fully-satisfied', 'created_on': '2018-01-10', 'satisfied_on': '2022-01-01', 'persons_entitled': [{'name': 'OLD BANK PLC'}]},
            ]})
        if url.endswith('/company/01234567/insolvency'):
            return FakeCHResponse({'cases': [{'type': 'administration', 'number': '1', 'dates': [{'date': '2026-08-01', 'type': 'administration-started-on'}]}]})
        if url.endswith('/company/01234567/persons-with-significant-control'):
            return FakeCHResponse({'items': [{'name': 'JANE DOE', 'kind': 'individual-person-with-significant-control', 'natures_of_control': ['ownership-of-shares-75-to-100-percent']}]})
        if url.endswith('/company/01234567/filing-history'):
            return FakeCHResponse({'items': [{'date': '2026-08-02', 'category': 'insolvency', 'description': 'appointment-of-administrator', 'type': 'AM01'}]})
        if url.endswith('/search/companies'):
            return FakeCHResponse({'items': [{'title': 'NORTH WEST ASSETS LIMITED', 'company_number': '01234567', 'company_status': 'administration', 'address': {'postal_code': 'M1 1AA'}}]})
        return FakeCHResponse({}, 404)


def test_companies_house_bundle_is_privacy_minimised_and_scores_pressure():
    session = FakeCHSession()
    client = CompaniesHouseClient('secret', session=session)
    result = client.fetch_bundle('01234567')
    assert result['company_status'] == 'administration'
    assert result['outstanding_charge_count'] == 1
    assert result['insolvency_case_count'] == 1
    assert result['corporate_pressure_score'] >= 8
    assert result['active_directors'] == [{'name': 'DOE, Jane', 'role': 'director', 'appointed_on': '2021-02-03'}]
    # Basic auth: API key is username and password is blank.
    assert session.calls[0][2] == ('secret', '')
    # No DOB or personal address fields are surfaced by our model.
    assert 'date_of_birth' not in json.dumps(result)


def test_company_resolution_accepts_unique_exact_name():
    client = CompaniesHouseClient('secret', session=FakeCHSession())
    result = client.resolve_company('North West Assets Ltd', '1 Market Street, Manchester M1 1AA')
    assert result['resolved'] is True
    assert result['company_number'] == '01234567'


def test_company_intelligence_roundtrip(tmp_path: Path):
    db = Database(tmp_path / 'tracker.db')
    db.upsert({
        'source': 'Test', 'source_key': 'c1', 'url': 'https://example.test', 'title': 'Property',
        'address': '1 Test St', 'postcode': 'M1 1AA', 'area': 'Manchester', 'property_type': 'Commercial',
        'guide_text': 'GBP 100000', 'guide_price': 100000, 'status': 'Live', 'auction_date': '2026-10-01', 'raw_text': ''
    })
    pid = db.property_for_key('c1')['id']
    summary = build_company_intelligence(
        '01234567',
        {'company_name': 'ABC LTD', 'company_status': 'active', 'registered_office_address': {'postal_code': 'M1 1AA'}},
        {'items': []}, {'items': []}, {}, {'items': []}, {'items': []}
    )
    db.save_company_intelligence(pid, summary)
    saved = db.company_intelligence_for(pid)
    assert saved['company_number'] == '01234567'
    assert saved['company_name'] == 'ABC LTD'
    assert db.company_intelligence_map()[pid]['status'] == 'ok'


def test_vendor_story_uses_official_corporate_pressure_as_fact_not_guess():
    lot = {'status': 'Available post-auction', 'title': 'Commercial property', 'raw_text': '', 'detail_text': ''}
    legal = {'status': 'parsed', 'extracted_fields': {'seller_name': 'ABC LIMITED', 'company_number': '01234567'}}
    company = {
        'status': 'ok', 'company_name': 'ABC LIMITED', 'company_number': '01234567', 'company_status': 'administration',
        'corporate_pressure_score': 9.0, 'corporate_pressure_label': 'Very High', 'outstanding_charge_count': 2,
        'insolvency_case_count': 1, 'accounts_overdue': True, 'company_url': 'https://example.test/company',
        'recent_filings': [{'date': '2026-08-02', 'category': 'insolvency', 'description': 'appointment-of-administrator'}],
        'insolvency_cases': [{'type': 'administration', 'number': '1', 'dates': [{'date': '2026-08-01'}]}],
    }
    story = build_vendor_story(lot, [], {'failure_count': 1, 'features': {}}, legal, [], company)
    assert any('company status is administration' in x.lower() for x in story['confirmed_facts'])
    assert any('corporate records' in x.lower() for x in story['inferences'])
    assert story['buyer_leverage_score'] >= 7
    assert any(x['type'] == 'company' for x in story['timeline'])


def test_legal_pack_change_detection_and_readiness_blocker():
    old = [{'name': 'Special Conditions.pdf', 'url': 'https://x.test/special.pdf', 'sha256': 'aaa', 'doc_type': 'Special conditions'}]
    new = [{'name': 'Special Conditions.pdf', 'url': 'https://x.test/special.pdf', 'sha256': 'bbb', 'doc_type': 'Special conditions'}]
    change = compare_legal_documents(old, new)
    assert change['changed'] is True
    assert change['modified'] == ['Special Conditions.pdf']
    readiness = deal_readiness({
        'status': 'Live', 'detail_enriched': True, 'history_points': 2, 'comparable_confidence': 75,
        'market_value': 200000, 'planning_status': 'ok', 'legal_status': 'parsed', 'legal_pack_changed': True,
        'works_missing': False, 'tenure': 'Freehold', 'latitude': 53.5, 'longitude': -2.2,
    })
    assert readiness['readiness_status'] == 'BID BLOCKED'
    assert any('changed' in x.lower() for x in readiness['readiness_blockers'])


def test_legal_extracts_tenancy_major_works_and_rights():
    docs = [{
        'name': 'Special Conditions.pdf', 'doc_type': 'Special conditions', 'access_status': 'uploaded and parsed', 'sha256': 'x',
        'text_content': '--- PAGE 1 ---\nProperty is tenanted under an Assured Shorthold Tenancy. Current rent GBP 950 per calendar month. Section 20 major works are proposed. Reserve fund applies. Rights of way are reserved. Restrictive covenant applies.'
    }]
    summary = analyse_legal_documents(docs)
    fields = summary['extracted_fields']
    assert fields['tenancy_type'].startswith('Assured Shorthold')
    assert fields['tenancy_rent_amount'] == 950
    assert fields['tenancy_rent_period'] == 'month'
    assert fields['section20_or_major_works_flag'] is True
    assert fields['reserve_fund_flag'] is True
    assert fields['rights_easements_flag'] is True
    assert fields['restrictive_covenant_flag'] is True


def test_motorway_network_uses_stale_cache_when_live_refresh_fails(tmp_path: Path):
    cache = tmp_path / 'junctions.json'
    cache.write_text(json.dumps({
        'updated_at': '2020-01-01T00:00:00+00:00',
        'junctions': [{'osm_id': 1, 'motorway': 'M6', 'junction_ref': '31', 'label': 'M6 J31', 'latitude': 53.7, 'longitude': -2.6}],
    }))
    class BrokenNetwork(MotorwayNetwork):
        def fetch(self):
            raise RuntimeError('all public endpoints unavailable')
    network = BrokenNetwork(cache_path=cache)
    rows = network.load(max_age_days=1)
    assert rows[0]['label'] == 'M6 J31'
    assert network.last_source == 'stale cache'
    assert 'last-known cached network' in network.last_warning
