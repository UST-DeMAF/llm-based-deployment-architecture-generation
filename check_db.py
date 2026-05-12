import os
import chromadb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")

client = chromadb.PersistentClient(path=CHROMA_PATH)

print("CHROMA_PATH:", CHROMA_PATH)
print("Collections:", [c.name for c in client.list_collections()])

COLLECTION_NAME = "kb_core"

col = client.get_collection(COLLECTION_NAME)

all_data = col.get(include=["metadatas"])

print(f"Toplam {len(all_data['metadatas'])} kaydin kaynak isimleri:")
for i, metadata in enumerate(all_data['metadatas']):
    print(f"{i+1}. Dosya: {metadata.get('source')} (Platform: {metadata.get('platform')})")