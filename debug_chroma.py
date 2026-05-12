import os
from pathlib import Path
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


_script_dir = Path(__file__).parent.resolve()
CHROMA_PATH       = os.getenv("CHROMA_PATH", str(_script_dir / "chroma_db"))
KB_DEPLOY         = os.getenv("KB_DEPLOY_COLLECTION", "kb_deploy")
KB_CORE           = os.getenv("KB_CORE_COLLECTION", "kb_core")
EMBEDDING_MODEL   = "intfloat/e5-base-v2"
PLATFORMS         = ["ansible", "kubernetes", "terraform"]
TEST_QUERY        = "accountingservice docker image deploy"


print("=" * 60)
print("ChromaDB Metadata Debug Script")
print("=" * 60)


print("\n⏳ Loading embeddings...")
embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


print(f"\n📦 Connecting to: {CHROMA_PATH} / {KB_DEPLOY}")
deploy_db = Chroma(
    collection_name=KB_DEPLOY,
    embedding_function=embeddings,
    persist_directory=CHROMA_PATH,
)


core_db = Chroma(
    collection_name=KB_CORE,
    embedding_function=embeddings,
    persist_directory=CHROMA_PATH,
)


print("\n📊 Chunk counts per platform in kb_deploy:")
print("-" * 40)
for platform in PLATFORMS:
    try:
        results = deploy_db.similarity_search(
            TEST_QUERY, k=100, filter={"platform": platform}
        )
        print(f"  {platform:12s}: {len(results)} chunk(s) found")
    except Exception as e:
        print(f"  {platform:12s}: ERROR — {e}")


print("\n📊 Total chunks in kb_deploy (no filter):")
try:
    all_results = deploy_db.similarity_search(TEST_QUERY, k=200)
    print(f"  Total: {len(all_results)} chunks")
except Exception as e:
    print(f"  ERROR: {e}")


print("\n🔍 Sample metadata from each platform:")
print("-" * 40)
for platform in PLATFORMS:
    try:
        results = deploy_db.similarity_search(
            TEST_QUERY, k=3, filter={"platform": platform}
        )
        print(f"\n  [{platform.upper()}] — {len(results)} sample(s):")
        for i, doc in enumerate(results):
            meta = doc.metadata
            print(f"    [{i+1}] platform={meta.get('platform', 'MISSING!')} "
                  f"| case={meta.get('case', 'N/A')} "
                  f"| source={meta.get('source', 'N/A')[:50]}")
    except Exception as e:
        print(f"  [{platform.upper()}] ERROR: {e}")


print("\n📊 Core KB platform distribution:")
print("-" * 40)
for platform in PLATFORMS + ["abstract"]:
    try:
        results = core_db.similarity_search(
            "EDMM component type", k=50, filter={"platform": platform}
        )
        print(f"  {platform:12s}: {len(results)} rule(s)")
    except Exception as e:
        print(f"  {platform:12s}: ERROR — {e}")


print("\n🔍 First 5 chunks (no filter) — raw metadata:")
print("-" * 40)
try:
    raw = deploy_db.similarity_search(TEST_QUERY, k=5)
    for i, doc in enumerate(raw):
        print(f"  [{i+1}] {doc.metadata}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 60)
print("✅ Debug complete.")
print("=" * 60)
