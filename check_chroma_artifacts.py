import os
import argparse
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from pathlib import Path

# Configuration
# Force DB to be in the same directory as this script
script_dir = Path(__file__).parent.resolve()
CHROMA_PATH = os.getenv("CHROMA_PATH", str(script_dir / "chroma_db"))
KB_DEPLOY_COLLECTION = os.getenv("KB_DEPLOY_COLLECTION", "kb_deploy")
EMBED_MODEL = "intfloat/e5-base-v2"

def check_artifacts():
    print(f"🔍 Checking ChromaDB collection: {KB_DEPLOY_COLLECTION}")
    print(f"📂 Persist Dir: {CHROMA_PATH}")

    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    db = Chroma(
        collection_name=KB_DEPLOY_COLLECTION,
        persist_directory=CHROMA_PATH,
        embedding_function=embeddings
    )

    # Get all documents (this might be slow for huge DBs, but okay for debug)
    print("⏳ Fetching all documents...")
    all_docs = db.get()
    
    total_docs = len(all_docs['ids'])
    print(f"📊 Total Documents: {total_docs}")

    if total_docs == 0:
        print("✅ Collection is empty.")
        return

    # Check for artifacts
    bad_patterns = ["_expected", "expected_", "_output", "generated_"]
    bad_count = 0
    
    metadatas = all_docs['metadatas']
    
    print("\n🧐 Scanning for excluded patterns...")
    for i, meta in enumerate(metadatas):
        if not meta: continue
        
        source = meta.get("source", "").lower()
        filename = meta.get("filename", "").lower()
        
        is_bad = False
        reason = ""
        
        for pat in bad_patterns:
            if pat in source or pat in filename:
                is_bad = True
                reason = f"Matches '{pat}'"
                break
        
        if "expected" in source: # Path check
            is_bad = True
            reason = "Path contains 'expected'"

        if is_bad:
            bad_count += 1
            if bad_count <= 10: # Print first 10
                print(f"❌ FOUND BAD ARTIFACT: {source} ({reason})")

    if bad_count > 0:
        print(f"\n⚠️  Found {bad_count} BAD ARTIFACTS out of {total_docs}!")
        print("💡 Recommendation: Run a FULL RESET.")
    else:
        print("\n✅ No bad artifacts found! The collection seems clean.")

if __name__ == "__main__":
    check_artifacts()
