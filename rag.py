# rag.py - EDMM RAG (Ollama + Chroma + HF embeddings)
# Single-Phase RAG with Hardcoded Perfect Examples
# Two-KB mode:
#   - kb_core  : mapping rules + abstract EDMM definitions + EDMM YAML spec + metamodel
#   - kb_deploy: deployment/IaC artifacts evidence (K8s/Terraform/Ansible)
 
from __future__ import annotations
 
import os
 
# CRITICAL FIX: Disable ChromaDB and OpenTelemetry logging to prevent "Interpreter Shutdown" errors
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["OTEL_PYTHON_DISABLED"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
 
# Strict warning suppression
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
 
import re
import yaml
import time
from pathlib import Path
from typing import List, Optional, Tuple, Any, Dict, Set
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
 
# --- LLM import: prefer new langchain-ollama, fallback to langchain_community ---
try:
    from langchain_ollama import OllamaLLM  # pip install -U langchain-ollama
    _USING_LANGCHAIN_OLLAMA = True
except ImportError:
    from langchain_community.llms import Ollama as OllamaLLM  # fallback
    _USING_LANGCHAIN_OLLAMA = False
 
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
 
 
# =========================
# Global config
# =========================
 
EMBEDDING_MODEL_NAME = "BAAI/bge-large-en-v1.5"
 
# Force DB to be in the same directory as this script
script_dir = Path(__file__).parent.resolve()
CHROMA_PATH = os.getenv("CHROMA_PATH", str(script_dir / "chroma_db"))
 
KB_CORE_COLLECTION = os.getenv("KB_CORE_COLLECTION", "kb_core")
KB_DEPLOY_COLLECTION = os.getenv("KB_DEPLOY_COLLECTION", "kb_deploy")
 
TOP_K_CORE = int(os.getenv("TOP_K_CORE", "10"))
# Increase default deploy chunks to 40 to ensure we get all of main.tf
# even after filtering out 15+ config files in post-retrieval filtering.
TOP_K_DEPLOY = int(os.getenv("TOP_K_DEPLOY", "40"))
DEBUG_RETRIEVAL = os.getenv("DEBUG_RETRIEVAL", "1") == "1"
 
CASE_NAME = os.getenv("CASE_NAME")  # optional
 
LANGUAGE_MODEL = os.getenv("LANGUAGE_MODEL", os.getenv("LANG_MODEL", "gpt-oss:latest"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11437")
 
_embeddings: Optional[HuggingFaceEmbeddings] = None
 
CASE_RE = re.compile(r"\b(OTEL-Shop-[A-Za-z0-9_-]+|T2Store-[A-Za-z0-9_-]+|Meitrex[A-Za-z0-9_-]*)\b")
RES_RE = re.compile(r"\bopentelemetry-demo-[a-z0-9-]+\b")
 

# GLOBAL EXAMPLES — INPUT → OUTPUT format

KUBERNETES_EXAMPLE = """
=== PERFECT EXAMPLE: Kubernetes (Generic Microservices) ===
 
INPUT (Kubernetes YAML):
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: release-name-frontend-webapp
spec:
  template:
    spec:
      containers:
      - name: web
        image: nginx:1.21.0
        ports:
        - containerPort: 80
        env:
        - name: DATABASE_HOST
          value: "release-name-backend-mysql"
---
apiVersion: v1
kind: Service
metadata:
  name: release-name-frontend-webapp
spec:
  ports:
  - port: 80
    targetPort: 80
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: release-name-cartservice
spec:
  template:
    spec:
      containers:
      - name: cartservice
        image: ghcr.io/myorg/demo:1.0.0-cartservice
        ports:
        - containerPort: 7070
          name: grpc
        env:
        - name: VALKEY_ADDR
          value: "release-name-valkey:6379"
        - name: OTEL_SERVICE_NAME
          value: "cartservice"
---
apiVersion: v1
kind: Service
metadata:
  name: release-name-cartservice
spec:
  ports:
  - port: 7070
    targetPort: 7070
    name: grpc
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: release-name-valkey
spec:
  template:
    spec:
      containers:
      - name: valkey
        image: valkey/valkey:7.2-alpine
        ports:
        - containerPort: 6379
          name: valkey
---
apiVersion: v1
kind: Service
metadata:
  name: release-name-valkey
spec:
  ports:
  - port: 6379
    targetPort: 6379
    name: valkey
 
EXPECTED OUTPUT (EDMM YAML):
components:
  - defaultKubernetesCluster:
      type: "DefaultKubernetesCluster"
      properties: []
      operations: []
      artifacts: []
 
  - release-name-frontend-webapp:
      type: "webapp-SoftwareApplication"
      properties:
        - imagePullPolicy: "IfNotPresent"
        - DATABASE_HOST: "release-name-backend-mysql"
        - containerPort_web: 80
        - exposedPort_tcp-web: "80:80"
      operations: []
      artifacts:
        - docker_image:
            name: "nginx:1.21.0"
            fileURI: "https://hub.docker.com/_/nginx"
 
  - release-name-cartservice:
      type: "cartservice-SoftwareApplication"
      properties:
        - imagePullPolicy: "IfNotPresent"
        - VALKEY_ADDR: "release-name-valkey:6379"
        - OTEL_SERVICE_NAME: "cartservice"
        - containerPort_grpc: 7070
        - exposedPort_grpc: "7070:7070"
      operations: []
      artifacts:
        - docker_image:
            name: "ghcr.io/myorg/demo:1.0.0-cartservice"
            fileURI: "https://ghcr.io/myorg/demo"
 
  - release-name-valkey:
      type: "valkey-DatabaseSystem"
      properties:
        - imagePullPolicy: "IfNotPresent"
        - containerPort_valkey: 6379
        - exposedPort_valkey: "6379:6379"
      operations: []
      artifacts:
        - docker_image:
            name: "valkey/valkey:7.2-alpine"
            fileURI: "https://hub.docker.com/r/valkey/valkey"
 
relations:
  - release-name-frontend-webapp_ConnectsTo_release-name-backend-mysql:
      type: "ConnectsTo"
      source: "release-name-frontend-webapp"
      target: "release-name-backend-mysql"
      properties: []
      operations: []
  - release-name-cartservice_ConnectsTo_release-name-valkey:
      type: "ConnectsTo"
      source: "release-name-cartservice"
      target: "release-name-valkey"
      properties: []
      operations: []
  - release-name-frontend-webapp_HostedOn_defaultKubernetesCluster:
      type: "HostedOn"
      source: "release-name-frontend-webapp"
      target: "defaultKubernetesCluster"
      properties: []
      operations: []
  - release-name-cartservice_HostedOn_defaultKubernetesCluster:
      type: "HostedOn"
      source: "release-name-cartservice"
      target: "defaultKubernetesCluster"
      properties: []
      operations: []
  - release-name-valkey_HostedOn_defaultKubernetesCluster:
      type: "HostedOn"
      source: "release-name-valkey"
      target: "defaultKubernetesCluster"
      properties: []
      operations: []
 
KEY PATTERNS (CRITICAL EDMM RULES):
✅ Component NAME = exact metadata.name (e.g. release-name-cartservice). NEVER abbreviate.
✅ Component TYPE derivation priority:
   1. If image tag has hyphenated suffix (demo:1.0.0-cartservice) → extract LAST token → cartservice-SoftwareApplication
   2. If database technology (valkey, redis, mongo, postgres) → <technology>-DatabaseSystem
   3. Otherwise strip common prefixes from name → <clean_name>-SoftwareApplication
✅ Properties MUST be a List of Maps: [ {port: 80} ], NOT a dict: { port: 80 }
✅ Relations MUST follow naming: {source}_{RelationType}_{target}
✅ Valid relation types: HostedOn, ConnectsTo, AttachesTo, DependsOn
✅ ConnectsTo derived from env var values containing other component names
✅ ALL workloads HostedOn defaultKubernetesCluster
✅ Do NOT create components for ConfigMaps, Secrets, ServiceAccounts, Namespaces
"""
 
TERRAFORM_CLUSTER_EXAMPLE = """
=== PERFECT EXAMPLE: Terraform Kubernetes Cluster + K8s YAMLs ===
 
INPUT (Terraform — infra.tf):
resource "azurerm_kubernetes_cluster" "mycluster" {
  name                = "mycluster-aks1"
  location            = "West Europe"
  resource_group_name = "myproject-resources"
  dns_prefix          = "myclusteraks1"
 
  default_node_pool {
    name       = "default_node"
    node_count = 1
    vm_size    = "standard_b4ms"
  }
 
  identity {
    type = "SystemAssigned"
  }
 
  tags = {
    Environment = "Production"
  }
}
 
INPUT (Kubernetes YAML — webapp.yaml):
---
apiVersion: v1
kind: Service
metadata:
  name: webapp
spec:
  ports:
    - port: 80
      targetPort: 8080
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: webapp
spec:
  template:
    spec:
      containers:
        - name: webapp
          image: myorg/webapp:main
          imagePullPolicy: Always
          env:
            - name: DB_HOST
              value: mydb-postgresql
          ports:
            - containerPort: 8080
 
INPUT (Kubernetes YAML — database.yaml):
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mydb-postgresql
spec:
  template:
    spec:
      containers:
        - name: postgresql
          image: bitnami/postgresql:16
          env:
            - name: POSTGRES_USER
              value: admin
            - name: POSTGRES_PASSWORD
              value: secret
          ports:
            - containerPort: 5432
          volumeMounts:
            - name: data-volume
              mountPath: /bitnami/postgresql
  volumeClaimTemplates:
    - metadata:
        name: data-volume
      spec:
        resources:
          requests:
            storage: 8Gi
 
EXPECTED OUTPUT (EDMM YAML):
components:
  - MicrosoftAzure:
      type: "CloudProvider"
      properties: []
      operations: []
      artifacts: []
 
  - mycluster:
      type: "azurerm_kubernetes_cluster"
      properties:
        - name: "mycluster-aks1"
        - location: "West Europe"
        - resource_group_name: "myproject-resources"
        - dns_prefix: "myclusteraks1"
        - default_node_pool.name: "default_node"
        - default_node_pool.node_count: "1"
        - default_node_pool.vm_size: "standard_b4ms"
        - identity.type: "SystemAssigned"
        - tags: "{\\"Environment\\":\\"Production\\"}"
      operations: []
      artifacts: []
 
  - mydb-postgresql-data-volume:
      type: "Storage"
      properties:
        - storage_size: "8Gi"
      operations: []
      artifacts: []
 
  - mydb-postgresql:
      type: "postgresql-DatabaseSystem"
      properties:
        - imagePullPolicy: "IfNotPresent"
        - POSTGRES_USER: "admin"
        - POSTGRES_PASSWORD: "secret"
        - containerPort: 5432
        - exposedPort: "5432:5432"
      operations: []
      artifacts:
        - docker_image:
            name: "bitnami/postgresql:16"
            fileURI: "https://hub.docker.com/r/bitnami/postgresql"
 
  - webapp:
      type: "webapp-SoftwareApplication"
      properties:
        - imagePullPolicy: "Always"
        - DB_HOST: "mydb-postgresql"
        - containerPort: 8080
        - exposedPort: "80:8080"
      operations: []
      artifacts:
        - docker_image:
            name: "myorg/webapp:main"
            fileURI: "https://hub.docker.com/r/myorg/webapp"
 
relations:
  - webapp_ConnectsTo_mydb-postgresql:
      type: "ConnectsTo"
      source: "webapp"
      target: "mydb-postgresql"
      properties: []
      operations: []
  - webapp_HostedOn_mycluster:
      type: "HostedOn"
      source: "webapp"
      target: "mycluster"
      properties: []
      operations: []
  - mydb-postgresql_HostedOn_mycluster:
      type: "HostedOn"
      source: "mydb-postgresql"
      target: "mycluster"
      properties: []
      operations: []
  - mydb-postgresql-data-volume_AttachesTo_mydb-postgresql:
      type: "AttachesTo"
      source: "mydb-postgresql-data-volume"
      target: "mydb-postgresql"
      properties:
        - location: "/bitnami/postgresql"
      operations: []
  - mydb-postgresql-data-volume_HostedOn_mycluster:
      type: "HostedOn"
      source: "mydb-postgresql-data-volume"
      target: "mycluster"
      properties: []
      operations: []
  - mycluster_HostedOn_MicrosoftAzure:
      type: "HostedOn"
      source: "mycluster"
      target: "MicrosoftAzure"
      properties: []
      operations: []
 
KEY PATTERNS:
✅ azurerm_ prefix → create MicrosoftAzure component with type: "CloudProvider"
   (aws_ → AmazonWebServices, google_ → GoogleCloudPlatform)
✅ Cluster name = Terraform resource LABEL (second string): "mycluster"
✅ Cluster type = exact Terraform resource TYPE: azurerm_kubernetes_cluster
✅ All workloads HostedOn the REAL cluster (mycluster), NOT defaultKubernetesCluster!
✅ volumeClaimTemplates → separate Storage component: <statefulset_name>-<volume_name>
   with storage_size property and AttachesTo relation (location = mountPath)
✅ CloudProvider component has NO properties, NO artifacts
✅ Cluster component has NO imagePullPolicy, NO artifacts
✅ mycluster_HostedOn_MicrosoftAzure relation always present
✅ SHELL SCRIPT helm install convention:
   helm install <release> <repo>/<chart> → component name: <release>-<chart>
   EXCEPTION: If release name == chart name, use just <release> (no duplication)
   Examples:
   helm install mongo-cart bitnami/mongodb  → mongo-cart-mongodb  (release ≠ chart)
   helm install mongo-order bitnami/mongodb → mongo-order-mongodb (release ≠ chart)
   helm install kafka bitnami/kafka         → kafka               (release == chart, no dup)
"""
 
ANSIBLE_EXAMPLE = """
=== PERFECT EXAMPLE: Ansible (Generic Worker/Redis) ===

INPUT (Ansible — inventory/hosts.yaml):
all:
  hosts:
    localhost:
      ansible_connection: local

INPUT (Ansible — roles/worker/tasks/main.yaml):
---
- name: Pull worker image
  docker_image:
    name: "mycomp/worker:v2"
    source: pull

- name: Deploy Worker
  docker_container:
    name: "worker-node"
    image: "mycomp/worker:v2"
    env:
      REDIS_URL: "redis-cache:6379"
      WORKER_THREADS: "4"
    restart_policy: "unless-stopped"
    state: "started"

INPUT (Ansible — roles/worker/defaults/main.yaml):
service_name: "worker"
redis_host: "redis-cache:6379"

EXPECTED OUTPUT (EDMM YAML):
components:
  - localhost:
      type: "localhost-type"
      properties:
        - ansible_connection: "local"
      operations:
        - Ensure services are started:
            artifacts:
              - launchd:
                  name: "[worker] started"
                  fileURI: "-"
      artifacts: []

  - worker:
      type: "worker-SoftwareApplication"
      properties:
        - REDIS_URL: "redis-cache:6379"
        - WORKER_THREADS: "4"
      operations:
        - Pull worker image:
            artifacts:
              - docker_image:
                  name: "mycomp/worker:v2"
                  fileURI: "mycomp/worker:v2"
              - bash:
                  name: "/bin/sh docker pull mycomp/worker:v2"
                  fileURI: "-"
        - Deploy Worker:
            artifacts:
              - docker_image:
                  name: "mycomp/worker:v2"
                  fileURI: "mycomp/worker:v2"
              - bash:
                  name: "/bin/sh docker run mycomp/worker:v2"
                  fileURI: "-"
      artifacts:
        - docker_image:
            name: "mycomp/worker:v2"
            fileURI: "mycomp/worker:v2"

relations:
  - worker_connectsTo_redis-cache:
      type: "ConnectsTo"
      source: "worker"
      target: "redis-cache"
      properties: []
      operations: []
  - worker_hostedOn_localhost:
      type: "HostedOn"
      source: "worker"
      target: "localhost"
      properties: []
      operations: []

KEY PATTERNS:
✅ Host component = created from inventory/hosts.yaml (this example: "localhost")
✅ Role component HostedOn the host from the same play — NOT hardcoded
✅ TWO operations per service: "Pull image" + "Deploy Service" (Pull ALWAYS first)
✅ Each operation has TWO artifacts: docker_image AND bash
✅ bash artifact: "/bin/sh docker pull <image>" or "/bin/sh docker run <image>"
✅ bash fileURI = "-" (always a dash)
✅ THERE IS NO KUBERNETES CLUSTER in Ansible! Host = inventory-defined host only.
✅ Every app component HostedOn the host defined in inventory/hosts.yaml.
✅ Do NOT create DockerEngine, defaultKubernetesCluster or MicrosoftAzure.
✅ Do NOT include imagePullPolicy for Ansible components.
"""
 
DOCKER_COMPOSE_EXAMPLE = """
=== PERFECT EXAMPLE: Terraform Docker Compose ===
 
INPUT (Terraform — main.tf):
resource "docker_network" "app-network" {
  name   = "myapp-network"
  driver = "bridge"
}
 
resource "docker_container" "webserver" {
  name     = "nginx"
  image    = "nginx:latest"
  network_mode = "bridge"
  networks_advanced {
    name = docker_network.app-network.name
  }
  restart  = "unless-stopped"
  ports {
    internal = 80
    external = 80
  }
  env = [
    "BACKEND_HOST=api",
    "BACKEND_PORT=8080"
  ]
}
 
resource "docker_container" "cache" {
  name     = "redis"
  image    = "redis:7-alpine"
  network_mode = "bridge"
  networks_advanced {
    name = docker_network.app-network.name
  }
  restart  = "unless-stopped"
  ports {
    internal = 6379
  }
}
 
EXPECTED OUTPUT (EDMM YAML):
components:
  - DefaultDockerEngine:
      type: "DockerEngine"
      properties: []
      operations: []
      artifacts: []
 
  - nginx:
      type: "nginx-SoftwareApplication"
      properties:
        - name: "nginx"
        - network_mode: "bridge"
        - networks_advanced.name: "myapp-network"
        - restart: "unless-stopped"
        - ports.internal: "80"
        - ports.external: "80"
        - BACKEND_HOST: "api"
        - BACKEND_PORT: "8080"
      operations: []
      artifacts:
        - docker_image:
            name: "nginx:latest"
            fileURI: "https://hub.docker.com/_/nginx"
 
  - redis:
      type: "redis-DatabaseSystem"
      properties:
        - name: "redis"
        - network_mode: "bridge"
        - networks_advanced.name: "myapp-network"
        - restart: "unless-stopped"
        - ports.internal: "6379"
      operations: []
      artifacts:
        - docker_image:
            name: "redis:7-alpine"
            fileURI: "https://hub.docker.com/_/redis"
 
relations:
  - nginx_ConnectsTo_redis:
      type: "ConnectsTo"
      source: "nginx"
      target: "redis"
      properties: []
      operations: []
  - nginx_HostedOn_DefaultDockerEngine:
      type: "HostedOn"
      source: "nginx"
      target: "DefaultDockerEngine"
      properties: []
      operations: []
  - redis_HostedOn_DefaultDockerEngine:
      type: "HostedOn"
      source: "redis"
      target: "DefaultDockerEngine"
      properties: []
      operations: []
 
KEY PATTERNS:
✅ Component name = Terraform resource LABEL (second string in resource block).
  CRITICAL: NEVER use the name field value, NEVER use hostname field.
  resource "docker_container" "accountingservice" { name = "accounting-service" }
  → component name: accountingservice  ✅
  → NOT: accounting-service  ❌
  → NOT: accountingservice (from hostname)  ❌
✅ DefaultDockerEngine component always present. NO CloudProvider, NO KubernetesCluster.
✅ All workloads HostedOn DefaultDockerEngine
✅ Do NOT include imagePullPolicy for Docker containers
✅ Extract ALL: env vars, network_mode, networks_advanced.*, hostname, memory, restart, ports.*
"""
 
 

# Helpers

def _infer_case_from_query(q: str) -> Optional[str]:
    m = CASE_RE.search(q or "")
    return m.group(0) if m else None
 
 
def _infer_resource_from_query(q: str) -> Optional[str]:
    m = RES_RE.search(q or "")
    return m.group(0) if m else None
 
 
def _get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL_NAME,
            model_kwargs={"device": device},
            encode_kwargs={"normalize_embeddings": True},
        )
    return _embeddings
 
 
def _get_db(collection_name: str) -> Chroma:
    return Chroma(
        collection_name=collection_name,
        persist_directory=CHROMA_PATH,
        embedding_function=_get_embeddings(),
    )
 
 
def _get_llm(model_name: Optional[str] = None):
    target_model = model_name or LANGUAGE_MODEL
    return OllamaLLM(model=target_model, base_url=OLLAMA_HOST, timeout=120.0, num_ctx=16384)
 
 
def _infer_platform(text: str) -> Optional[str]:
    """
    Fallback: called only when platform=None (e.g. API call without platform param).
    UI now makes platform selection mandatory, so this is a safety net only.
    """
    t = (text or "").lower()
 
    # Ansible: must contain 'ansible' keyword OR Ansible-specific module names
    # NOTE: parentheses required — 'and' binds tighter than 'or' in Python
    if "ansible" in t or "playbook" in t:
        return "ansible"
 
    # Terraform: .tf files or provider/resource blocks
    if ("terraform" in t or ".tf" in t
            or "resource \"aws" in t
            or "resource \"google" in t
            or "resource \"azurerm" in t
            or "provider \"azurerm" in t):
        return "terraform"
 
    # Kubernetes: apiVersion is the most reliable K8s signature
    if "apiversion" in t or "kind: deployment" in t or "kind: service" in t:
        return "kubernetes"
 
    return None
 
 
 
def _dedupe_key(d: Document) -> Tuple[Optional[str], str]:
    md = d.metadata or {}
    return (md.get("source") or md.get("filename"), d.page_content)
 
 
def _detect_tf_subtype(content: str) -> str:
    """
    Generic Terraform sub-type detection based on IaC content, NOT on project/case name.
    Returns:
      'terraform_cluster'    - provisions a managed K8s cluster (AKS/EKS/GKE/etc.)
      'terraform_kubernetes' - deploys TO an existing K8s cluster via kubernetes/helm providers
      'terraform_docker'     - provisions Docker containers
    """
    t = (content or "").lower()
    # Managed Kubernetes cluster provisioning (cloud providers)
    if ("azurerm_kubernetes_cluster" in t
            or "aws_eks_cluster" in t
            or "google_container_cluster" in t
            or "oci_containerengine_cluster" in t
            or "digitalocean_kubernetes_cluster" in t):
        return "terraform_cluster"
    # Kubernetes/Helm provider: deploying TO an existing cluster
    if ("kubernetes_deployment" in t
            or "helm_release" in t
            or "kubernetes_namespace" in t
            or "kubernetes_manifest" in t
            or "kubernetes_service" in t
            or "kubernetes_ingress" in t):
        return "terraform_kubernetes"
    # Docker provider resources (Terraform docker_container)
    if 'resource "docker_container"' in t or "docker_container" in t:
        return "terraform_docker"
    # Default: assume Docker/generic if nothing specific found
    return "terraform_docker"
 
 
def _add_unique(dst: List[Document], seen: Set[Tuple[Optional[str], str]], docs: List[Document]) -> None:
    for d in docs:
        key = _dedupe_key(d)
        if key in seen:
            continue
        seen.add(key)
        dst.append(d)
 
 
def _filter_deploy_by_resource(deploy_docs: List[Document], target_res: Optional[str], platform: str = "") -> List[Document]:
    if not target_res:
        relevant: List[Document] = []
        for d in deploy_docs:
            src = (d.metadata or {}).get("source") or (d.metadata or {}).get("filename") or ""
            src_lower = src.lower()
            if src_lower.endswith(".json"):
                continue
            if "/files/" in src_lower or "\\files\\" in src_lower:
                continue
            if "provisioning" in src_lower and "grafana" not in src_lower:
                continue
            if src_lower.endswith(".ini"):
                continue
            relevant.append(d)

        deduped: List[Document] = []
        seen_fallback: Set[Tuple[Optional[str], str]] = set()
        for d in relevant:
            k = _dedupe_key(d)
            if k not in seen_fallback:
                seen_fallback.add(k)
                deduped.append(d)

        result = deduped
        print(f"  [RESOURCE_FILTER] target_res=None fallback: {len(deploy_docs)} → {len(relevant)} (filtered) → {len(deduped)} (deduped) → {len(result)} (all passed)", flush=True)
        return result

    # --- target_res is set: find matching chunks ---
    filtered: List[Document] = []
    seen: Set[Tuple[Optional[str], str]] = set()

    # 1. Exact metadata match (resource_name)
    for d in deploy_docs:
        md = d.metadata or {}
        if md.get("resource_name") == target_res:
            k = _dedupe_key(d)
            if k not in seen:
                seen.add(k)
                filtered.append(d)

    # 2. ALWAYS also include semantic chunks whose content mentions this resource
    for d in deploy_docs:
        md = d.metadata or {}
        if md.get("doc_type") == "semantic_chunk" and target_res.lower() in d.page_content.lower():
            k = _dedupe_key(d)
            if k not in seen:
                seen.add(k)
                filtered.append(d)

    if filtered:
        exact = [d for d in filtered if (d.metadata or {}).get("resource_name") == target_res]
        semantic = [d for d in filtered if (d.metadata or {}).get("resource_name") != target_res]
        prioritized = exact + semantic
        print(f"  [RESOURCE_FILTER] '{target_res}': {len(filtered)} chunks → {len(exact)} exact + {len(semantic)} semantic", flush=True)
        return prioritized[:5]

    # 3. Content-based fallback (any chunk mentioning the resource)
    name_filtered: List[Document] = []
    seen2: Set[Tuple[Optional[str], str]] = set()
    for d in deploy_docs:
        if target_res.lower() in d.page_content.lower():
            k = _dedupe_key(d)
            if k not in seen2:
                seen2.add(k)
                name_filtered.append(d)
    if name_filtered:
        print(f"  [RESOURCE_FILTER] '{target_res}' content-based fallback: {len(name_filtered)} chunks", flush=True)
        return name_filtered[:5]

    print(f"  [RESOURCE_FILTER] '{target_res}' no match found, returning first 3 chunks", flush=True)
    return deploy_docs[:3]
 
 
def _make_chroma_filter(case_name: Optional[str], platform_final: Optional[str]) -> Optional[Dict[str, Any]]:
    parts = []
    if case_name:
        parts.append({"case": case_name})
    if platform_final:
        parts.append({"platform": platform_final})
 
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}
 
 
def _select_example(platform: Optional[str], tf_subtype: Optional[str] = None) -> str:
    """Select the appropriate hardcoded example based on platform and IaC content signals.
    Returns full INPUT→OUTPUT examples to teach the LLM the mapping process.
    """
    if not platform:
        return KUBERNETES_EXAMPLE + "\n" + ANSIBLE_EXAMPLE + "\n" + DOCKER_COMPOSE_EXAMPLE
 
    p_lower = platform.lower()
 
    if "ansible" in p_lower:
        return ANSIBLE_EXAMPLE
 
    if "terraform" in p_lower:
        if tf_subtype == "terraform_cluster":
            return TERRAFORM_CLUSTER_EXAMPLE
        elif tf_subtype == "terraform_kubernetes":
            return KUBERNETES_EXAMPLE
        else:
            return DOCKER_COMPOSE_EXAMPLE
 
    if "kubernetes" in p_lower or "k8" in p_lower:
        return KUBERNETES_EXAMPLE
 
    return KUBERNETES_EXAMPLE + "\n" + ANSIBLE_EXAMPLE + "\n" + DOCKER_COMPOSE_EXAMPLE
 

# Main

def answer(query: str, case: Optional[str] = None, platform: Optional[str] = None, target_resource: Optional[str] = None, output_format: str = "edmm", model_name: Optional[str] = None) -> str:
    llm = _get_llm(model_name)
    core_db = _get_db(KB_CORE_COLLECTION)
    deploy_db = _get_db(KB_DEPLOY_COLLECTION)
 
    # Resolve request scope (do not override user inputs)
    case_name = case or CASE_NAME or _infer_case_from_query(query)
    target_res = target_resource or _infer_resource_from_query(query)
    platform_final = platform or _infer_platform((query or "") + " " + (case_name or ""))
 
    # ── Platform Normalization ─────────────────────────────────────────────────
    if platform_final and "," in platform_final:
        q_lower = (query or "").lower()
        if "/k8/" in q_lower or "\\k8\\" in q_lower or "/kubernetes/" in q_lower or ".yaml" in q_lower and "apiversion" in q_lower:
            platform_final = "kubernetes"
        elif "/terraform/" in q_lower or "\\terraform\\" in q_lower or ".tf" in q_lower:
            platform_final = "terraform"
        elif "/ansible/" in q_lower or "\\ansible\\" in q_lower or "playbook" in q_lower:
            platform_final = "ansible"
        else:
            parts_p = [p.strip().lower() for p in platform_final.split(",")]
            if any("ansible" in p for p in parts_p):
                platform_final = "ansible"
            elif any("terraform" in p for p in parts_p):
                platform_final = "terraform"
            elif any("kubernetes" in p or "k8" in p for p in parts_p):
                platform_final = "kubernetes"
        print(f"🔀 Platform normalized from '{platform}' → '{platform_final}' (via path detection)", flush=True)
 
    # -------------------------
    # 0) DEBUG: Check DB
    # -------------------------
    if DEBUG_RETRIEVAL:
        print(f"DEBUG: CHROMA_PATH={CHROMA_PATH}")
        try:
            deploy_count = deploy_db._collection.count()
            print(f"DEBUG: deploy_db count={deploy_count}")
        except:
            print("DEBUG: Could not count deploy_db")
 

    # 1) Retrieve from kb_core
   
    core_docs: List[Document] = []
    core_seen: Set[Tuple[Optional[str], str]] = set()
 
    if platform_final:
        k_platform = max(1, TOP_K_CORE // 2)
        k_abstract = max(1, TOP_K_CORE - k_platform)
 
        _add_unique(core_docs, core_seen, core_db.similarity_search(query, k=k_platform, filter={"platform": platform_final}))
        _add_unique(core_docs, core_seen, core_db.similarity_search(query, k=k_abstract, filter={"platform": "abstract"}))
 
        if len(core_docs) < TOP_K_CORE:
            _add_unique(core_docs, core_seen, core_db.similarity_search(query, k=TOP_K_CORE - len(core_docs)))
    else:
        _add_unique(core_docs, core_seen, core_db.similarity_search(query, k=TOP_K_CORE))
 
    # 2) Retrieve from kb_deploy

    deploy_docs: List[Document] = []
    deploy_seen: Set[Tuple[Optional[str], str]] = set()
 
    deploy_filter = _make_chroma_filter(case_name, platform_final)
 
    # --- ADAPTIVE K SELECTION ---
    try:
        if deploy_filter:
            doc_count = len(deploy_db._collection.get(where=deploy_filter, include=[])["ids"])
        else:
            doc_count = deploy_db._collection.count()
            
        top_k_deploy = max(15, min(doc_count + 5, 60))
        if platform_final == "ansible":
            top_k_deploy = min(top_k_deploy, 25)
        print(f"📈 Adaptive K: detected {doc_count} docs for this project. Dynamically set TOP_K_DEPLOY = {top_k_deploy}", flush=True)
    except Exception as e:
        top_k_deploy = TOP_K_DEPLOY
        print(f"⚠️ Adaptive K failed ({e}). Using default {top_k_deploy}", flush=True)
 
    if deploy_filter:
        _add_unique(deploy_docs, deploy_seen, deploy_db.similarity_search(query, k=top_k_deploy, filter=deploy_filter))
        if not deploy_docs and platform_final:
            print(f"DEBUG retrieval: case+platform filter returned 0 docs. Trying platform-only filter.", flush=True)
            _add_unique(deploy_docs, deploy_seen, deploy_db.similarity_search(query, k=top_k_deploy, filter={"platform": platform_final}))
        if not deploy_docs and case_name:
            print(f"DEBUG retrieval: platform-only filter returned 0 docs. Trying case-only filter.", flush=True)
            _add_unique(deploy_docs, deploy_seen, deploy_db.similarity_search(query, k=top_k_deploy, filter={"case": case_name}))
        if not deploy_docs:
            print(f"DEBUG retrieval: case-only filter returned 0 docs. Using no filter (last resort).", flush=True)
            _add_unique(deploy_docs, deploy_seen, deploy_db.similarity_search(query, k=top_k_deploy))
    else:
        _add_unique(deploy_docs, deploy_seen, deploy_db.similarity_search(query, k=top_k_deploy))
 
    deploy_docs = _filter_deploy_by_resource(deploy_docs, target_res, platform=platform_final or "")
 
    # Filter out pure JSON files — keep /files/ and provisioning
    # (they contain ConnectsTo information: Prometheus, Jaeger, OpenSearch)
    clean_deploy_docs = []
    for d in deploy_docs:
        md = d.metadata or {}
        src = md.get("source") or md.get("filename") or ""
        src_lower = src.lower()
        if src_lower.endswith(".json"):
            continue
        # kept — they contain ConnectsTo information (Prometheus, Jaeger, OpenSearch)
        clean_deploy_docs.append(d)
    deploy_docs = clean_deploy_docs
 
   
    # DEBUG
   
    if DEBUG_RETRIEVAL:
        print("\n--- RETRIEVAL (kb_core) ---", flush=True)
        print(f"query={query[:200]!r}", flush=True)
        print(f"case={case_name!r} platform_final={platform_final!r} target_res={target_res!r} TOP_K_CORE={TOP_K_CORE} retrieved={len(core_docs)}", flush=True)
        for i, d in enumerate(core_docs, 1):
            md = d.metadata or {}
            print(f"[{i}] source={md.get('filename') or md.get('source')} doc_type={md.get('doc_type')} platform={md.get('platform')}", flush=True)
            print(d.page_content[:300].replace("\n", " "), flush=True)
            print("", flush=True)
 
        print("\n--- RETRIEVAL (kb_deploy) ---", flush=True)
        print(f"deploy_filter={deploy_filter!r} TOP_K_DEPLOY={TOP_K_DEPLOY} retrieved={len(deploy_docs)} using_langchain_ollama={_USING_LANGCHAIN_OLLAMA}", flush=True)
        for i, d in enumerate(deploy_docs, 1):
            md = d.metadata or {}
            print(f"[{i}] source={md.get('filename') or md.get('source')} case={md.get('case')} platform={md.get('platform')} kind={md.get('kind')} resource_name={md.get('resource_name')} namespace={md.get('namespace')}", flush=True)
            print(d.page_content[:300].replace("\n", " "), flush=True)
            print("", flush=True)
 
  
    # 3) Fact Extraction
    
    from fact_extractor import FactExtractor
    extractor = FactExtractor()

    # Determine correct file extension based on Platform
    if platform_final and "terraform" in platform_final.lower():
        _fe_filename = "main.tf"
    elif platform_final and "ansible" in platform_final.lower():
        _fe_filename = "ansible_playbook.yaml"
    else:
        _fe_filename = "manifest.yaml"  # K8s default

    corpus_text = query
    if deploy_docs:
        clean_parts = []
        for d in deploy_docs:
            text = d.page_content
            # Strip semantic chunk headers so YAML parser can read the content
            if text.startswith("[SEMANTIC CHUNK]") or text.startswith("[DEPLOY]") or text.startswith("[CORE]"):
                # Keep only lines that look like YAML (start with spaces, letters, or -)
                lines = text.splitlines()
                yaml_lines = []
                in_yaml = False
                for line in lines:
                    if line.startswith("apiVersion:") or line.startswith("kind:") or line.startswith("metadata:"):
                        in_yaml = True
                    if in_yaml:
                        yaml_lines.append(line)
                text = "\n".join(yaml_lines) if yaml_lines else text
            clean_parts.append(text)
        corpus_text = "\n\n".join(clean_parts)

    extracted_facts = extractor.extract(_fe_filename, content=corpus_text)

    facts_text = ""
    if extracted_facts:
        facts_text = "\n[VERIFIED INFRASTRUCTURE FACTS]:\n"
        facts_text += "Use component names EXACTLY as given.\n"
        for f in extracted_facts:
            facts_text += (
                f"- Component: {f.name} | Type: {f.source_type} | Image: {f.image} "
                f"| Ports: {f.ports} | Envs: {f.envs}"
            )
            facts_text += "\n"

    # 4) Build context docs

    context_docs: List[Document] = []
    context_docs.extend([Document(page_content=f"[CORE] {d.page_content}", metadata=d.metadata) for d in core_docs])
    
    MAX_DEPLOY_CHARS = 8000
    for d in deploy_docs:
        content = d.page_content
        if len(content) > MAX_DEPLOY_CHARS:
            content = content[:MAX_DEPLOY_CHARS] + "\n... (TRUNCATED due to length)"
        
        md = d.metadata or {}
        src = md.get("source") or md.get("filename") or "Unknown"
        if md.get("doc_type") == "semantic_chunk":
            header = f"[SEMANTIC CHUNK] Source: {src} | Group: {md.get('group_reason', 'Unknown')} | Resources: {md.get('resource_count')}"
            context_docs.append(Document(page_content=f"{header}\n{content}", metadata=d.metadata))
        else:
            context_docs.append(Document(page_content=f"[DEPLOY] Source: {src}\n{content}", metadata=d.metadata))
 
  
    # 5) Select Hardcoded Example

    tf_subtype: Optional[str] = None
    if platform_final and "terraform" in platform_final.lower():
        tf_corpus = (query or "") + "\n" + "\n".join(d.page_content for d in deploy_docs[:20])
        tf_subtype = _detect_tf_subtype(tf_corpus)
        print(f"\n🔍 Terraform sub-type detected from content: {tf_subtype}", flush=True)
 
    selected_example = _select_example(platform_final, tf_subtype)
    print(f"\n📚 Using hardcoded example for platform={platform_final} tf_subtype={tf_subtype}", flush=True)
 
  
    # 6) Prompt Construction

    
    platform_rules = ""
    platforms_for_rules = ((platform_final or "") + "," + (platform or "")).lower()
    p_lower = platforms_for_rules
    if "kubernetes" in p_lower or "k8" in p_lower:
        platform_rules += """
[KUBERNETES SPECIFIC]
- Always create `defaultKubernetesCluster` component with type `DefaultKubernetesCluster` (note capital D, K, C).
- In Phase 2, every component must receive a `HostedOn` relation to `defaultKubernetesCluster`.
- **CRITICAL**: Convert Service ports into normalized `exposedPort_<name-or-number>` properties. If a port name exists, use it. Otherwise use the service port number. Format the value as "externalPort:containerPort".
- **TYPE CLASSIFICATION**: Follow the global type rules defined in [CRITICAL RULES] Rule 4. NEVER use the full `metadata.name` verbatim as the type base if it contains a deployment/release prefix.
- Use `containerPort_<name>` when a port or container name is available in the workload pod templates; otherwise use `containerPort_<number>`.
- Include `imagePullPolicy` as a component property. If not 
  explicitly specified in the source file, use the default 
  value `IfNotPresent`.
- **CRITICAL**: For StatefulSets with volumeClaimTemplates, create a SEPARATE Storage component for each volume claim. Name: <statefulset_name>-<volume_claim_name>. Type: "Storage". Property: storage_size from resources.requests.storage. Also create an AttachesTo relation with location = volumeMount.mountPath.

PVC NAMING RULE:
Component name for PersistentVolumeClaim = <statefulset_name>-<volumeClaimTemplate_name>-volume
Example: StatefulSet "postgres", volumeClaimTemplate name "postgres-storage" 
→ component name: postgres-postgres-storage-volume

TYPE DERIVATION RULE:
Component type MUST be derived from the container image name, NOT the deployment/pod name.
Take the last path segment of the image (before the colon/tag).
Example: image=t2project/modulith:main → type: modulith-SoftwareApplication  
Example: image=ghcr.io/open-telemetry/demo:1.11.1-cartservice → type: cartservice-SoftwareApplication
Example: image=postgres:12.16 → type: postgres-DatabaseSystem

SHELL SCRIPT RULE:
If input contains shell script with helm install commands:
  helm install <release-name> <repo>/<chart>
  → create component: <release-name>-<chart-name>
  → type: derived from chart name using Rule 4
  EXCEPTION: If release name == chart name, use just <release> (no duplication)
  Examples:
  helm install mongo bitnami/mongodb   → mongo-mongodb   (release ≠ chart) ✅
  helm install mongo-cart bitnami/mongodb → mongo-cart-mongodb (release ≠ chart) ✅
  helm install kafka bitnami/kafka     → kafka           (release == chart, no dup) ✅
DAPR SIDECAR INJECTION RULE:
If any workload has the annotation dapr.io/enabled: "true" in its 
metadata.annotations, this workload uses Dapr sidecar injection.
In this case:
- Create a component named "dapr-sidecar-injector" with type 
  "dapr-SoftwareApplication" if not already present.
- Create a ConnectsTo relation FROM "dapr-sidecar-injector" TO 
  that workload.
- This applies to EVERY workload with dapr.io/enabled: "true".
Example:
  annotations:
    dapr.io/enabled: "true"
→ dapr-sidecar-injector_ConnectsTo_<workload-name>
"""
    if "terraform" in p_lower:
        if tf_subtype == "terraform_cluster":
            platform_rules += """
[TERRAFORM SPECIFIC — CLUSTER INFRASTRUCTURE]

# Component Creation
- Only create components for: the managed cluster resource, CloudProvider,
  deployable components (kubernetes_deployment, helm_release), Storage volumes.
- **TYPE CLASSIFICATION**: Follow the global type rules defined in [CRITICAL RULES] Rule 4.

SHELL SCRIPT RULE:
If deployment script (*.sh) contains helm install commands,
create components for each helm release:
  helm install <release> <repo>/<chart> → component: <release>-<chart>
  EXCEPTION: If release name == chart name, use just <release>
  Examples:
  helm install mongo-cart bitnami/mongodb  → mongo-cart-mongodb
  helm install kafka bitnami/kafka         → kafka

# Cloud Provider
- Identify from resource prefix:
    azurerm_ → create `MicrosoftAzure` (type: CloudProvider)
    aws_     → create `AmazonWebServices` (type: CloudProvider)
    google_  → create `GoogleCloudPlatform` (type: CloudProvider)
- CloudProvider has NO properties, NO artifacts.
- Cluster MUST have HostedOn relation to CloudProvider.

# Hosting (CRITICAL)
- Do NOT create defaultKubernetesCluster — a real cluster is explicitly defined.
- Every workload and Storage MUST have HostedOn relation to the REAL cluster.
- Storage volumes → separate component (type: Storage), storage_size property,
  AttachesTo relation with location = mountPath.

# Dependencies
- depends_on meta-argument → create DependsOn relation for each entry;
  refine to ConnectsTo/AttachesTo/HostedOn if context allows.

# Configuration Files
- Configuration files (ConfigMaps, variable files, application.properties) are NEVER 
  part of the network topology. Do NOT create components for them, and do 
  NOT create ConnectsTo relations simply because a config file references a host.
  ONLY create ConnectsTo for explicit runtime network communication.
"""
        elif tf_subtype == "terraform_kubernetes":
            platform_rules += """
[TERRAFORM SPECIFIC — KUBERNETES / HELM PROVIDER]

# Component Creation
- Follow the same component rules as Kubernetes platform.
- For helm_release: if K8s manifests are available use 
  metadata.name as component name; otherwise use chart name.
  Type derived per Rule 4.
  Example: bitnami/mongodb → name: mongodb, type: mongo-DatabaseSystem
- There is NO CloudProvider component.
- Skip: kubernetes_namespace, kubernetes_secret, random_password,
  service_account, data sources, variables.

# Hosting (CRITICAL)
- If a real Kubernetes cluster is already defined in the deployment 
  model (e.g. azurerm_kubernetes_cluster), every component MUST have 
  HostedOn relation to THAT cluster — do NOT create defaultKubernetesCluster.
- Only create defaultKubernetesCluster (type: DefaultKubernetesCluster) 
  if no real cluster resource exists in the deployment model.
- Every component and Storage MUST have HostedOn relation to the cluster.
"""
        else:  # terraform_docker
            platform_rules += """
[TERRAFORM SPECIFIC — DOCKER PROVIDER]

# Component Creation
- Create DefaultDockerEngine component (type: DockerEngine). NO CloudProvider. NO KubernetesCluster.
- Each docker_container resource becomes a component.
- Extract ALL properties: env variables (split BACKEND=value format),
  network_mode, networks_advanced.*, hostname, memory, restart, depends_on,
  volumes.*, healthcheck.*, command, user.
- Ports: internal port → ports.internal, external → ports.external.
- Do NOT include imagePullPolicy — Docker containers do not use this field.
- **TYPE CLASSIFICATION**: Follow the global type rules defined in [CRITICAL RULES] Rule 4.
  Do NOT use DockerContainer as type. Derive semantic type from image tag.
  Example: image "demo:1.11.1-accountingservice" → type: accountingservice-SoftwareApplication
  Example: image "valkey/valkey:8.0-alpine" → type: valkey-DatabaseSystem
  Example: image "kafka:latest" → type: kafka-MessageBroker

# FORBIDDEN Resources (do NOT create components):
- docker_network → NOT a component, skip entirely
- random_password, random_string, random_id → NOT components
- null_resource, local_file, template_file → NOT components
- variable blocks → NOT components
- data sources → NOT components

# Dependencies
- depends_on → create DependsOn relation; refine to ConnectsTo/AttachesTo/HostedOn if context allows.

# Hosting (CRITICAL)
- Every component MUST have HostedOn relation to DefaultDockerEngine.

# Configuration Files
- Configuration files (variable files, env files) are NEVER part of the network 
  topology. Do NOT create components for them, and do NOT create ConnectsTo 
  relations simply because a config file references a host.
  ONLY create ConnectsTo for explicit runtime network communication.
"""
    if "ansible" in p_lower:
        platform_rules += """
[ANSIBLE SPECIFIC]
- **Host Component**: Create a component for each host defined in 
  the inventory/hosts.yaml file. Use the host name and ALL 
  configuration properties from file. Do NOT assume localhost.

- **Role Components**: Each Ansible role becomes a component. 
  Component name = role name.

- **HostedOn**: Every role component MUST have a HostedOn relation 
  to the host component defined in inventory/hosts.yaml for that play.
  Use the EXACT host name from inventory.

- **Operations**: Each task in tasks/main.yaml → one operation.
  For docker_image and docker_container tasks specifically:
  - Pull operation MUST come BEFORE deploy operation
  - Each operation MUST have TWO artifacts: docker_image AND bash

- **Jinja2**: Resolve all {{ variable_name }} from defaults/main.yaml 
  or vars/main.yaml. NEVER output unresolved template strings.

- **Properties**: application-level env vars ONLY. Do NOT include: 
  image, imagePullPolicy, log_driver, log_options_*, 
  network_mode, restart, container_name, volumes, deploy.

- **Role Dependencies**: Dependencies defined in meta directory become 
  ConnectsTo relations between role components.

- **ARTIFACT RULES**: Each component MUST have a top-level artifacts 
  list containing the primary docker_image artifact with its fileURI.

- Do NOT include imagePullPolicy — Ansible does not use this field.
- Do NOT create components not defined in source files or platform rules.
"""
 
    base_prompt_phase1 = f"""You are a specialized EDMM Compiler. Your task is to extract components and their properties from infrastructure code into EDMM YAML format.
 
{selected_example}
 
[CRITICAL RULES]
1. **Output ONLY VALID YAML** - no conversational text, no markdown fences
2. **Extract ALL deployment-relevant details** — nothing may be omitted.

   For ALL platforms:
   - Container/service images → artifacts (full image:tag)
   - All ports (internal and external) → properties

   For Kubernetes:
   - All env vars → properties (+ ConnectsTo if reference to other component)
   - imagePullPolicy → property
   - Volume mounts → AttachesTo relation

   For Terraform:
   - All resource arguments → properties, nested blocks flattened with 
     dot notation (e.g. default_node_pool.name) — applies to ALL 
     Terraform subtypes
   - Variable references → resolved to concrete values

   For Ansible:
   - All role variables → properties
   - Each task → operation with artifacts
   - Referenced files → artifacts
3. **COMPONENT NAME (EXACT SOURCE NAME)**: Use the exact, full 
   name as it appears in the source file. Nothing may be 
   abbreviated or shortened.
   - Kubernetes: metadata.name field value
   - Terraform: Terraform resource LABEL (second string in 
     resource block) — applies to ALL Terraform subtypes
     Example: resource "docker_container" "accountingservice" 
     → component name: accountingservice
   - Ansible: role name from the roles/ directory
4. **COMPONENT TYPE (LOGICAL/SEMANTIC TYPE)**: The type field 
   represents the architectural role of the component, not its 
   exact resource name. This applies to ALL components — 
   infrastructure component types are defined in the 
   platform-specific rules below. For type derivation, 
   apply these rules in order:

   a. If it is a persistent data store or database — recognized by
      technology keywords in name or image (mongo, redis, valkey, 
      postgres, postgresql, mysql, mariadb, cassandra, elasticsearch,
      opensearch, influxdb, neo4j, couchdb, clickhouse, etc.)
      → use <technology>-DatabaseSystem

   b. If it is a message broker or event streaming platform — 
      recognized by technology keywords in name or image (kafka, 
      rabbitmq, nats, pulsar, activemq, artemis, redpanda, emqx, 
      mosquitto)
      → use <technology>-MessageBroker

   c. If the image tag contains a hyphenated suffix, extract the 
      LAST token as the type base.
      Example: myapp:2.0.0-paymentservice → paymentservice-SoftwareApplication

   d. [Kubernetes only] If Kubernetes labels are present, use 
      app.kubernetes.io/name for type derivation. This label 
      contains the semantic service name, avoiding generic 
      deployment name prefixes.

   e. Otherwise, strip any generic helm/release prefixes from 
      the full name and use: <clean_name>-SoftwareApplication
5. **ALLOWED COMPONENTS**: Create EDMM components ONLY for 
   objects that represent a deployable unit — i.e., objects 
   that have an Artifact (image, file, archive) that implements 
   them and is required for their execution.

   IGNORE — do NOT create components for objects that only 
   support or configure other components:
   - Kubernetes: Services, ConfigMaps, Secrets, ClusterRoles,
     ServiceAccounts, Namespaces, HorizontalPodAutoscalers, Tests
   - Terraform: namespace, secret, service account resources,
     docker_network, random_password, null_resource, 
     data sources, variable blocks
   - Ansible: Tasks and Handlers → these become Operations 
     on their role component, NOT separate components
6. **Do NOT invent numbered variants** (e.g., accountdb1, accountdb2, ...)
7. **Properties format**: List of single-key maps (e.g., `- port: 8080`). 
8. **MANDATORY ARTIFACTS**: An artifact implements a component 
   and is required for its execution. Every component with a 
   deployment image MUST declare it as an artifact:
     artifacts:
       - docker_image:
           name: <full image:tag>
           fileURI: <registry URL>
   Components that do NOT require artifacts:
   - ContainerPlatform and its subtypes (KubernetesCluster, 
     DockerEngine, DefaultKubernetesCluster, DefaultDockerEngine)
   - CloudProvider
   - Storage
   - Ansible host components (localhost, etc.)
9. **IGNORE RELATIONS**: Do NOT output a `relations` list. We will do that in the next phase.
 
{platform_rules}
 
[SEMANTIC CHUNKING HINTS]
The input context contains "Semantic Chunks" which group related 
Kubernetes resources together (e.g. a Deployment + its Service + 
its ConfigMap or Secret).
- Use these groups to identify the FULL properties of a component.
- If a chunk groups a Deployment with a ConfigMap or Secret, merge 
  their configuration values into the single component's properties.
  Do NOT create separate components for ConfigMap or Secret.
- Pay attention to the "Reason" field in the context to understand 
  why resources are grouped.
 
[OUTPUT FORMAT]
**CRITICAL**: Start your output with `---` (YAML document marker).
 
---
component_types:
  - <type-name>:
      extends: <base-type>
 
components:
  - <component-name>:
      type: <type>
      properties:
        - <key>: <value>
      artifacts:
        - docker_image:
            fileURI: <image>
 
END your output with `[OUTPUT END]` on a new line.
"""
 
    prompt_phase1 = ChatPromptTemplate.from_messages([
        ("system", "{base_prompt}"),
        ("human", """
{facts_text}
 
Context:
{context}
 
Task: Extract components and properties for:
{input}
 
[OUTPUT START]
""")
    ])
    
    chain_phase1 = create_stuff_documents_chain(llm=llm, prompt=prompt_phase1)
        
    print("RAG PHASE 1: Extracting Components...", flush=True)
    result_phase1 = chain_phase1.invoke({
        "input": query, 
        "context": context_docs, 
        "facts_text": facts_text,
        "base_prompt": base_prompt_phase1
    })
 
    def _clean_yaml(res: str) -> str:
        c = re.sub(r"^```.*\n", "", res, flags=re.MULTILINE)
        c = c.replace("```", "")
        if "[OUTPUT END]" in c:
            c = c.split("[OUTPUT END]")[0].strip()
        lines = c.splitlines()
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if (stripped.startswith("**") or
                    (stripped.startswith("|") and stripped.endswith("|")) or
                    (stripped.startswith("#") and not stripped.startswith("#!"))):
                break
            clean_lines.append(line)
        c = "\n".join(clean_lines)
        pattern = r"[\"']?(properties|component_types|components|relations)[\"']?\s*:"
        match = re.search(pattern, c, re.MULTILINE | re.IGNORECASE)
        if match:
            key_start = match.start()
            pre_c = c[:key_start].rstrip()
            if pre_c.endswith('{'):
                c = c[key_start:]
                c = c.rstrip()
                if c.endswith('}') or c.endswith("}"):
                    c = c.rstrip()[:-1].rstrip()
            else:
                c = c[key_start:]
        return c
 
    clean_p1 = _clean_yaml(result_phase1)
    
    # Phase 2:Relation Extraction
    # 
    base_prompt_phase2 = f"""You are a specialized EDMM Topology Extractor.

You have already successfully extracted the components and properties from the infrastructure code.
Here are the extracted Phase 1 components — use THESE EXACT names for source/target fields:
```yaml
{clean_p1}
```

{platform_rules}

[CRITICAL RELATION RULES]
1. **Output ONLY VALID YAML** containing a SINGLE root key named `relations`. No markdown fences, no conversational text.
2. **Find Network Edges (ConnectsTo)**: Analyze the ORIGINAL SOURCE 
   FILES provided in the context (Kubernetes manifests, Terraform 
   files, Ansible tasks) directly. Also scan the `properties` block 
   of every extracted component for env var references.
   **CRUCIAL**: Strip protocol prefixes (http://, https://, jdbc:*://)
   and port suffixes (:NNNN) before matching. Example:
   `http://otelcol:4318` → matches `otelcol`;
   `jdbc:postgresql://postgres:5432/mydb` → matches `postgres`.
   
   CONFIG EXCLUSION: Configuration files (ConfigMaps, variable files, 
   inventory vars) are NEVER part of the network topology. Do NOT create 
   ConnectsTo relations simply because a config script or variable file 
   references a host. ONLY create ConnectsTo for explicit runtime 
   network communication between actual service components.
3. **CRITICAL - EXACT TARGET NAMES**: You MUST use the EXACT full name from the component list above for `source` and `target`. DO NOT use abbreviated or short names.
4. **Terraform depends_on**: If the source files contain a `depends_on` 
   block, create a relation for each referenced component. 
   Use `DependsOn` as the default relation type, but infer a more 
   specific type from context if possible:
   - If the target is a database or service → use `ConnectsTo`
   - If the target is a storage/volume → use `AttachesTo`
   - If the target is a cluster/host → use `HostedOn`
   - If unclear → use `DependsOn`
5. **Find Hosting Edges (HostedOn)**: Create `HostedOn` relations for every component based on the platform type:
   - For Kubernetes / terraform_kubernetes / terraform_cluster:
     If a real cluster was defined in Phase 1, every component MUST 
     have HostedOn to THAT cluster. If no real cluster exists, use 
     defaultKubernetesCluster.
   - For Ansible: every component MUST have a HostedOn relation 
     targeting the host component defined in inventory/hosts.yaml 
     (e.g., if inventory says localhost → target: localhost; 
      if inventory says webserver01 → target: webserver01).
     Do NOT create relations to a cluster or DockerEngine.
   - For Docker Compose / Terraform Docker: every component MUST 
     have a HostedOn relation targeting `DefaultDockerEngine`.
6. **Valid Relation Types** — only create a relation when its definition is met:
   - **HostedOn**: Component runs ON an infrastructure host 
     (cluster, docker engine, VM). Use when a workload is deployed 
     to a platform.
   - **ConnectsTo**: Network communication between two application 
     components (API call, DB connection, message consumption). 
     Use when a component references another via env var, config, 
     or connection string.
   - **AttachesTo**: A storage/volume component is mounted to an 
     application component. Use for PVC/volume attachments.
   - **DependsOn**: Generic dependency when none of the above apply 
     (e.g. startup order). Use as last resort only.
7. **Relation Name (KEY)**: Each relation MUST use this naming convention:
   `{{source}}_{{relationType}}_{{target}}`
   Example: `componentA_ConnectsTo_componentB`

8. **Syntax**:
relations:
  - {{source}}_{{relationType}}_{{target}}:   # relation NAME/KEY
      type: ConnectsTo                        # relation TYPE
      source: source_node
      target: target_node
      properties: []
      operations: []

END your output with `[OUTPUT END]` on a new line.
"""
 
    prompt_phase2 = ChatPromptTemplate.from_messages([
        ("system", "{base_prompt}"),
        ("human", """
Original Context to verify network variables:
{context}

Task: Output ONLY the `relations` YAML list that connects the components defined previously.

[OUTPUT START]
""")
    ])
 
    chain_phase2 = create_stuff_documents_chain(llm=llm, prompt=prompt_phase2)
 
    print("RAG PHASE 2: Extracting Relations...", flush=True)
    result_phase2 = chain_phase2.invoke({
        "context": context_docs,
        "base_prompt": base_prompt_phase2
    })
    
    clean_p2 = _clean_yaml(result_phase2)
 
    print(f"DEBUG Phase 1:\n{clean_p1}\n", flush=True)
    print(f"DEBUG Phase 2 (raw):\n{clean_p2}\n", flush=True)
 
    # Self-Consistency Normalization
    
    def normalize_relation_targets(p1_yaml_str: str, p2_yaml_str: str, platform: str = "") -> str:
        """Fix short-name targets in Phase 2 by matching against Phase 1 component names."""
        try:
            import yaml as _yaml
            p1_data = _yaml.safe_load(p1_yaml_str) or {}
            p2_data = _yaml.safe_load(p2_yaml_str) or {}
 
            p1_components = []
            for item in p1_data.get("components", []):
                if isinstance(item, dict):
                    if "name" in item:
                        p1_components.append(item["name"])
                    else:
                        p1_components.extend(item.keys())
 
            if not p1_components or not p2_data.get("relations"):
                return p2_yaml_str
 
            def resolve_name(name: str) -> str:
                if not name: return ""
                if name in p1_components:
                    return name
                matches = [c for c in p1_components if c.endswith(name) or c.endswith(f"-{name}")]
                if len(matches) == 1:
                    return matches[0]
                contains = [c for c in p1_components if name in c]
                if len(contains) == 1:
                    return contains[0]
                return name
 
            fixed_relations = []
            seen_edges = set()
 
            raw_relations = p2_data.get("relations", [])
            
            def process_relation(rel_body):
                src = resolve_name(rel_body.get("source", ""))
                tgt = resolve_name(rel_body.get("target", ""))
                rtype = rel_body.get("type", "ConnectsTo")
                
                edge_key = (src, tgt, rtype)
                if edge_key in seen_edges:
                    print(f"  [DEDUP] Skipping duplicate relation: {src} --[{rtype}]--> {tgt}", flush=True)
                    return None
                seen_edges.add(edge_key)
                
                def make_rel_name(src: str, tgt: str, rtype: str) -> str:
                    return f"{src}_{rtype}_{tgt}"
                
                rel_name = make_rel_name(src, tgt, rtype)
                return {
                    rel_name: {
                        "type": rtype,
                        "source": src,
                        "target": tgt,
                        "properties": rel_body.get("properties", []),
                        "operations": rel_body.get("operations", [])
                    }
                }
 
            if isinstance(raw_relations, list):
                for item in raw_relations:
                    if isinstance(item, dict):
                        if len(item) == 1 and isinstance(list(item.values())[0], dict) and "source" in list(item.values())[0]:
                            rel_name = list(item.keys())[0]
                            rel_body = item[rel_name]
                            fixed = process_relation(rel_body)
                            if fixed: fixed_relations.append(fixed)
                        elif "source" in item and "target" in item:
                            fixed = process_relation(item)
                            if fixed: fixed_relations.append(fixed)
                        else:
                            fixed_relations.append(item)
                    else:
                        fixed_relations.append(item)
 
            p2_data["relations"] = fixed_relations
            return _yaml.dump(p2_data, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            print(f"WARN: normalize_relation_targets failed: {e}", flush=True)
            return p2_yaml_str
 
    clean_p2 = normalize_relation_targets(clean_p1, clean_p2, platform=platform_final or "")
    print(f"DEBUG Phase 2 (normalized):\n{clean_p2}\n", flush=True)
 
    combined_yaml = f"{clean_p1}\n---\n{clean_p2}"
 
    # 7) Clean Output

    clean_result = combined_yaml
 
    # 8) Validate & Post-Process
    try:
        import yaml, json as _json, re as _re
        try:
            data = {}
            parts = _re.split(r'\n---\n', clean_result)
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                try:
                    doc = yaml.safe_load(part)
                    if not isinstance(doc, dict):
                        continue
                    if i == 0:
                        data.update(doc)
                    else:
                        for key in ("relations", "relation_types"):
                            if key in doc:
                                if key in data and isinstance(data[key], list) and isinstance(doc[key], list):
                                    data[key] = data[key] + doc[key]
                                else:
                                    data[key] = doc[key]
                except Exception:
                    pass
            if not data:
                raise ValueError("No valid YAML document found in output")
        except Exception as yaml_err:
            print(f"WARN: YAML parse failed ({yaml_err}), attempting JSON fallback...", flush=True)
            try:
                data = _json.loads(clean_result)
                print("INFO: Parsed output as JSON successfully.", flush=True)
            except Exception:
                raise yaml_err
        
        # Post-processing sanitization
        print("Running Python-side sanitization...", flush=True)
        from rag_post_process import post_process_edmm
        data = post_process_edmm(data, platform=platform_final or "", strict_integrity=False)
        
        if data is None:
            data = {}
            print("WARN: Data was None after sanitization (likely empty LLM output).", flush=True)
 
        return data
        
    except Exception as e:
        print(f"Generated output is NOT valid YAML: {e}", flush=True)
        return {"error": str(e), "raw_output": clean_result}