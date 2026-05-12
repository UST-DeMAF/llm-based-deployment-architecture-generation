"""
No-RAG Baseline: LLM + Prompt Rules only (no ChromaDB, no KB retrieval)
Fragment-based processing for ALL platforms and cases.

Usage:
  python no_rag_final.py --case kubernetes
  python no_rag_final.py --case terraform
  python no_rag_final.py --case ansible
  python no_rag_final.py --case t2store
  python no_rag_final.py --case meitrex
"""

import requests
import yaml
import re
import argparse
from pathlib import Path

OLLAMA_HOST = "http://localhost:11437"
MODEL = "gpt-oss:latest"
BASE_DIR = Path("/app/project_folder/Evaluation")
RESULTS_DIR = Path("/app/project_folder/ResultsNoRAG")

CASES = {
    "boutiqueshop": {
    "dir": BASE_DIR / "BoutiqueShop/deploymentModel",
    "platform": "kubernetes,terraform_cluster",
    "output": RESULTS_DIR / "actual_boutiqueshop.yaml",
    "mode": "t2store_fragment",
    },
    "kubernetes": {
        "dir": BASE_DIR / "OTEL-Shop-Kubernetes/deploymentModel",
        "platform": "kubernetes",
        "output": RESULTS_DIR / "actual_kubernetes.yaml",
        "mode": "k8s_fragment",
    },
    "terraform": {
        "dir": BASE_DIR / "OTEL-Shop-Terraform/deploymentModel",
        "platform": "terraform_docker",
        "output": RESULTS_DIR / "actual_terraform.yaml",
        "mode": "tf_fragment",
    },
    "ansible": {
        "dir": BASE_DIR / "OTEL-Shop-Ansible/deploymentModel",
        "platform": "ansible",
        "output": RESULTS_DIR / "actual_ansible.yaml",
        "mode": "ansible_fragment",
    },
    "t2store": {
        "dir": BASE_DIR / "T2Store-Modulith/deploymentModel",
        "platform": "kubernetes,terraform_cluster",
        "output": RESULTS_DIR / "actual_t2storemodulith.yaml",
        "mode": "t2store_fragment",
    },
    "t2store_micro": {
        "dir": BASE_DIR / "T2Store-Microservices/deploymentModel",
        "platform": "kubernetes,terraform_cluster",
        "output": RESULTS_DIR / "actual_t2storemicroservices.yaml",
        "mode": "t2store_fragment",
    },
    "meitrex": {
        "dir": BASE_DIR / "Meitrex/deploymentModel",
        "platform": "terraform_kubernetes",
        "output": RESULTS_DIR / "actual_meitrex.yaml",
        "mode": "tf_fragment",
    },
}

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

✅ ALWAYS create a component for every Deployment/StatefulSet/DaemonSet, even if it has
   NO env vars with plain value: fields. A component with empty properties is valid.
✅ env vars using valueFrom (secretKeyRef, configMapKeyRef, fieldRef) → SKIP, do not add
   to properties. But the component MUST still be created.
✅ Derive component type from the container image, not from env vars:
   image: "docker.io/grafana/grafana:11.1.0" → type: grafana-SoftwareApplication
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
   Examples:
   helm install mongo-cart bitnami/mongodb  → mongo-cart-mongodb  (NOT mongo-cart)
   helm install mongo-order bitnami/mongodb → mongo-order-mongodb (NOT mongo-order)
   helm install kafka bitnami/kafka         → kafka-kafka         (NOT kafka)
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

COMMON_RULES = """
[EDMM SPECIFICATION]
EDMM (Essential Deployment Metamodel) describes a deployment model declaratively.

[COMPONENT TYPES HIERARCHY]
BaseType (root)
  ├── SoftwareApplication
  │     ├── DatabaseSystem      (postgres, mysql, mongo, redis, valkey, opensearch...)
  │     └── MessageBroker       (kafka, rabbitmq, nats, pulsar...)
  ├── ContainerPlatform
  │     ├── KubernetesCluster
  │     │     └── DefaultKubernetesCluster
  │     └── DockerEngine
  │           └── DefaultDockerEngine
  ├── Storage                   (PVC volumes, persistent disks)
  └── CloudProvider             (MicrosoftAzure, AmazonWebServices, GoogleCloudPlatform)

[OUTPUT FORMAT]
---
component_types:
  - <TypeName>:
      extends: <ParentType>
      description: null
      properties: []
      operations: []

components:
  - <component-name>:
      type: <TypeName>
      description: null
      properties:
        - <key>: <value>
      operations: []
      artifacts:
        - docker_image:
            name: <full-image:tag>
            fileURI: <registry-url>

relations:
  - <source>_<RelationType>_<target>:
      type: <RelationType>
      source: <source-component-name>
      target: <target-component-name>
      description: null
      properties: []
      operations: []

relation_types:
  - AttachesTo:
      extends: DependsOn
      properties:
        - location: <mountPath>   # REQUIRED for AttachesTo
  - ConnectsTo:
      extends: DependsOn
  - DependsOn:
      extends: '-'
  - HostedOn:
      extends: DependsOn

[RELATION RULES]
- HostedOn:   Component runs ON infrastructure (cluster, VM, Docker engine)
              Use when a workload is deployed to a platform
- ConnectsTo: Network communication between application components
              Use when a component references another via env var or connection string
              Strip protocol prefixes (http://, jdbc://) and port suffixes before matching
              NEVER ConnectsTo infrastructure (cluster, DockerEngine, CloudProvider)
- AttachesTo: Storage/volume mounted to a component
              MUST include location property (= mountPath)
- DependsOn:  Generic dependency — use ONLY as last resort

[ARTIFACT RULES]
Every component with a Docker image MUST declare:
  artifacts:
    - docker_image:
        name: <full image:tag>        # e.g. ghcr.io/org/demo:1.0.0-cartservice
        fileURI: <registry URL>       # e.g. https://ghcr.io/org/demo

Infrastructure components (cluster, DockerEngine, CloudProvider, Storage) have NO artifacts.

[PROPERTY RULES]
Properties MUST be a List of single-key maps:
  CORRECT:   properties:
               - port: 8080
               - HOST: myservice
  INCORRECT: properties:
               port: 8080
               HOST: myservice

[TYPE DERIVATION RULES]
Apply in order:
1. Database tech in name/image (mongo, redis, valkey, postgres, mysql, opensearch) 
   → <tech>-DatabaseSystem
2. Message broker in name/image (kafka, rabbitmq, nats) 
   → <tech>-MessageBroker
3. Image tag has hyphenated suffix (demo:1.0.0-cartservice) 
   → extract last token → cartservice-SoftwareApplication
4. Otherwise strip generic prefixes and use 
   → <clean_name>-SoftwareApplication

[CRITICAL RULES]
1. Output ONLY valid YAML — no markdown fences, no explanation text
2. Component name = EXACT name from source file
   - Kubernetes: metadata.name field
   - Terraform: resource LABEL (second string): resource "docker_container" "myservice" → myservice
   - Ansible: role name from roles/ directory
3. Every workload MUST have a HostedOn relation to its host
4. Do NOT create components for: ConfigMaps, Secrets, ServiceAccounts, Namespaces,
   docker_network, random_password, null_resource, data sources, variables
5. Do NOT invent components not present in source files
6. ALWAYS create a component for EVERY Deployment/StatefulSet/DaemonSet found in input,
   even if the component has no extractable env var properties. Empty properties: [] is valid.
   NEVER skip a workload just because its env vars all use valueFrom.
"""

PLATFORM_RULES = {
    "kubernetes": """
[KUBERNETES RULES]
- Components ONLY for: Deployments, StatefulSets, DaemonSets
- Component name = exact metadata.name
- Always create defaultKubernetesCluster (type: DefaultKubernetesCluster)
- Every workload HostedOn defaultKubernetesCluster
- ConnectsTo from env vars referencing other component names
- Include imagePullPolicy (default: IfNotPresent)
- Skip: Services, ConfigMaps, Secrets, ServiceAccounts, Namespaces
- StatefulSet volumeClaimTemplates → Storage: <statefulset>-<claim>-volume
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
""",
    "terraform_docker": """
[TERRAFORM DOCKER RULES]
- Create DefaultDockerEngine (type: DockerEngine)
- Each docker_container resource → one component
- Component name = Terraform resource LABEL (second string in resource block)
  e.g. resource "docker_container" "accountingservice" → name: accountingservice
- Every workload HostedOn DefaultDockerEngine
- ConnectsTo from env vars and depends_on
- Do NOT include imagePullPolicy
- Skip: docker_network, random_password, null_resource, variables, data sources
""",
    "ansible": """
[ANSIBLE RULES]
- Host component from inventory/hosts.yaml
- Each role → one component (name = role name)
- Every role HostedOn the host from inventory
- ConnectsTo from env vars referencing other service names
- Relation names camelCase: connectsTo, hostedOn
- Do NOT create defaultKubernetesCluster or DefaultDockerEngine
- Do NOT include imagePullPolicy
- TWO operations per service: Pull image first, then Deploy
- Each operation has TWO artifacts: docker_image AND bash
""",
    "kubernetes,terraform_cluster": """
[TERRAFORM CLUSTER + KUBERNETES RULES]
- azurerm_kubernetes_cluster → cluster component, create MicrosoftAzure (type: CloudProvider)
- google_container_cluster → cluster component, create GoogleCloudPlatform (type: CloudProvider)
- aws_eks_cluster → cluster component, create AmazonWebServices (type: CloudProvider)
- cluster_HostedOn_MicrosoftAzure relation always present
- K8s workloads HostedOn the real cluster name (NOT defaultKubernetesCluster)
- helm install <release> <repo>/<chart> in .sh → component: <release>-<chart>
  EXCEPTION: If release name == chart name, use just <release> (no duplication)
  Examples: helm install mongo-cart bitnami/mongodb → mongo-cart-mongodb
            helm install kafka bitnami/kafka         → kafka
- StatefulSet volumeClaimTemplates → Storage: <statefulset>-<claim>-volume
- Include imagePullPolicy (default: IfNotPresent)
""",
    "terraform_kubernetes": """
[TERRAFORM KUBERNETES/HELM RULES]
- Components for: kubernetes_deployment, helm_release
- helm_release chart name → component name, type from chart
- Always create defaultKubernetesCluster (type: DefaultKubernetesCluster)
- Every workload HostedOn defaultKubernetesCluster
- Do NOT create CloudProvider
- Skip: kubernetes_namespace, kubernetes_secret, variables, data sources
""",
}


def _select_example(platform: str) -> str:
    p = platform.lower()
    if "ansible" in p:
        return ANSIBLE_EXAMPLE
    if "terraform" in p:
        if "cluster" in p or "azure" in p or "aws" in p:
            return TERRAFORM_CLUSTER_EXAMPLE
        if "kubernetes" in p:
            return TERRAFORM_CLUSTER_EXAMPLE
        return DOCKER_COMPOSE_EXAMPLE  # terraform_docker default
    if "kubernetes" in p or "k8" in p:
        return KUBERNETES_EXAMPLE
    return KUBERNETES_EXAMPLE


def call_ollama(prompt: str) -> str:
    response = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": 16384}
        },
        timeout=900
    )
    if response.status_code != 200:
        raise Exception(f"Ollama error: {response.status_code}")
    return response.json()["response"]


def convert_to_edmm(iac_content: str, platform: str) -> str:
    rules = PLATFORM_RULES.get(platform, "")
    selected_example = _select_example(platform)  # ← few-shot example
    prompt = f"""You are an EDMM compiler. Convert infrastructure code to EDMM YAML.

{COMMON_RULES}

{rules}

{selected_example}

[INPUT]
{iac_content}

[EDMM OUTPUT]
---
"""
    return call_ollama(prompt)


def merge_outputs(outputs: list) -> str:
    all_components = []
    all_relations = []
    seen_comp = set()
    seen_rel = set()

    for output in outputs:
        clean = re.sub(r"^```.*\n", "", output, flags=re.MULTILINE)
        clean = clean.replace("```", "")
        clean = clean.split("[OUTPUT END]")[0].strip()
        parts = re.split(r'\n---\n', clean)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            try:
                doc = yaml.safe_load(part)
                if not isinstance(doc, dict):
                    continue
                comps = doc.get("components", [])
                if isinstance(comps, dict):
                    comps = [{k: v} for k, v in comps.items()]
                for c in comps:
                    if isinstance(c, dict):
                        k = list(c.keys())[0]
                        if k not in seen_comp:
                            seen_comp.add(k)
                            all_components.append(c)
                rels = doc.get("relations", [])
                if isinstance(rels, dict):
                    rels = [{k: v} for k, v in rels.items()]
                for r in rels:
                    if isinstance(r, dict):
                        k = list(r.keys())[0]
                        v = r[k]
                        # "true" format 
                        if v is True or v is None:
                            for rt in ["ConnectsTo", "HostedOn",
                                      "AttachesTo", "DependsOn"]:
                                if rt in k:
                                    idx = k.index(rt)
                                    src = k[:idx-1]
                                    tgt = k[idx+len(rt)+1:]
                                    r = {k: {
                                        "type": rt,
                                        "source": src,
                                        "target": tgt,
                                        "properties": [],
                                        "operations": []
                                    }}
                                    break
                            else:
                                continue
                        if k not in seen_rel:
                            seen_rel.add(k)
                            all_relations.append(r)
            except Exception as e:
                print(f"  ! parse warning: {e}", flush=True)

    return yaml.dump(
        {"components": all_components, "relations": all_relations},
        default_flow_style=False, allow_unicode=True
    )


# Phase 3: Global ConnectsTo extraction
def phase3_global_relations(components: list, platform: str) -> list:
    # generate comp_summary
    comp_summary = ""
    for c in components:
        if isinstance(c, dict):
            for name, body in c.items():
                props = (body or {}).get("properties", [])
                if isinstance(props, list):
                    prop_str = ", ".join(
                        f"{list(p.keys())[0]}={list(p.values())[0]}"
                        for p in props if isinstance(p, dict)
                    )
                else:
                    prop_str = ""
                comp_summary += f"- {name}: {prop_str}\n"

    is_ansible = "ansible" in platform.lower()
    rel_naming = "source_connectsTo_target" if is_ansible else "source_ConnectsTo_target"

    prompt = f"""You are an EDMM relation extractor.

Given the following components and their properties, identify ALL ConnectsTo relations.

For each component, scan its property VALUES for references to other component names.
Strip protocol prefixes (http://, https://, jdbc://) and port suffixes (:NNNN) before matching.

Components:
{comp_summary}

Rules:
- Only create ConnectsTo between components in the list above
- Do NOT create HostedOn relations
- Relation key naming: {rel_naming}
- Use EXACT component names listed above
- Output ONLY valid YAML with root key 'relations'

---
"""
    result = call_ollama(prompt)
    result = result.split("[OUTPUT END]")[0].strip()
    result = re.sub(r"```[a-zA-Z]*\n?", "", result).replace("```", "").strip()
    
    try:
        data = yaml.safe_load(result) or {}
        rels = data.get("relations", {})
        if isinstance(rels, dict):
            return [{k: v} for k, v in rels.items()]
        elif isinstance(rels, list):
            return rels
    except Exception as e:
        print(f"  ! Phase 3 parse error: {e}", flush=True)
    return []


# ── Fragment strategies ──────────────────────────────────────────────────────
def k8s_fragments(case_dir: Path) -> list:
    """One fragment per Deployment/StatefulSet/DaemonSet."""
    fragments = []
    for f in sorted(case_dir.rglob("*.yaml")) + sorted(case_dir.rglob("*.yml")):
        try:
            content = f.read_text(encoding="utf-8")
            for doc in content.split("\n---\n"):
                if any(k in doc for k in ["kind: Deployment", "kind: StatefulSet", "kind: DaemonSet"]):
                    fragments.append((f.name, doc))
        except Exception:
            pass
    return fragments


def tf_fragments(case_dir: Path) -> list:
    """One fragment per docker_container or per .tf file (for K8s/Helm TF)."""
    fragments = []
    for tf_file in sorted(case_dir.rglob("*.tf")):
        try:
            content = tf_file.read_text(encoding="utf-8")
            # Split per resource block
            blocks = re.split(r'\n(?=resource\s+")', content)
            current_batch = []
            current_size = 0
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                current_batch.append(block)
                current_size += len(block)
                # Send batch when ~3000 chars
                if current_size > 3000:
                    fragments.append((tf_file.name, "\n\n".join(current_batch)))
                    current_batch = []
                    current_size = 0
            if current_batch:
                fragments.append((tf_file.name, "\n\n".join(current_batch)))
        except Exception as e:
            print(f"  ! {tf_file.name}: {e}", flush=True)
    return fragments 


def ansible_fragments(case_dir: Path) -> list:
    """One fragment per Ansible role."""
    fragments = []
    hosts_content = ""
    for h in case_dir.rglob("hosts.yaml"):
        hosts_content = f"### hosts.yaml ###\n{h.read_text(encoding='utf-8')}\n\n"
        break

    roles_dir = case_dir / "roles"
    if not roles_dir.exists():
        return []

    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir():
            continue
        parts = [hosts_content]
        for ext in [".yaml", ".yml"]:
            for f in sorted(role_dir.rglob(f"*{ext}")):
                try:
                    text = f.read_text(encoding="utf-8")
                    if len(text.strip()) > 10:
                        parts.append(f"### {role_dir.name}/{f.name} ###\n{text}")
                except Exception:
                    pass
        if len(parts) > 1:
            fragments.append((role_dir.name, "\n\n".join(parts)))
    return fragments


def t2store_fragments(case_dir: Path) -> list:
    """T2Store: TF files + K8s YAMLs + shell scripts as separate fragments."""
    fragments = []
    # Terraform files together (small)
    tf_content = []
    for f in sorted(case_dir.rglob("*.tf")):
        try:
            tf_content.append(f"### {f.name} ###\n{f.read_text(encoding='utf-8')}")
        except Exception:
            pass
    # Shell scripts
    for f in sorted(case_dir.rglob("*.sh")):
        try:
            tf_content.append(f"### {f.name} ###\n{f.read_text(encoding='utf-8')}")
        except Exception:
            pass
    if tf_content:
        fragments.append(("terraform+sh", "\n\n".join(tf_content)))

    # K8s YAMLs — one per workload
    for f in sorted(case_dir.rglob("*.yaml")) + sorted(case_dir.rglob("*.yml")):
        try:
            content = f.read_text(encoding="utf-8")
            for doc in content.split("\n---\n"):
                if any(k in doc for k in ["kind: Deployment", "kind: StatefulSet"]):
                    fragments.append((f.name, doc))
        except Exception:
            pass
    return fragments

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=list(CASES.keys()))
    args = parser.parse_args()

    cfg = CASES[args.case]
    platform = cfg["platform"]
    output_path = cfg["output"]
    mode = cfg["mode"]

    print(f"\n{'='*60}", flush=True)
    print(f"No-RAG Baseline: {args.case} ({platform})", flush=True)
    print(f"Mode: {mode}", flush=True)
    print(f"{'='*60}\n", flush=True)

    # Get fragments based on mode
    if mode == "k8s_fragment":
        fragments = k8s_fragments(cfg["dir"])
    elif mode == "tf_fragment":
        fragments = tf_fragments(cfg["dir"])
    elif mode == "ansible_fragment":
        fragments = ansible_fragments(cfg["dir"])
    elif mode == "t2store_fragment":
        fragments = t2store_fragments(cfg["dir"])
    else:
        fragments = []

    print(f"Found {len(fragments)} fragments\n", flush=True)

    if not fragments:
        print("No fragments found!", flush=True)
        return

    outputs = []
    for i, (name, frag) in enumerate(fragments):
        print(f"[{i+1}/{len(fragments)}] Processing: {name} ({len(frag)} chars)...", flush=True)
        try:
            result = convert_to_edmm(frag, platform)
            outputs.append(result)
            print(f"  -> OK ({len(result)} chars)", flush=True)
        except Exception as e:
            print(f"  -> ERROR: {e}", flush=True)

    print(f"\nMerging {len(outputs)} outputs...", flush=True)
    final = merge_outputs(outputs)

    print("\nPhase 3: Extracting global relations...", flush=True)
    final_data = yaml.safe_load(final) or {}
    p3_rels = phase3_global_relations(final_data.get("components", []), platform)
    print(f"  Phase 3 added {len(p3_rels)} relations", flush=True)
    existing_keys = {list(r.keys())[0] for r in final_data.get("relations", []) if isinstance(r, dict)}
    for r in p3_rels:
        if isinstance(r, dict):
            k = list(r.keys())[0]
            if k not in existing_keys:
                final_data["relations"].append(r)
                existing_keys.add(k)
    final = yaml.dump(final_data, default_flow_style=False, allow_unicode=True)
    
    output_path.write_text(final, encoding="utf-8")
    print(f"\n✅ Written: {output_path}", flush=True)
    print(f"   Size: {len(final)} chars", flush=True)
    print("\n--- PREVIEW ---")
    print(final[:1000])


if __name__ == "__main__":
    main()