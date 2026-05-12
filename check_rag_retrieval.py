import sys
import os
from pathlib import Path
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag_check")

# Ensure we can import rag
sys.path.append(os.getcwd())

print("--- RAG DIAGNOSTIC START ---")
try:
    import rag
    print(f"✅ Imported rag.py successfully.")
    print(f"🔑 Configured CHROMA_PATH in rag.py: {rag.CHROMA_PATH}")
    
    # Check DB directly
    from langchain_chroma import Chroma
    
    print(f"📊 Checking KB_DEPLOY_COLLECTION: {rag.KB_DEPLOY_COLLECTION}")
    db = rag._get_db(rag.KB_DEPLOY_COLLECTION)
    
    try:
        count = db._collection.count()
        print(f"📈 Total Documents in KB_DEPLOY: {count}")
        
        if count == 0:
            print("❌ ERROR: Database is empty! Ingestion failed or path mismatch.")
        else:
            print("✅ Database has content.")
            
            # Simple metadata check
            print("🔍 Inspecting first 5 documents metadata:")
            res = db._collection.get(limit=5)
            for i, meta in enumerate(res['metadatas']):
                print(f"  [{i}] {meta}")

    except Exception as e:
        print(f"❌ Error accessing collection: {e}")

    # Run Test Query
    print("\n🚀 Running Test Query: 'Convert content_service.tf'")
    query = "Convert content_service.tf to EDMM YAML."
    
    # Try raw search first
    print("\n🔎 Raw Similarity Search (k=3):")
    results = db.similarity_search(query, k=3)
    for i, res in enumerate(results):
        print(f"  [{i}] Source: {res.metadata.get('source')} | Len: {len(res.page_content)}")
        
    if not results:
        print("❌ Raw search returned 0 results.")

except Exception as e:
    print(f"❌ CRITICAL ERROR: {e}")
    import traceback
    traceback.print_exc()

print("--- RAG DIAGNOSTIC END ---")
