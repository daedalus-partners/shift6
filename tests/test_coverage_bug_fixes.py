"""
Comprehensive tests for Coverage Tracker Bug Fixes (Phase 1)

Tests the following fixes:
1. Pagination bug: new_only filter applied BEFORE pagination
2. N+1 query: single query with LEFT JOIN for read status
3. Total count: API returns filtered count + total for pagination UI
4. Frontend would need manual testing (filter changes trigger reloads)

Run with: pytest tests/test_coverage_bug_fixes.py -v -s
"""
import pytest
import uuid
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# Import the app and models
import sys
sys.path.insert(0, "backend")

from backend.app.main import app
from backend.app.models import Base, Quote, Hit, HitRead
from backend.app.db import get_db

# Test database URL - uses the same DB as development for integration testing
# In production you'd use a separate test DB
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/quotes"

SENTINEL_USER = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def engine():
    """Create test database engine"""
    return create_engine(DATABASE_URL)


@pytest.fixture(scope="module")
def TestSessionLocal(engine):
    """Create session factory"""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session(TestSessionLocal):
    """Create a fresh session for each test"""
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(TestSessionLocal):
    """Create test client with database dependency override"""
    def override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestPaginationBugFix:
    """
    Test: new_only filter should be applied BEFORE pagination
    
    Bug: If we have 25 items (15 read, 10 unread) and request page=1, limit=10 with new_only=true:
    - OLD (buggy): Fetch first 10 items, THEN filter to unread -> might return 0-10 items
    - NEW (fixed): Filter to unread first (10 items), THEN paginate -> returns exactly 10 items
    """
    
    def test_new_only_pagination_returns_full_page(self, db_session, client):
        """
        Create 30 hits: 15 read, 15 unread
        With limit=10 and new_only=true, page 1 should return exactly 10 unread items
        """
        # Setup: Create a test quote
        test_quote = Quote(
            client_name="TestClient_Pagination",
            quote_text="Test quote for pagination",
            state="ACTIVE_HOURLY"
        )
        db_session.add(test_quote)
        db_session.flush()
        
        # Create 30 hits for this quote
        hits = []
        for i in range(30):
            hit = Hit(
                quote_id=test_quote.id,
                client_name="TestClient_Pagination",
                url=f"https://test-pagination-{uuid.uuid4()}.com/article-{i}",
                domain="test-pagination.com",
                title=f"Test Article {i}",
                snippet=f"Test snippet {i}",
                match_type="exact",
                confidence=0.9,
                created_at=datetime.utcnow() - timedelta(hours=30-i)  # Oldest first
            )
            hits.append(hit)
            db_session.add(hit)
        
        db_session.flush()
        
        # Mark first 15 hits as read
        for hit in hits[:15]:
            hit_read = HitRead(
                hit_id=hit.id,
                user_id=uuid.UUID(SENTINEL_USER),
                read_at=datetime.utcnow()
            )
            db_session.add(hit_read)
        
        db_session.commit()
        
        # Test: Request page 1 with new_only=true
        response = client.get("/api/v1/coverage", params={
            "new_only": "true",
            "client": "TestClient_Pagination",
            "page": 1,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Should return exactly 10 items (full page of unread)
        assert data["count"] == 10, f"Expected 10 items on page, got {data['count']}"
        
        # Total should be 15 (all unread items)
        assert data["total"] == 15, f"Expected total of 15 unread, got {data['total']}"
        
        # All items should be unread
        for item in data["items"]:
            assert item["is_read"] == False, "All returned items should be unread"
        
        # Cleanup
        db_session.query(HitRead).filter(HitRead.hit_id.in_([h.id for h in hits])).delete(synchronize_session=False)
        db_session.query(Hit).filter(Hit.client_name == "TestClient_Pagination").delete(synchronize_session=False)
        db_session.query(Quote).filter(Quote.client_name == "TestClient_Pagination").delete(synchronize_session=False)
        db_session.commit()
    
    def test_pagination_page_2_with_new_only(self, db_session, client):
        """
        With 15 unread items and limit=10, page 2 should return 5 items
        """
        # Setup: Create a test quote
        test_quote = Quote(
            client_name="TestClient_Page2",
            quote_text="Test quote for page 2",
            state="ACTIVE_HOURLY"
        )
        db_session.add(test_quote)
        db_session.flush()
        
        # Create 20 hits: 5 read, 15 unread
        hits = []
        for i in range(20):
            hit = Hit(
                quote_id=test_quote.id,
                client_name="TestClient_Page2",
                url=f"https://test-page2-{uuid.uuid4()}.com/article-{i}",
                domain="test-page2.com",
                title=f"Test Article {i}",
                snippet=f"Test snippet {i}",
                match_type="exact",
                confidence=0.9,
                created_at=datetime.utcnow() - timedelta(hours=20-i)
            )
            hits.append(hit)
            db_session.add(hit)
        
        db_session.flush()
        
        # Mark first 5 hits as read
        for hit in hits[:5]:
            hit_read = HitRead(
                hit_id=hit.id,
                user_id=uuid.UUID(SENTINEL_USER),
                read_at=datetime.utcnow()
            )
            db_session.add(hit_read)
        
        db_session.commit()
        
        # Test: Request page 2 with new_only=true
        response = client.get("/api/v1/coverage", params={
            "new_only": "true",
            "client": "TestClient_Page2",
            "page": 2,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Page 2 should have 5 items (15 unread total, 10 on page 1, 5 on page 2)
        assert data["count"] == 5, f"Expected 5 items on page 2, got {data['count']}"
        assert data["total"] == 15, f"Expected total of 15 unread, got {data['total']}"
        assert data["page"] == 2
        
        # Cleanup
        db_session.query(HitRead).filter(HitRead.hit_id.in_([h.id for h in hits])).delete(synchronize_session=False)
        db_session.query(Hit).filter(Hit.client_name == "TestClient_Page2").delete(synchronize_session=False)
        db_session.query(Quote).filter(Quote.client_name == "TestClient_Page2").delete(synchronize_session=False)
        db_session.commit()


class TestN1QueryFix:
    """
    Test: Read status should be fetched in a single query (no N+1)
    
    This is hard to test directly, but we can verify:
    1. Response contains correct is_read status for each item
    2. Mix of read/unread items are correctly labeled
    """
    
    def test_read_status_correctly_populated(self, db_session, client):
        """
        Create hits, mark some as read, verify is_read status is correct
        """
        # Setup
        test_quote = Quote(
            client_name="TestClient_N1",
            quote_text="Test quote for N+1",
            state="ACTIVE_HOURLY"
        )
        db_session.add(test_quote)
        db_session.flush()
        
        # Create 5 hits
        hits = []
        for i in range(5):
            hit = Hit(
                quote_id=test_quote.id,
                client_name="TestClient_N1",
                url=f"https://test-n1-{uuid.uuid4()}.com/article-{i}",
                domain="test-n1.com",
                title=f"Test Article {i}",
                snippet=f"Test snippet {i}",
                match_type="exact",
                confidence=0.9,
                created_at=datetime.utcnow() - timedelta(hours=5-i)
            )
            hits.append(hit)
            db_session.add(hit)
        
        db_session.flush()
        
        # Mark hits 0, 2, 4 as read (odd indices unread)
        read_hit_ids = [hits[0].id, hits[2].id, hits[4].id]
        for hit_id in read_hit_ids:
            hit_read = HitRead(
                hit_id=hit_id,
                user_id=uuid.UUID(SENTINEL_USER),
                read_at=datetime.utcnow()
            )
            db_session.add(hit_read)
        
        db_session.commit()
        
        # Test
        response = client.get("/api/v1/coverage", params={
            "client": "TestClient_N1",
            "page": 1,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Build lookup of is_read by hit id
        id_to_read = {item["id"]: item["is_read"] for item in data["items"]}
        
        # Verify read status
        for i, hit in enumerate(hits):
            expected_read = str(hit.id) in [str(rid) for rid in read_hit_ids]
            actual_read = id_to_read.get(str(hit.id))
            assert actual_read == expected_read, f"Hit {i}: expected is_read={expected_read}, got {actual_read}"
        
        # Cleanup
        db_session.query(HitRead).filter(HitRead.hit_id.in_([h.id for h in hits])).delete(synchronize_session=False)
        db_session.query(Hit).filter(Hit.client_name == "TestClient_N1").delete(synchronize_session=False)
        db_session.query(Quote).filter(Quote.client_name == "TestClient_N1").delete(synchronize_session=False)
        db_session.commit()


class TestTotalCountFix:
    """
    Test: API should return 'total' field with total count of filtered items
    """
    
    def test_total_count_in_response(self, client):
        """Verify response contains 'total' field"""
        response = client.get("/api/v1/coverage", params={"page": 1, "limit": 10})
        assert response.status_code == 200
        data = response.json()
        
        assert "total" in data, "Response should contain 'total' field"
        assert "count" in data, "Response should contain 'count' field"
        assert "page" in data, "Response should contain 'page' field"
        assert "limit" in data, "Response should contain 'limit' field"
    
    def test_total_vs_count_difference(self, db_session, client):
        """
        Total should be total filtered items, count should be items on current page
        """
        # Setup: Create 25 items
        test_quote = Quote(
            client_name="TestClient_Total",
            quote_text="Test quote for total count",
            state="ACTIVE_HOURLY"
        )
        db_session.add(test_quote)
        db_session.flush()
        
        hits = []
        for i in range(25):
            hit = Hit(
                quote_id=test_quote.id,
                client_name="TestClient_Total",
                url=f"https://test-total-{uuid.uuid4()}.com/article-{i}",
                domain="test-total.com",
                title=f"Test Article {i}",
                snippet=f"Test snippet {i}",
                match_type="exact",
                confidence=0.9,
                created_at=datetime.utcnow() - timedelta(hours=25-i)
            )
            hits.append(hit)
            db_session.add(hit)
        
        db_session.commit()
        
        # Test page 1 with limit 10
        response = client.get("/api/v1/coverage", params={
            "client": "TestClient_Total",
            "page": 1,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["count"] == 10, "Page 1 should have 10 items"
        assert data["total"] == 25, "Total should be 25"
        
        # Test page 3 with limit 10 (should have 5 items)
        response = client.get("/api/v1/coverage", params={
            "client": "TestClient_Total",
            "page": 3,
            "limit": 10
        })
        
        data = response.json()
        assert data["count"] == 5, "Page 3 should have 5 items"
        assert data["total"] == 25, "Total should still be 25"
        
        # Cleanup
        db_session.query(Hit).filter(Hit.client_name == "TestClient_Total").delete(synchronize_session=False)
        db_session.query(Quote).filter(Quote.client_name == "TestClient_Total").delete(synchronize_session=False)
        db_session.commit()


class TestQuotesPagination:
    """
    Test: Quotes endpoint should also have correct pagination with total count
    """
    
    def test_quotes_total_count(self, db_session, client):
        """Verify quotes endpoint returns total count"""
        # Setup: Create 15 quotes
        quotes = []
        for i in range(15):
            quote = Quote(
                client_name="TestClient_QuotesPag",
                quote_text=f"Test quote {i} for pagination",
                state="ACTIVE_HOURLY"
            )
            quotes.append(quote)
            db_session.add(quote)
        
        db_session.commit()
        
        # Test
        response = client.get("/api/v1/coverage/quotes", params={
            "client": "TestClient_QuotesPag",
            "page": 1,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert "total" in data, "Quotes response should contain 'total'"
        assert data["count"] == 10, "Page 1 should have 10 quotes"
        assert data["total"] == 15, "Total should be 15 quotes"
        
        # Cleanup
        db_session.query(Quote).filter(Quote.client_name == "TestClient_QuotesPag").delete(synchronize_session=False)
        db_session.commit()


class TestMarkAllRead:
    """
    Test: mark_all_read should efficiently mark all unread hits as read
    """
    
    def test_mark_all_read_updates_unread(self, db_session, client):
        """
        Create mix of read/unread hits, call mark_all_read, verify all become read
        """
        # Setup
        test_quote = Quote(
            client_name="TestClient_MarkAll",
            quote_text="Test quote for mark all read",
            state="ACTIVE_HOURLY"
        )
        db_session.add(test_quote)
        db_session.flush()
        
        hits = []
        for i in range(10):
            hit = Hit(
                quote_id=test_quote.id,
                client_name="TestClient_MarkAll",
                url=f"https://test-markall-{uuid.uuid4()}.com/article-{i}",
                domain="test-markall.com",
                title=f"Test Article {i}",
                snippet=f"Test snippet {i}",
                match_type="exact",
                confidence=0.9,
                created_at=datetime.utcnow() - timedelta(hours=10-i)
            )
            hits.append(hit)
            db_session.add(hit)
        
        db_session.flush()
        
        # Mark first 3 as already read
        for hit in hits[:3]:
            hit_read = HitRead(
                hit_id=hit.id,
                user_id=uuid.UUID(SENTINEL_USER),
                read_at=datetime.utcnow()
            )
            db_session.add(hit_read)
        
        db_session.commit()
        
        # Call mark_all_read
        response = client.post("/api/v1/coverage/mark-all-read")
        assert response.status_code == 200
        data = response.json()
        
        # Should have updated 7 items (10 total - 3 already read)
        assert data["updated"] == 7, f"Expected 7 updated, got {data['updated']}"
        
        # Verify all are now read
        response = client.get("/api/v1/coverage", params={
            "client": "TestClient_MarkAll",
            "new_only": "true",
            "page": 1,
            "limit": 20
        })
        
        data = response.json()
        assert data["total"] == 0, "Should have no unread items after mark_all_read"
        
        # Cleanup
        db_session.query(HitRead).filter(HitRead.hit_id.in_([h.id for h in hits])).delete(synchronize_session=False)
        db_session.query(Hit).filter(Hit.client_name == "TestClient_MarkAll").delete(synchronize_session=False)
        db_session.query(Quote).filter(Quote.client_name == "TestClient_MarkAll").delete(synchronize_session=False)
        db_session.commit()


class TestFilterCombinations:
    """
    Test: Various filter combinations should work correctly
    """
    
    def test_client_filter(self, db_session, client):
        """Test filtering by client name"""
        # Setup: Create quotes and hits for two different clients
        for client_name in ["ClientA", "ClientB"]:
            quote = Quote(
                client_name=client_name,
                quote_text=f"Quote for {client_name}",
                state="ACTIVE_HOURLY"
            )
            db_session.add(quote)
            db_session.flush()
            
            for i in range(5):
                hit = Hit(
                    quote_id=quote.id,
                    client_name=client_name,
                    url=f"https://test-filter-{client_name.lower()}-{uuid.uuid4()}.com/article-{i}",
                    domain=f"test-{client_name.lower()}.com",
                    title=f"{client_name} Article {i}",
                    match_type="exact",
                    created_at=datetime.utcnow()
                )
                db_session.add(hit)
        
        db_session.commit()
        
        # Test: Filter by ClientA
        response = client.get("/api/v1/coverage", params={
            "client": "ClientA",
            "page": 1,
            "limit": 20
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 5, "Should have 5 items for ClientA"
        for item in data["items"]:
            assert item["client_name"] == "ClientA"
        
        # Test: Filter by ClientB
        response = client.get("/api/v1/coverage", params={
            "client": "ClientB",
            "page": 1,
            "limit": 20
        })
        
        data = response.json()
        assert data["total"] == 5, "Should have 5 items for ClientB"
        for item in data["items"]:
            assert item["client_name"] == "ClientB"
        
        # Cleanup
        for client_name in ["ClientA", "ClientB"]:
            db_session.query(Hit).filter(Hit.client_name == client_name).delete(synchronize_session=False)
            db_session.query(Quote).filter(Quote.client_name == client_name).delete(synchronize_session=False)
        db_session.commit()
    
    def test_date_filters(self, db_session, client):
        """Test filtering by date range"""
        # Setup
        test_quote = Quote(
            client_name="TestClient_Date",
            quote_text="Quote for date filter test",
            state="ACTIVE_HOURLY"
        )
        db_session.add(test_quote)
        db_session.flush()
        
        # Create hits across different dates
        now = datetime.utcnow()
        dates = [
            now - timedelta(days=10),  # 10 days ago
            now - timedelta(days=5),   # 5 days ago
            now - timedelta(days=2),   # 2 days ago
            now,                        # today
        ]
        
        hits = []
        for i, dt in enumerate(dates):
            hit = Hit(
                quote_id=test_quote.id,
                client_name="TestClient_Date",
                url=f"https://test-date-{uuid.uuid4()}.com/article-{i}",
                domain="test-date.com",
                title=f"Date Test Article {i}",
                match_type="exact",
                created_at=dt
            )
            hits.append(hit)
            db_session.add(hit)
        
        db_session.commit()
        
        # Test: Filter last 3 days
        start_date = (now - timedelta(days=3)).isoformat()
        response = client.get("/api/v1/coverage", params={
            "client": "TestClient_Date",
            "start": start_date,
            "page": 1,
            "limit": 20
        })
        
        assert response.status_code == 200
        data = response.json()
        
        # Should have 2 items (2 days ago and today)
        assert data["total"] == 2, f"Expected 2 items in last 3 days, got {data['total']}"
        
        # Cleanup
        db_session.query(Hit).filter(Hit.client_name == "TestClient_Date").delete(synchronize_session=False)
        db_session.query(Quote).filter(Quote.client_name == "TestClient_Date").delete(synchronize_session=False)
        db_session.commit()


class TestEdgeCases:
    """
    Test: Edge cases and boundary conditions
    """
    
    def test_empty_results(self, client):
        """Test with non-existent client"""
        response = client.get("/api/v1/coverage", params={
            "client": "NonExistentClient12345",
            "page": 1,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["items"] == []
        assert data["count"] == 0
        assert data["total"] == 0
    
    def test_invalid_page_number(self, client):
        """Test with invalid page numbers (should default to page 1)"""
        response = client.get("/api/v1/coverage", params={
            "page": -1,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1, "Negative page should default to 1"
        
        response = client.get("/api/v1/coverage", params={
            "page": 0,
            "limit": 10
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1, "Page 0 should default to 1"
    
    def test_invalid_limit(self, client):
        """Test with invalid limits"""
        response = client.get("/api/v1/coverage", params={
            "page": 1,
            "limit": 0
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 20, "Zero limit should default to 20"
        
        response = client.get("/api/v1/coverage", params={
            "page": 1,
            "limit": 500
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 20, "Limit > 100 should default to 20"


# Manual test checklist for frontend
FRONTEND_MANUAL_TESTS = """
================================================================================
MANUAL FRONTEND TESTING CHECKLIST
================================================================================

The frontend fixes involve useEffect dependencies and state management.
These require manual testing in the browser.

SETUP:
1. Start the backend: cd backend && uvicorn app.main:app --reload
2. Start the frontend: cd frontend && npm run dev
3. Open http://localhost:5173 (or the Vite dev server URL)

--------------------------------------------------------------------------------
TEST 1: Filter Changes Trigger Reload
--------------------------------------------------------------------------------
Steps:
1. Load the Coverage Tracker (Hits tab)
2. Open browser DevTools > Network tab
3. Toggle "New only" checkbox
   - [ ] Should see a new /api/v1/coverage request
   - [ ] Items should update
4. Change client dropdown (if available)
   - [ ] Should see a new request
5. Change date filters
   - [ ] Should see new requests

Expected: Each filter change triggers an API call

--------------------------------------------------------------------------------
TEST 2: Pagination Info Shows Total Count
--------------------------------------------------------------------------------
Steps:
1. Ensure you have more than 20 items in the database
2. Load page 1 with limit=10 (default or select from dropdown)
3. Check pagination info at bottom

Expected: Shows "Page X of Y • Z total items" format
- Y should be ceil(total/limit)
- Z should match total items across all pages

--------------------------------------------------------------------------------
TEST 3: Pagination Navigation Uses Total Count
--------------------------------------------------------------------------------
Steps:
1. Load the Coverage Tracker
2. Go to the last page using Next button
3. Verify the Next button is disabled on the last page
4. Verify Prev button is disabled on page 1

Expected: Buttons correctly disabled at boundaries

--------------------------------------------------------------------------------
TEST 4: New Only Filter with Pagination
--------------------------------------------------------------------------------
Steps:
1. Mark some items as read by clicking their links
2. Enable "New only" filter
3. Navigate through pages
4. Verify page sizes are consistent

Expected: Each page (except last) should have exactly `limit` items

--------------------------------------------------------------------------------
TEST 5: Filter Change Resets to Page 1
--------------------------------------------------------------------------------
Steps:
1. Navigate to page 2 or 3
2. Toggle "New only" checkbox
3. Verify you're back on page 1
4. Try changing client dropdown
5. Verify page resets to 1

Expected: Any filter change should reset to page 1

--------------------------------------------------------------------------------
TEST 6: Quotes Tab Pagination
--------------------------------------------------------------------------------
Steps:
1. Switch to Quotes tab
2. Verify pagination shows "Page X of Y • Z total items"
3. Navigate pages
4. Change limit dropdown
5. Verify page resets and totals update

Expected: Same pagination behavior as Hits tab

--------------------------------------------------------------------------------
TEST 7: Read Status Updates
--------------------------------------------------------------------------------
Steps:
1. Click on an unread hit (has ! indicator) to open it
2. Return to the app and refresh
3. Verify the hit is now marked as read (no ! indicator)
4. Click "Mark all read"
5. Verify all ! indicators disappear

Expected: Read status correctly tracked and displayed

================================================================================
"""


if __name__ == "__main__":
    print(FRONTEND_MANUAL_TESTS)
    print("\nRunning automated tests...")
    pytest.main([__file__, "-v", "-s"])

