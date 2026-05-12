import os
import shutil
import re
import yaml
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
# Agentic Chunking imports
try:
    from agentic_chunker import (
        IaCAgenticChunker,
        IaCResource,
        SemanticChunk,
        kubernetes_resources_to_iac_resources,
        ansible_to_iac_resources,
        terraform_to_iac_resources
    )
    AGENTIC_CHUNKER_AVAILABLE = True
except ImportError as e:
    AGENTIC_CHUNKER_AVAILABLE = False
    print(f"agentic_chunker import failed: {e}. Falling back to rule-based chunking.", flush=True)

# Configuration
# Force DB to be in the same directory as this script (which is mounted)
script_dir = Path(__file__).parent.resolve()
CHROMA_PATH = os.getenv("CHROMA_PATH", str(script_dir / "chroma_db"))
KB_CORE_COLLECTION = os.getenv("KB_CORE_COLLECTION", "kb_core")
KB_DEPLOY_COLLECTION = os.getenv("KB_DEPLOY_COLLECTION", "kb_deploy")
EMBED_MODEL = "BAAI/bge-large-en-v1.5"
LANGUAGE_MODEL = os.getenv("LANGUAGE_MODEL", "gpt-oss")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11437")
CASE_NAME = os.getenv("CASE_NAME")  # optional fallback

# Agentic Config
USE_AGENTIC_CHUNKING = os.getenv("USE_AGENTIC_CHUNKING", "1") == "1"
AGENTIC_MODEL = os.getenv("AGENTIC_MODEL", "gpt-oss")
MAX_AGENTIC_RESOURCES = int(os.getenv("MAX_AGENTIC_RESOURCES", "20"))  # Skip agentic for large files

# Crude regex approximation - we rely more on the brace counter in split_terraform_blocks
TF_BLOCK_SIMPLE_RE = re.compile(
    r'((?:^|\n)\s*(?:resource|data|module|variable|output|provider|terraform|locals)\s+.*?\s*\{)', 
    re.DOTALL
)

def split_terraform_blocks(text: str) -> List[str]:
    # Python re doesn't support recursive matching easily. 
    # Use a brace counter approach for reliability.
    blocks = []
    lines = text.split('\n')
    current_block = []
    brace_count = 0
    in_block = False
    
    # Keywords that start a top-level block
    keywords = ("resource", "data", "module", "variable", "output", "provider", "terraform", "locals")
    
    for line in lines:
        stripped = line.strip()
        # comment skipping
        if stripped.startswith("#") or stripped.startswith("//"):
            if in_block:
                current_block.append(line)
            continue
            
        # Check for start of block
        if not in_block:
            # Check if line starts with keyword
            is_start = False
            for kw in keywords:
                if stripped.startswith(kw + " ") or stripped == kw:
                    is_start = True
                    break
            
            if is_start and "{" in line:
                in_block = True
                brace_count += line.count("{") - line.count("}")
                current_block.append(line)
                if brace_count == 0:
                    # one-liner block
                    blocks.append("\n".join(current_block))
                    current_block = []
                    in_block = False
            elif is_start:
                # multiliner starting without brace on same line? (rare in canonical TF but possible)
                # treat as start anyway if we see keyword
                in_block = True
                brace_count += line.count("{") - line.count("}")
                current_block.append(line)

        else:
            # Inside block
            current_block.append(line)
            brace_count += line.count("{") - line.count("}")
            
            if brace_count <= 0:
                blocks.append("\n".join(current_block))
                current_block = []
                in_block = False
                brace_count = 0 

    # leftover
    if current_block:
        blocks.append("\n".join(current_block))
        
    if not blocks:
        # fallback: no blocks detected, return whole text
        return [text] if text.strip() else []
        
    return blocks

# ---------- Kubernetes splitting ----------
def looks_like_k8_yaml(text: str) -> bool:
    # crude but effective: kind + apiVersion usually exist
    return ("kind:" in text) and ("apiVersion:" in text)


def split_k8_multi_doc_yaml(text: str) -> List[Tuple[str, Optional[str], Optional[str], Optional[str]]]:
    """
    Return list of tuples: (yaml_text, kind, name, namespace)
    """
    out = []
    docs = list(yaml.safe_load_all(text))
    for obj in docs:
        if not isinstance(obj, dict):
            continue
        kind = obj.get("kind")
        meta = obj.get("metadata") or {}
        name = meta.get("name")
        namespace = meta.get("namespace")
        # dump back to yaml for stable chunk text
        chunk_text = yaml.safe_dump(obj, sort_keys=False)
        out.append((chunk_text, kind, name, namespace))
    # if parsing failed / empty, fallback to raw split by '---'
    if not out:
        raw_parts = [p.strip() for p in re.split(r"^\s*---\s*$", text, flags=re.M) if p.strip()]
        for part in raw_parts:
            out.append((part, None, None, None))
    return out

def split_ansible_playbook(text: str) -> List[str]:
    # simplest: split by "- hosts:" lines (plays)
    parts = re.split(r"(?m)^\s*-\s+hosts\s*:", text)
    if len(parts) <= 1:
        # maybe it is a tasks file? split by "- name:"
        task_parts = re.split(r"(?m)^\s*-\s+name\s*:", text)
        if len(task_parts) > 1:
            out = []
            prefix = task_parts[0].strip()
            if prefix: out.append(prefix)
            for p in task_parts[1:]:
                chunk = "- name:" + p
                if chunk.strip(): out.append(chunk.strip())
            return out
        return [text.strip()] if text.strip() else []
    
    out = []
    # first chunk re-add marker for each part except prefix
    prefix = parts[0].strip()
    if prefix:
        out.append(prefix)
    for p in parts[1:]:
        chunk = "- hosts:" + p
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out


def infer_case_name(path: Path, root: Path) -> str:
    # e.g., Evaluation/OTEL-Shop-Kubernetes/... -> OTEL-Shop-Kubernetes
    # path is absolute. root is absolute.
    # rel = path.relative_to(root)
    # parts[0] is typically the case folder if structure is consistent
    # Attempt to find known patterns
    p_str = str(path).replace("\\", "/")
    if "BoutiqueShop" in p_str: return "BoutiqueShop"
    if "OTEL-Shop-Kubernetes" in p_str: return "OTEL-Shop-Kubernetes"
    if "T2Store-Microservices" in p_str: return "T2Store-Microservices"
    if "T2Store-Modulith" in p_str: return "T2Store-Modulith"
    if "OTEL-Shop-Ansible" in p_str: return "OTEL-Shop-Ansible"
    if "T2Store-Terraform" in p_str: return "T2Store-Terraform"
    if "OTEL-Shop-Terraform" in p_str: return "OTEL-Shop-Terraform"
    if "Meitrex-Microservices" in p_str: return "Meitrex-Microservices"
    if "/Meitrex/" in p_str: return "Meitrex"
    
    # Fallback: parent folder name
    return path.parent.name

def infer_platform_from_path(path: Path) -> str:
    s = str(path).lower()
    if "kubernetes" in s or "k8s" in s or "/k8/" in s:
        return "kubernetes"
    if "ansible" in s:
        return "ansible"
    if "terraform" in s:
        return "terraform"
    return "unknown"


def build_kb_deploy(
    root: Path,
    persist_dir: Path,
    collection_name: str,
    chunk_size: int,
    chunk_overlap: int,
    reset: bool,
    dry_run: bool = False
):
    print(f"[kb_deploy] Scanning {root} ...")
    
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    
    # Init DB
    if not dry_run:
        db = Chroma(
            collection_name=collection_name,
            persist_directory=str(persist_dir),
            embedding_function=embeddings
        )

    # Gather files
    extensions = {".yaml", ".yml", ".tf", ".tfvars", ".hcl", ".json", ".xml", ".properties", ".conf", ".sh"}
    to_index = []
    
    # skip list
    skip_patterns = ["_expected", "expected_", "_actual", "actual_", "deployment_stats.json", "edmm_", "docker-compose", "_output", "generated_", "measurements"]
    
    for ext in extensions:
        for p in root.rglob(f"*{ext}"):
            # Case-insensitive check for skip patterns
            p_lower = p.name.lower()
            if any(s in p_lower for s in skip_patterns):
                print(f"⏭️  Skipping excluded file: {p.name}")
                continue
            
            # Additional check: if 'expected' is anywhere in the path parts (folder names)
            if "expected" in str(p).lower():
                 print(f"⏭️  Skipping file in expected folder: {p}")
                 continue
            to_index.append(p)
            
    print(f"[kb_deploy] selected files: {len(to_index)}")
    
    if reset and not dry_run:
        # Delete collection if exists
        try:
             # Try standardized LangChain-Chroma delete_collection
             # Note: This might raise if collection doesn't exist
             print(f"[kb_deploy] 🗑️  Attempting to delete collection '{collection_name}'...")
             
             # Attempt 1: Direct client access (most reliable for full drop)
             try:
                 db._client.delete_collection(collection_name)
                 print(f"[kb_deploy] ✅ Deleted collection via _client.")
             except Exception as e1:
                 # Attempt 2: LangChain interface
                 try:
                    db.delete_collection()
                    print(f"[kb_deploy] ✅ Deleted collection via db.delete_collection().")
                 except Exception as e2:
                    print(f"[kb_deploy] ⚠️  Soft reset: Could not drop collection ({e1}), deleting all docs instead.")
                    # Attempt 3: Delete all IDs
                    ids = db.get().get("ids", [])
                    if ids:
                        batch_size = 1000
                        for i in range(0, len(ids), batch_size):
                            db.delete(ids=ids[i:i+batch_size])
                        print(f"[kb_deploy] ✅ Deleted {len(ids)} documents from collection.")
                    else:
                        print(f"[kb_deploy] Collection was already empty.")
                        
        except Exception as e:
            print(f"[kb_deploy] ❌ Reset failed: {e}")

        # IMPORTANT: If we deleted the collection (hard delete), we MUST re-initialize the db object
        # so it creates a fresh collection reference.
        try:
            db = Chroma(
                collection_name=collection_name,
                persist_directory=str(persist_dir),
                embedding_function=embeddings
            )
            print(f"[kb_deploy] 🔄 Re-initialized DB connection to '{collection_name}'")
        except Exception as e:
            print(f"[kb_deploy] ❌ Failed to re-initialize DB: {e}")

    if not dry_run:
        # Remove old docs for these files to avoid dupes
        # This is expensive but safe.
        existing_ids = []
        # optimization: verify if we can delete by where={"source": ...}
        for p in to_index:
            try:
                db.delete(where={"source": str(p)})
            except Exception:
                pass

    docs: List[Document] = []
    processed_roles = set()

    for p in to_index:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"⚠️ Failed to read {p}: {e}")
            continue

        case = infer_case_name(p, root)
        platform_guess = infer_platform_from_path(p)
        ext = p.suffix.lower()

        # (Ansible Role-Level Bundling logic removed per user request)

        if ext in (".yaml", ".yml") and looks_like_k8_yaml(text):
            pieces = split_k8_multi_doc_yaml(text)
            
            # AGENTIC CHUNKING (if enabled and available)
            # For large files: batch processing to avoid LLM collapsing everything into 1 group
            if USE_AGENTIC_CHUNKING and AGENTIC_CHUNKER_AVAILABLE and len(pieces) > 0:
                iac_resources_raw = kubernetes_resources_to_iac_resources(pieces)
                WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Pod"}
                workloads = [r for r in iac_resources_raw if r.kind in WORKLOAD_KINDS]
                others = [r for r in iac_resources_raw if r.kind not in WORKLOAD_KINDS]
                iac_resources = workloads + others
                chunker = IaCAgenticChunker(model_name=AGENTIC_MODEL, ollama_host=OLLAMA_HOST)
                
                all_semantic_chunks = []
                # Split into batches so LLM doesn't collapse all into "Default Group"
                for batch_start in range(0, len(iac_resources), MAX_AGENTIC_RESOURCES):
                    batch = iac_resources[batch_start:batch_start + MAX_AGENTIC_RESOURCES]
                    batch_num = batch_start // MAX_AGENTIC_RESOURCES + 1
                    total_batches = (len(iac_resources) + MAX_AGENTIC_RESOURCES - 1) // MAX_AGENTIC_RESOURCES
                    print(f"🤖 Agentic chunking: {p.name} batch {batch_num}/{total_batches} ({len(batch)} resources)", flush=True)
                    try:
                        batch_chunks = chunker.chunk_resources(batch, platform="kubernetes")
                        if batch_chunks:
                            for chunk in batch_chunks:
                                chunk.id = f"b{batch_num}_{chunk.id}"
                            all_semantic_chunks.extend(batch_chunks)
                            print(f"  ✅ Batch {batch_num}: {len(batch_chunks)} semantic chunks", flush=True)
                        else:
                            # Agentic chunker returned 0 (resource name mismatch) → rule-based
                            print(f"  ⚠️  Batch {batch_num}: 0 chunks returned. Rule-based fallback.", flush=True)
                            for j, (chunk_text, kind, name, ns) in enumerate(pieces[batch_start:batch_start+MAX_AGENTIC_RESOURCES], 1):
                                if chunk_text.strip():
                                    docs.append(Document(
                                        page_content=chunk_text,
                                        metadata={"source": str(p), "filename": p.name, "case": case,
                                                  "platform": "kubernetes", "doc_type": "k8s_manifest",
                                                  "kind": kind, "resource_name": name, "namespace": ns,
                                                  "item_id": f"{p.stem}_b{batch_num}_fallback{j}"}
                                    ))
                    except Exception as e:
                        print(f"  ⚠️  Batch {batch_num} agentic chunking failed: {e}. Falling back to rule-based for this batch.", flush=True)
                        for j, res in enumerate(batch, 1):
                            docs.append(Document(
                                page_content=res.content,
                                metadata={
                                    "source": str(p), "filename": p.name, "case": case,
                                    "platform": "kubernetes", "doc_type": "k8s_manifest",
                                    "resource_name": res.name if hasattr(res, 'name') else "",
                                    "item_id": f"{p.stem}_b{batch_num}_res{j}"
                                }
                            ))

                # Save all semantic chunks from all batches
                for chunk in all_semantic_chunks:
                    resource_names = ",".join([r.name for r in chunk.resources if r.name]) if chunk.resources else ""
                    docs.append(Document(
                        page_content=chunk.content,
                        metadata={
                            "source": str(p), "filename": p.name, "case": case,
                            "platform": "kubernetes", "doc_type": "semantic_chunk",
                            "chunk_id": chunk.id, "group_reason": chunk.group_reason,
                            "resource_count": len(chunk.resources),
                            "resource_name": resource_names,
                            "item_id": f"{p.stem}_{chunk.id}",
                        },
                    ))
                print(f"✅ Total: {len(all_semantic_chunks)} semantic chunks from {len(pieces)} resources", flush=True)
            else:
                # Rule based (fallback when agentic chunker not available)
                for i, (chunk_text, kind, name, ns) in enumerate(pieces, 1):
                    if not chunk_text.strip():
                        continue
                    docs.append(
                        Document(
                            page_content=chunk_text, 
                            metadata={
                                "source": str(p), "filename": p.name, "case": case,
                                "platform": "kubernetes", "doc_type": "k8s_manifest",
                                "kind": kind, "resource_name": name, "namespace": ns,
                                "item_id": f"{p.stem}_{kind}_{name}_{i}"
                            }
                        )
                    )

        elif ext in (".tf", ".tfvars", ".hcl"):
            blocks = split_terraform_blocks(text)
            
            # AGENTIC CHUNKING with batch processing
            if USE_AGENTIC_CHUNKING and AGENTIC_CHUNKER_AVAILABLE and len(blocks) > 0:
                iac_resources = terraform_to_iac_resources(blocks)
                chunker = IaCAgenticChunker(model_name=AGENTIC_MODEL, ollama_host=OLLAMA_HOST)
                all_semantic_chunks = []
                for batch_start in range(0, len(iac_resources), MAX_AGENTIC_RESOURCES):
                    batch = iac_resources[batch_start:batch_start + MAX_AGENTIC_RESOURCES]
                    batch_num = batch_start // MAX_AGENTIC_RESOURCES + 1
                    total_batches = (len(iac_resources) + MAX_AGENTIC_RESOURCES - 1) // MAX_AGENTIC_RESOURCES
                    print(f"🤖 Agentic chunking: {p.name} batch {batch_num}/{total_batches} ({len(batch)} blocks)", flush=True)
                    try:
                        batch_chunks = chunker.chunk_resources(batch, platform="terraform")
                        if batch_chunks:
                            for chunk in batch_chunks:
                                chunk.id = f"b{batch_num}_{chunk.id}"
                            all_semantic_chunks.extend(batch_chunks)
                            print(f"  ✅ Batch {batch_num}: {len(batch_chunks)} semantic chunks", flush=True)
                        else:
                            print(f"  ⚠️  Batch {batch_num}: 0 chunks returned. Rule-based fallback.", flush=True)
                            for j, res in enumerate(batch, 1):
                                docs.append(Document(
                                    page_content=res.content,
                                    metadata={"source": str(p), "filename": p.name, "case": case,
                                              "platform": "terraform", "doc_type": "tf_block",
                                              "item_id": f"{p.stem}_b{batch_num}_fallback{j}"}
                                ))
                    except Exception as e:
                        print(f"  ⚠️  Batch {batch_num} failed: {e}. Falling back to rule-based.", flush=True)
                        for j, res in enumerate(batch, 1):
                            docs.append(Document(
                                page_content=res.content,
                                metadata={"source": str(p), "filename": p.name, "case": case,
                                          "platform": "terraform", "doc_type": "tf_block",
                                          "item_id": f"{p.stem}_b{batch_num}_tf{j}"}
                            ))
                for chunk in all_semantic_chunks:
                    resource_names = ",".join([r.name for r in chunk.resources if r.name]) if chunk.resources else ""
                    docs.append(Document(
                        page_content=chunk.content,
                        metadata={"source": str(p), "filename": p.name, "case": case,
                                  "platform": "terraform", "doc_type": "semantic_chunk",
                                  "chunk_id": chunk.id, "group_reason": chunk.group_reason,
                                  "resource_count": len(chunk.resources),
                                  "resource_name": resource_names,
                                  "item_id": f"{p.stem}_{chunk.id}"},
                    ))
                print(f"✅ Total: {len(all_semantic_chunks)} semantic chunks from {len(blocks)} blocks", flush=True)
            else:
                # RULE-BASED CHUNKING (fallback or disabled)
                for i, b in enumerate(blocks, 1):
                    if not b.strip():
                        continue
                    docs.append(Document(
                        page_content=b,
                        metadata={"source": str(p), "filename": p.name, "case": case,
                                  "platform": "terraform", "doc_type": "tf_block",
                                  "item_id": f"{p.stem}_tf_{i}"},
                    ))

        elif ext in (".yaml", ".yml"):
            # treat as potential ansible playbook
            plays = split_ansible_playbook(text)
            
            # AGENTIC CHUNKING with batch processing
            if USE_AGENTIC_CHUNKING and AGENTIC_CHUNKER_AVAILABLE and len(plays) > 0:
                iac_resources = ansible_to_iac_resources(plays)
                chunker = IaCAgenticChunker(model_name=AGENTIC_MODEL, ollama_host=OLLAMA_HOST)
                all_semantic_chunks = []
                for batch_start in range(0, len(iac_resources), MAX_AGENTIC_RESOURCES):
                    batch = iac_resources[batch_start:batch_start + MAX_AGENTIC_RESOURCES]
                    batch_num = batch_start // MAX_AGENTIC_RESOURCES + 1
                    total_batches = (len(iac_resources) + MAX_AGENTIC_RESOURCES - 1) // MAX_AGENTIC_RESOURCES
                    print(f"🤖 Agentic chunking: {p.name} batch {batch_num}/{total_batches} ({len(batch)} plays)", flush=True)
                    try:
                        batch_chunks = chunker.chunk_resources(batch, platform="ansible")
                        if batch_chunks:
                            for chunk in batch_chunks:
                                chunk.id = f"b{batch_num}_{chunk.id}"
                            all_semantic_chunks.extend(batch_chunks)
                            print(f"  ✅ Batch {batch_num}: {len(batch_chunks)} semantic chunks", flush=True)
                        else:
                            print(f"  ⚠️  Batch {batch_num}: 0 chunks returned. Rule-based fallback.", flush=True)
                            for j, res in enumerate(batch, 1):
                                docs.append(Document(
                                    page_content=res.content,
                                    metadata={"source": str(p), "filename": p.name, "case": case,
                                              "platform": "ansible", "doc_type": "ansible_play_or_yaml",
                                              "item_id": f"{p.stem}_b{batch_num}_fallback{j}"}
                                ))
                    except Exception as e:
                        print(f"  ⚠️  Batch {batch_num} failed: {e}. Falling back to rule-based.", flush=True)
                        for j, res in enumerate(batch, 1):
                            docs.append(Document(
                                page_content=res.content,
                                metadata={"source": str(p), "filename": p.name, "case": case,
                                          "platform": "ansible", "doc_type": "ansible_play_or_yaml",
                                          "item_id": f"{p.stem}_b{batch_num}_ans{j}"}
                            ))
                for chunk in all_semantic_chunks:
                    resource_names = ",".join([r.name for r in chunk.resources if r.name]) if chunk.resources else ""
                    docs.append(Document(
                        page_content=chunk.content,
                        metadata={"source": str(p), "filename": p.name, "case": case,
                                  "platform": "ansible", "doc_type": "semantic_chunk",
                                  "chunk_id": chunk.id, "group_reason": chunk.group_reason,
                                  "resource_count": len(chunk.resources),
                                  "resource_name": resource_names,
                                  "item_id": f"{p.stem}_{chunk.id}"},
                    ))
                print(f"✅ Total: {len(all_semantic_chunks)} semantic chunks from {len(plays)} plays", flush=True)
            else:
                # RULE-BASED CHUNKING (fallback or disabled)
                for i, pl in enumerate(plays, 1):
                    if not pl.strip():
                        continue
                    docs.append(Document(
                        page_content=pl,
                        metadata={"source": str(p), "filename": p.name, "case": case,
                                  "platform": "ansible", "doc_type": "ansible_play_or_yaml",
                                  "item_id": f"{p.stem}_ans_{i}"},
                    ))

        else:
            # configs etc.
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "source": str(p),
                        "filename": p.name,
                        "case": case,
                        "platform": platform_guess,
                        "doc_type": "config_file",
                        "item_id": f"{p.stem}_full",
                    }
                )
            )

    print(f"[kb_deploy] docs: {len(docs)}  chunks(after splitter): {len(docs)}")

    if dry_run:
        print("[kb_deploy] dry_run=True -> not indexing.")
        return

    # Add to Chroma
    if docs:
        batch_size = 100
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            db.add_documents(batch)
        print(f"[kb_deploy] ✅ saved: {persist_dir}  collection={collection_name}")
    else:
        print("[kb_deploy] ⚠️ No docs found to index.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Delete old collection first")
    parser.add_argument("--dry_run", action="store_true", help="Print processed docs, do not index")
    args = parser.parse_args()
    
    # 2) Deploy KB (Kubernetes / Terraform / Ansible / code)
    build_kb_deploy(
        root=Path("/app/project_folder/Evaluation"),
        persist_dir=Path(CHROMA_PATH),
        collection_name=KB_DEPLOY_COLLECTION,
        chunk_size=1000,
        chunk_overlap=100,
        reset=args.reset,
        dry_run=args.dry_run
    )