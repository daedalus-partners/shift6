"""
Seed test data for comprehensive pagination testing.

This creates a controlled dataset to verify the bug fixes:
- 50 hits across 2 clients
- Mix of read/unread states
- Various dates for date filtering tests

Run with: python tests/seed_test_data.py
Clean with: python tests/seed_test_data.py --clean
"""
import sys
import uuid
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, "backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, Quote, Hit, HitRead
from backend.app.embedding import embed_texts

# Connect to the database
DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/quotes"
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)

SENTINEL_USER = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Test client names - clearly marked as test data
TEST_CLIENTS = ["__TEST_ClientAlpha__", "__TEST_ClientBeta__"]


def clean_test_data():
    """Remove all test data"""
    session = Session()
    try:
        # Get test quotes
        test_quotes = session.query(Quote).filter(
            Quote.client_name.in_(TEST_CLIENTS)
        ).all()
        
        if test_quotes:
            quote_ids = [q.id for q in test_quotes]
            
            # Get test hits
            test_hits = session.query(Hit).filter(
                Hit.quote_id.in_(quote_ids)
            ).all()
            
            if test_hits:
                hit_ids = [h.id for h in test_hits]
                
                # Delete read records
                deleted_reads = session.query(HitRead).filter(
                    HitRead.hit_id.in_(hit_ids)
                ).delete(synchronize_session=False)
                print(f"Deleted {deleted_reads} read records")
                
                # Delete hits
                session.query(Hit).filter(Hit.id.in_(hit_ids)).delete(synchronize_session=False)
                print(f"Deleted {len(hit_ids)} hits")
            
            # Delete quotes
            session.query(Quote).filter(Quote.id.in_(quote_ids)).delete(synchronize_session=False)
            print(f"Deleted {len(quote_ids)} quotes")
        
        session.commit()
        print("Test data cleaned!")
    finally:
        session.close()


def seed_test_data():
    """Create comprehensive test dataset"""
    session = Session()
    try:
        # First clean any existing test data
        print("Cleaning existing test data...")
        clean_test_data()
        
        print("\nSeeding new test data...")
        now = datetime.utcnow()
        
        # Create test quotes
        quotes = []
        quote_texts = []
        
        for client in TEST_CLIENTS:
            for i in range(5):
                quote = Quote(
                    client_name=client,
                    quote_text=f"Test quote {i+1} for {client}: We are expanding our operations.",
                    state="ACTIVE_HOURLY",
                    added_at=now - timedelta(days=30-i)
                )
                quotes.append(quote)
                quote_texts.append(quote.quote_text)
                session.add(quote)
        
        session.flush()
        print(f"Created {len(quotes)} quotes")
        
        # Generate embeddings for quotes
        try:
            print("Generating quote embeddings...")
            embeddings = embed_texts(quote_texts)
            for quote, emb in zip(quotes, embeddings):
                quote.quote_emb = emb
        except Exception as e:
            print(f"Warning: Could not generate embeddings: {e}")
        
        # Create hits with various states
        hits = []
        hit_index = 0
        
        for quote in quotes:
            # Create 5 hits per quote = 50 total hits
            for j in range(5):
                hit = Hit(
                    quote_id=quote.id,
                    client_name=quote.client_name,
                    url=f"https://test-{uuid.uuid4()}.com/article-{hit_index}",
                    domain=f"test-domain-{j % 3}.com",
                    title=f"[TEST] Article {hit_index}: News about {quote.client_name}",
                    snippet=f"This is a test snippet for article {hit_index}. It contains information about {quote.client_name} and their expansion plans.",
                    match_type=["exact", "partial", "paraphrase"][j % 3],
                    confidence=0.7 + (j * 0.05),
                    published_at=now - timedelta(days=hit_index % 30),
                    created_at=now - timedelta(hours=hit_index),  # Staggered creation times
                )
                hits.append(hit)
                session.add(hit)
                hit_index += 1
        
        session.flush()
        print(f"Created {len(hits)} hits")
        
        # Mark some hits as read (about 40%)
        read_count = 0
        for i, hit in enumerate(hits):
            # Mark every 2-3 hits as read, creating a mix
            if i % 5 < 2:  # 40% read
                hit_read = HitRead(
                    hit_id=hit.id,
                    user_id=SENTINEL_USER,
                    read_at=now - timedelta(hours=i)
                )
                session.add(hit_read)
                read_count += 1
        
        session.commit()
        print(f"Marked {read_count} hits as read ({read_count}/{len(hits)} = {read_count/len(hits)*100:.0f}%)")
        
        print("\n" + "="*60)
        print("TEST DATA SUMMARY")
        print("="*60)
        print(f"Quotes created: {len(quotes)}")
        print(f"  - {TEST_CLIENTS[0]}: 5 quotes")
        print(f"  - {TEST_CLIENTS[1]}: 5 quotes")
        print(f"Hits created: {len(hits)}")
        print(f"  - Read: {read_count}")
        print(f"  - Unread: {len(hits) - read_count}")
        print(f"\nTest clients: {TEST_CLIENTS}")
        print("\nYou can now test pagination:")
        print(f"  - Total hits: 50 (25 per client)")
        print(f"  - With limit=10, you should have 5 pages")
        print(f"  - new_only=true should show ~30 unread hits (3 pages)")
        print("="*60)
        
    finally:
        session.close()


def show_status():
    """Show current test data status"""
    session = Session()
    try:
        quote_count = session.query(Quote).filter(
            Quote.client_name.in_(TEST_CLIENTS)
        ).count()
        
        hit_count = session.query(Hit).filter(
            Hit.client_name.in_(TEST_CLIENTS)
        ).count()
        
        # Count read hits
        read_hits = session.query(Hit, HitRead).join(
            HitRead, Hit.id == HitRead.hit_id
        ).filter(
            Hit.client_name.in_(TEST_CLIENTS),
            HitRead.user_id == SENTINEL_USER
        ).count()
        
        print("\nCurrent test data status:")
        print(f"  Test quotes: {quote_count}")
        print(f"  Test hits: {hit_count}")
        print(f"  Read hits: {read_hits}")
        print(f"  Unread hits: {hit_count - read_hits}")
        
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed or clean test data")
    parser.add_argument("--clean", action="store_true", help="Remove test data")
    parser.add_argument("--status", action="store_true", help="Show test data status")
    args = parser.parse_args()
    
    if args.clean:
        clean_test_data()
    elif args.status:
        show_status()
    else:
        seed_test_data()

