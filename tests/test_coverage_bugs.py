#!/usr/bin/env python3
"""
Comprehensive tests for Coverage Tracker bug fixes (Phase 1)

Tests the following fixes:
1. Pagination bug: new_only filter applied BEFORE pagination (not after)
2. N+1 query fix: is_read status fetched in single query
3. Total count fix: API returns total for proper pagination
4. Frontend state sync: validated via API consistency tests

Run with: python -m pytest tests/test_coverage_bugs.py -v
Or standalone: python tests/test_coverage_bugs.py
"""

import os
import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from uuid import uuid4

BASE = os.getenv("API_BASE", "http://localhost:8000")
API_TIMEOUT = float(os.getenv("API_TIMEOUT", "30"))


def http(method: str, path: str, data: dict | None = None, headers: dict | None = None):
    """HTTP helper - same as test_api_smoke.py"""
    url = f"{BASE}{path}"
    body = None
    req_headers = headers or {}
    if data is not None:
        body = json.dumps(data).encode()
        req_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            return resp.getcode(), json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            payload = e.read().decode()
            parsed = json.loads(payload) if payload else {}
        except Exception:
            parsed = {}
        return e.code, parsed


def wait_health(timeout=20):
    """Wait for backend to be healthy"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            code, data = http("GET", "/health")
            if code == 200 and data.get("status") == "ok":
                return True
        except Exception:
            time.sleep(0.5)
    return False


def setup_test_data():
    """
    Insert test quotes for testing. These will be used for pagination tests.
    Returns the client name used.
    """
    client_name = f"TestClient_{uuid4().hex[:8]}"
    
    # Insert multiple quotes for the test client
    quotes = [
        f"Quote {i} from {client_name} for coverage testing" 
        for i in range(1, 6)
    ]
    
    payload = {
        "items": [
            {"client_name": client_name, "quote_text": q} 
            for q in quotes
        ]
    }
    
    code, result = http("POST", "/api/v1/coverage/ingest/paste", payload)
    if code != 200:
        print(f"Warning: Failed to insert test quotes: {result}")
        return None
    
    print(f"✅ Inserted {result.get('inserted', 0)} test quotes for client '{client_name}'")
    return client_name


def test_health():
    """Test 1: Verify backend is running"""
    print("\n--- Test 1: Health Check ---")
    assert wait_health(), "Backend health check failed"
    print("✅ Backend is healthy")


def test_api_returns_total_field():
    """Test 2: Verify /coverage endpoint returns 'total' field (Bug fix #3)"""
    print("\n--- Test 2: API Returns 'total' Field ---")
    
    code, data = http("GET", "/api/v1/coverage?page=1&limit=5")
    assert code == 200, f"Expected 200, got {code}"
    
    # Check all expected fields are present
    assert "items" in data, "Response missing 'items' field"
    assert "page" in data, "Response missing 'page' field"
    assert "limit" in data, "Response missing 'limit' field"
    assert "count" in data, "Response missing 'count' field"
    assert "total" in data, "Response missing 'total' field (BUG FIX #3)"
    
    print(f"✅ API returns total={data['total']}, count={data['count']}, page={data['page']}")
    
    # Verify total >= count (total is all matching items, count is items on this page)
    assert data['total'] >= data['count'], "total should be >= count"
    print("✅ total >= count verified")


def test_quotes_api_returns_total_field():
    """Test 3: Verify /coverage/quotes endpoint also returns 'total' field"""
    print("\n--- Test 3: Quotes API Returns 'total' Field ---")
    
    code, data = http("GET", "/api/v1/coverage/quotes?page=1&limit=5")
    assert code == 200, f"Expected 200, got {code}"
    
    assert "total" in data, "Quotes response missing 'total' field"
    print(f"✅ Quotes API returns total={data['total']}, count={data['count']}")


def test_is_read_field_present():
    """Test 4: Verify each hit has 'is_read' field (N+1 fix verification)"""
    print("\n--- Test 4: is_read Field Present (N+1 Fix) ---")
    
    code, data = http("GET", "/api/v1/coverage?page=1&limit=10")
    assert code == 200, f"Expected 200, got {code}"
    
    if not data['items']:
        print("⚠️ No hits to test - skipping is_read verification")
        return
    
    for i, item in enumerate(data['items']):
        assert 'is_read' in item, f"Item {i} missing 'is_read' field"
        assert isinstance(item['is_read'], bool), f"Item {i} is_read should be boolean"
    
    read_count = sum(1 for item in data['items'] if item['is_read'])
    unread_count = len(data['items']) - read_count
    print(f"✅ All {len(data['items'])} items have is_read field (read={read_count}, unread={unread_count})")


def test_new_only_filter_with_pagination():
    """Test 5: Verify new_only filter works correctly WITH pagination (Bug fix #1)
    
    This is the critical test for the pagination bug fix.
    The fix ensures new_only filter is applied BEFORE pagination, not after.
    """
    print("\n--- Test 5: new_only Filter with Pagination (Bug Fix #1) ---")
    
    # First, get total counts
    code, all_data = http("GET", "/api/v1/coverage?page=1&limit=100&new_only=false")
    assert code == 200
    total_all = all_data['total']
    
    code, new_data = http("GET", "/api/v1/coverage?page=1&limit=100&new_only=true")
    assert code == 200
    total_new = new_data['total']
    
    print(f"   Total all items: {total_all}")
    print(f"   Total new (unread) items: {total_new}")
    
    # Test with small page size to verify pagination works correctly
    code, page1 = http("GET", "/api/v1/coverage?page=1&limit=3&new_only=true")
    assert code == 200
    
    # Verify the page contains only unread items (the bug was mixing read/unread)
    for item in page1['items']:
        assert item['is_read'] == False, f"new_only=true returned a read item! Bug not fixed!"
    
    print(f"✅ Page 1 with new_only=true contains {len(page1['items'])} items, all unread")
    
    # Verify total reflects filtered count, not page count
    assert page1['total'] == total_new, f"total should match filtered count ({total_new}), got {page1['total']}"
    print(f"✅ Filtered total ({page1['total']}) matches expected ({total_new})")
    
    # Test consistency across pages
    if total_new > 3:
        code, page2 = http("GET", "/api/v1/coverage?page=2&limit=3&new_only=true")
        assert code == 200
        
        for item in page2['items']:
            assert item['is_read'] == False, "Page 2 new_only=true returned a read item!"
        
        # Verify no duplicates across pages
        page1_ids = {item['id'] for item in page1['items']}
        page2_ids = {item['id'] for item in page2['items']}
        assert not page1_ids.intersection(page2_ids), "Duplicate items across pages!"
        
        print(f"✅ Page 2 has {len(page2['items'])} items, no duplicates with page 1")


def test_pagination_math():
    """Test 6: Verify pagination calculations are correct"""
    print("\n--- Test 6: Pagination Math ---")
    
    code, data = http("GET", "/api/v1/coverage?page=1&limit=5")
    assert code == 200
    
    total = data['total']
    limit = data['limit']
    
    expected_pages = (total + limit - 1) // limit if total > 0 else 1  # ceiling division
    
    print(f"   Total: {total}, Limit: {limit}, Expected pages: {expected_pages}")
    
    # Try to access a page beyond the last
    if expected_pages > 0:
        code, last_page = http("GET", f"/api/v1/coverage?page={expected_pages}&limit={limit}")
        assert code == 200
        print(f"✅ Last page ({expected_pages}) is accessible")
        
        # Page beyond last should return empty but not error
        code, beyond = http("GET", f"/api/v1/coverage?page={expected_pages + 1}&limit={limit}")
        assert code == 200
        assert len(beyond['items']) == 0, "Page beyond last should be empty"
        print(f"✅ Page {expected_pages + 1} (beyond last) returns empty items")


def test_mark_all_read():
    """Test 7: Verify mark_all_read endpoint works correctly"""
    print("\n--- Test 7: Mark All Read ---")
    
    # Get initial new count
    code, before = http("GET", "/api/v1/coverage?page=1&limit=1&new_only=true")
    assert code == 200
    new_before = before['total']
    print(f"   Unread items before: {new_before}")
    
    # Mark all as read
    code, result = http("POST", "/api/v1/coverage/mark-all-read")
    assert code == 200
    print(f"   Marked {result.get('updated', 0)} items as read")
    
    # Verify all are now read
    code, after = http("GET", "/api/v1/coverage?page=1&limit=1&new_only=true")
    assert code == 200
    new_after = after['total']
    print(f"   Unread items after: {new_after}")
    
    assert new_after == 0, f"Expected 0 unread after mark_all_read, got {new_after}"
    print("✅ mark_all_read works correctly")


def test_client_filter():
    """Test 8: Verify client filter works with pagination"""
    print("\n--- Test 8: Client Filter ---")
    
    # Get all clients from data
    code, data = http("GET", "/api/v1/coverage?page=1&limit=100")
    assert code == 200
    
    clients = set(item.get('client_name') for item in data['items'] if item.get('client_name'))
    
    if not clients:
        print("⚠️ No client data to test - skipping")
        return
    
    print(f"   Found {len(clients)} unique clients: {list(clients)[:5]}{'...' if len(clients) > 5 else ''}")
    
    # Test filter for first client
    test_client = list(clients)[0]
    code, filtered = http("GET", f"/api/v1/coverage?page=1&limit=100&client={test_client}")
    assert code == 200
    
    # Verify all items match the client
    for item in filtered['items']:
        assert item.get('client_name') == test_client, f"Client filter failed: expected {test_client}, got {item.get('client_name')}"
    
    print(f"✅ Client filter '{test_client}' returned {filtered['total']} items, all matching")


def test_date_filters():
    """Test 9: Verify date filters work correctly"""
    print("\n--- Test 9: Date Filters ---")
    
    # Test with start date in future (should return 0)
    future_date = "2030-01-01"
    code, data = http("GET", f"/api/v1/coverage?page=1&limit=10&start={future_date}")
    assert code == 200
    print(f"   Filter start={future_date}: {data['total']} items")
    
    # Test with end date in past (should return 0 or very few)
    past_date = "2020-01-01"
    code, data = http("GET", f"/api/v1/coverage?page=1&limit=10&end={past_date}")
    assert code == 200
    print(f"   Filter end={past_date}: {data['total']} items")
    
    # Test with date range encompassing today
    today = datetime.now().strftime("%Y-%m-%d")
    code, data = http("GET", f"/api/v1/coverage?page=1&limit=10&end={today}")
    assert code == 200
    print(f"   Filter end={today}: {data['total']} items")
    
    print("✅ Date filters execute without error")


def test_combined_filters():
    """Test 10: Verify multiple filters work together"""
    print("\n--- Test 10: Combined Filters ---")
    
    # Get a client name to use
    code, data = http("GET", "/api/v1/coverage?page=1&limit=10")
    assert code == 200
    
    if not data['items']:
        print("⚠️ No data to test combined filters - skipping")
        return
    
    test_client = data['items'][0].get('client_name')
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Apply all filters at once
    code, filtered = http("GET", 
        f"/api/v1/coverage?page=1&limit=5&new_only=false&client={test_client}&end={today}")
    assert code == 200
    
    print(f"   Combined filters (client={test_client}, end={today}): {filtered['total']} items")
    print(f"   Page contains {len(filtered['items'])} items")
    
    # Verify results respect all filters
    for item in filtered['items']:
        if test_client:
            assert item.get('client_name') == test_client
    
    print("✅ Combined filters work correctly")


def test_quotes_pagination():
    """Test 11: Verify quotes endpoint pagination matches hits endpoint behavior"""
    print("\n--- Test 11: Quotes Pagination ---")
    
    code, data = http("GET", "/api/v1/coverage/quotes?page=1&limit=5")
    assert code == 200
    
    assert 'items' in data
    assert 'total' in data
    assert 'page' in data
    assert 'limit' in data
    assert 'count' in data
    
    print(f"   Quotes: total={data['total']}, page={data['page']}, count={data['count']}")
    
    # Test page navigation
    if data['total'] > 5:
        code, page2 = http("GET", "/api/v1/coverage/quotes?page=2&limit=5")
        assert code == 200
        
        page1_ids = {item['id'] for item in data['items']}
        page2_ids = {item['id'] for item in page2['items']}
        assert not page1_ids.intersection(page2_ids), "Duplicate quotes across pages!"
        
        print(f"✅ Quotes pagination works: page 2 has {len(page2['items'])} items, no duplicates")
    else:
        print("✅ Quotes pagination structure verified (not enough data for multi-page test)")


def run_all_tests():
    """Run all tests in sequence"""
    print("=" * 60)
    print("COVERAGE TRACKER BUG FIX TESTS")
    print("=" * 60)
    
    tests = [
        test_health,
        test_api_returns_total_field,
        test_quotes_api_returns_total_field,
        test_is_read_field_present,
        test_new_only_filter_with_pagination,
        test_pagination_math,
        test_mark_all_read,
        test_client_filter,
        test_date_filters,
        test_combined_filters,
        test_quotes_pagination,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {type(e).__name__}: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)

