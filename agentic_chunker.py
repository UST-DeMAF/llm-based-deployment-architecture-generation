"""
Agentic Chunking for Infrastructure-as-Code (IaC)

Uses LangChain + Ollama (local LLM) instead of Anthropic Claude.
"""

from __future__ import annotations

import json
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Data Models

@dataclass
class IaCResource:
    """Represents a single infrastructure resource."""
    name: str
    kind: str  # Deployment, Service, resource, play, etc.
    content: str
    metadata: Dict[str, Any]
    
    def __repr__(self):
        return f"IaCResource(name={self.name}, kind={self.kind})"


@dataclass
class SemanticChunk:
    """A semantically grouped chunk of resources."""
    id: str
    resources: List[IaCResource]
    group_reason: str  # Why these were grouped together
    content: str  # Combined YAML/HCL content
    
    def __repr__(self):
        resource_names = [r.name for r in self.resources]
        return f"SemanticChunk(id={self.id}, resources={resource_names})"


# Agentic Chunker

class IaCAgenticChunker:
    """
    Agentic chunking for Infrastructure-as-Code.
    
    Uses LLM to make smart decisions about grouping resources
    based on semantic relationships (dependencies, shared purpose, etc.)
    """
    
    def __init__(
        self, 
        model_name: str = "gpt-oss",
        ollama_host: str = "http://localhost:11437",
        timeout: float = 300.0
    ):
        self.llm = OllamaLLM(
            model=model_name,
            base_url=ollama_host,
            timeout=timeout,
            num_ctx=4096
        )
    
    def _extract_json(self, text: str) -> Any:
        """Extract JSON from LLM response (handles markdown blocks)."""
        text = text.strip()
        

        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            text = match.group(1)
        
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fallback: find JSON structure
            if "{" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                return json.loads(text[start:end])
            if "[" in text:
                start = text.find("[")
                end = text.rfind("]") + 1
                return json.loads(text[start:end])
        
        return None
    
    def analyze_resource_dependencies(
        self, 
        resources: List[IaCResource]
    ) -> Dict[str, List[str]]:
        """
        Use LLM to identify dependencies between resources.
        
        Returns:
            Dict mapping resource name -> list of dependent resource names
        """
        
        # Build resource summary
        resource_summary = []
        for r in resources:
            # Extract key info from content
            summary = f"- {r.name} ({r.kind})"
            
            # Add relevant metadata hints
            if "env" in r.content.lower():
                env_matches = re.findall(r"(\w+)_HOST|(\w+)_URL|(\w+)_SERVICE", r.content, re.IGNORECASE)
                if env_matches:
                    deps = [m[0] or m[1] or m[2] for m in env_matches if m[0] or m[1] or m[2]]
                    summary += f" → env refs: {', '.join(deps)}"
            
            resource_summary.append(summary)
        DEPENDENCY_PROMPT = """You are an expert infrastructure analyzer.
    Analyze the following {platform} resources and identify dependencies.
    
    Resources:
    {resources_text}
    
    Return a JSON object with a list of dependencies. Each dependency should have:
    - source: name of the resource depending on something
    - target: name of the resource being depended on
    - type: type of dependency (service_discovery, network, volume, config, order, explicit_ref)
    
    Example output format:
    {{
      "dependencies": [
        {{ "source": "frontend-deployment", "target": "backend-service", "type": "network" }},
        {{ "source": "backend-deployment", "target": "db-config", "type": "config" }}
      ]
    }}
    
    Return ONLY valid JSON.
    """

        prompt = ChatPromptTemplate.from_messages([("system", DEPENDENCY_PROMPT)])
        chain = prompt | self.llm | StrOutputParser()
        
        try:
            response = chain.invoke({"platform": "kubernetes", "resources_text": chr(10).join(resource_summary)})
            data = self._extract_json(response)
            
            if data and "dependencies" in data:
                # Convert the new dependency format to the old one for compatibility
                old_format_deps = {}
                for dep in data["dependencies"]:
                    source = dep.get("source")
                    target = dep.get("target")
                    if source and target:
                        if source not in old_format_deps:
                            old_format_deps[source] = []
                        old_format_deps[source].append(target)
                return old_format_deps
            
            return {}
        
        except Exception as e:
            print(f"⚠️  Dependency analysis failed: {e}", flush=True)
            return {}
    
    def group_resources_semantically(
        self,
        resources: List[IaCResource],
        platform: str = "kubernetes"
    ) -> List[Dict[str, Any]]:
        """
        Use LLM to group resources into semantic chunks.
        
        Args:
            resources: List of infrastructure resources
            platform: kubernetes, ansible, or terraform
        
        Returns:
            List of groups, where each group is a list of resource names
        """
        
        # Get dependencies first
        dependencies = self.analyze_resource_dependencies(resources)
        
        # Build resource list with dependency info
        resource_info = []
        for r in resources:
            info = f"- {r.name} ({r.kind})"
            if r.name in dependencies:
                deps = dependencies[r.name]
                if deps:
                    info += f" → depends on: {', '.join(deps)}"
            resource_info.append(info)
        
        platform_hints = {
            "kubernetes": """
            Group by:
            - Microservice boundaries (app Deployment + Service + ConfigMap)
            - Shared dependencies (app + database it uses)
            - Functional layers (all monitoring tools together)
            """,
            "ansible": """
            Group by:
            - Target hosts (tasks for same host group)
            - Deployment stages (setup → install → configure)
            - Component stacks (web server + app + database)
            """,
            "terraform": """
            Group by:
            - Resource dependencies (VPC → subnet → instance)
            - Module boundaries (networking module, compute module)
            - Shared tags or project names
            """
        }
        
        # Semantic grouping prompt with proper escaping
        SEMANTIC_GROUP_PROMPT = """You are an expert infrastructure architect.
    Group the following {platform} resources into logical semantic units (e.g., a microservice and its config, a database cluster, an ingress stack).
    
    Resources:
    {resources_text}
    
    Dependencies:
    {dependencies_json}
    
    Rules for grouping:
    1. A Deployment/StatefulSet should be grouped with its Service, ConfigMap, and Secret.
    2. Database components (StorageClass, PVC, Service, Deployment) should be grouped together.
    3. Ingress rules should be grouped with the services they expose if possible, or a separate 'Routing' group.
    4. Related resources that must eventually be deployed together (like a T2Store component) should be in one group.
    
    Return a JSON object with a list of groups.
    
    Example output format:
    {{
      "groups": [
        {{
          "name": "Payment Service Stack",
          "resources": ["payment-deploy", "payment-svc", "payment-config"],
          "reason": "Core service components"
        }},
        {{
          "name": "Database Cluster",
          "resources": ["postgres-statefulset", "postgres-svc", "postgres-pvc"],
          "reason": "Database and storage"
        }}
      ]
    }}
    
    CRITICAL: In the "resources" list, you MUST use the EXACT resource names as provided in the Resources section above. 
    Do NOT shorten, abbreviate, modify, or paraphrase any resource name.
    Copy the name character by character as given.

    Return ONLY valid JSON.
    """

        prompt = ChatPromptTemplate.from_messages([("system", SEMANTIC_GROUP_PROMPT)])
        chain = prompt | self.llm | StrOutputParser()
        
        try:
            dep_json = json.dumps(dependencies, indent=2)
            response = chain.invoke({
                "platform": platform, 
                "resources_text": "\n".join(resource_info),
                "dependencies_json": dep_json
            })
            data = self._extract_json(response)
            
            if data and "groups" in data:
                groups = []
                for group in data["groups"]:
                    if "resources" in group:
                        groups.append({
                            "name": group.get("name", f"Group {len(groups)+1}"),
                            "resources": group["resources"]
                        })
                return groups
            
            # Fallback: keep all together
            all_names = [r.name for r in resources]
            return [{"name": "Default Group", "resources": all_names}]
        
        except Exception as e:
            print(f"⚠️  Semantic grouping failed: {e}", flush=True)
            # Fallback
            all_names = [r.name for r in resources]
            return [{"name": "Default Group", "resources": all_names}]
    
    def chunk_resources(
        self,
        resources: List[IaCResource],
        platform: str = "kubernetes"
    ) -> List[SemanticChunk]:
        """
        Main chunking function.
        
        Args:
            resources: List of IaCResource objects
            platform: Platform type (kubernetes, ansible, terraform)
        
        Returns:
            List of SemanticChunk objects
        """
        
        print(f"🤖 Agentic chunking: {len(resources)} {platform} resources", flush=True)
        
        # Get semantic groups from LLM
        groups = self.group_resources_semantically(resources, platform)
        
        print(f"✅ Created {len(groups)} semantic chunks", flush=True)
        
        # Build SemanticChunk objects
        chunks = []
        resource_map = {r.name: r for r in resources}
        
        for i, group in enumerate(groups, 1):
            group_name = group.get("name", f"Chunk {i}")
            resource_names = group["resources"]
            
            # Get actual resource objects
            group_resources = []
            for name in resource_names:
                if name in resource_map:
                    group_resources.append(resource_map[name])
                else:
                    print(f"⚠️  Resource not found: {name}", flush=True)
            
            if not group_resources:
                continue
            
            # Combine content
            combined_content = "\n---\n".join([r.content for r in group_resources])
            
            chunk = SemanticChunk(
                id=f"semantic_chunk_{i}",
                resources=group_resources,
                group_reason=f"Semantic group: {group_name}",
                content=combined_content
            )
            
            chunks.append(chunk)
            print(f"  Chunk {i}: {group_name} ({len(group_resources)} resources)", flush=True)
        
        return chunks



# Integration Helpers


def kubernetes_resources_to_iac_resources(yaml_pieces: List[Tuple[str, str, str, str]]) -> List[IaCResource]:
    """
    Convert split_k8_multi_doc_yaml output to IaCResource objects.
    
    Args:
        yaml_pieces: Output from split_k8_multi_doc_yaml
                     [(yaml_text, kind, name, namespace), ...]
    
    Returns:
        List of IaCResource objects
    """
    resources = []
    
    for yaml_text, kind, name, namespace in yaml_pieces:
        if not name:
            name = f"unnamed_{kind}_{len(resources)}"
        
        resource = IaCResource(
            name=name,
            kind=kind or "Unknown",
            content=yaml_text,
            metadata={
                "kind": kind,
                "namespace": namespace
            }
        )
        resources.append(resource)
    
    return resources


def ansible_to_iac_resources(plays: List[str]) -> List[IaCResource]:
    """
    Convert split_ansible_playbook output to IaCResource objects.
    
    Args:
        plays: List of Ansible play texts from split_ansible_playbook
    
    Returns:
        List of IaCResource objects
    """
    resources = []
    
    for i, play_text in enumerate(plays, 1):
        # Try to extract play name from "- name:" line
        name_match = re.search(r"^\s*-?\s*name:\s*(.+)$", play_text, re.MULTILINE)
        if name_match:
            name = name_match.group(1).strip()
        else:
            # Fallback: extract from "hosts:" line
            hosts_match = re.search(r"hosts:\s*(\S+)", play_text)
            if hosts_match:
                name = f"play_{hosts_match.group(1)}"
            else:
                name = f"play_{i}"
        
        resource = IaCResource(
            name=name,
            kind="AnsiblePlay",
            content=play_text,
            metadata={"play_index": i}
        )
        resources.append(resource)
    
    return resources


def terraform_to_iac_resources(blocks: List[str]) -> List[IaCResource]:
    """
    Convert split_terraform_blocks output to IaCResource objects.
    
    Args:
        blocks: List of Terraform block texts
    
    Returns:
        List of IaCResource objects
    """
    resources = []
    
    for i, block_text in enumerate(blocks, 1):
        # Extract resource type and name
        # Example: resource "aws_instance" "web" { ... }
        match = re.search(r'(resource|module|provider|data)\s+"([^"]+)"\s+"([^"]+)"', block_text)
        
        if match:
            block_type = match.group(1)
            resource_type = match.group(2)
            resource_name = match.group(3)
            name = f"{resource_type}_{resource_name}"
            kind = f"TF_{block_type}"
        else:
            # Fallback for variable, output, etc
            var_match = re.search(r'(variable|output|locals)\s+"([^"]+)"', block_text)
            if var_match:
                block_type = var_match.group(1)
                var_name = var_match.group(2)
                name = f"{block_type}_{var_name}"
                kind = f"TF_{block_type}"
            else:
                name = f"block_{i}"
                kind = "TF_block"
        
        resource = IaCResource(
            name=name,
            kind=kind,
            content=block_text,
            metadata={"block_index": i}
        )
        resources.append(resource)
    
    return resources



# Example Usage

if __name__ == "__main__":
    # Example: Kubernetes resources
    example_resources = [
        IaCResource(
            name="grafana",
            kind="Deployment",
            content="""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
spec:
  containers:
  - env:
    - name: GF_DATABASE_HOST
      value: postgres
    - name: GF_REDIS_HOST
      value: redis
""",
            metadata={"kind": "Deployment"}
        ),
        IaCResource(
            name="grafana-service",
            kind="Service",
            content="""
apiVersion: v1
kind: Service
metadata:
  name: grafana-service
spec:
  selector:
    app: grafana
""",
            metadata={"kind": "Service"}
        ),
        IaCResource(
            name="postgres",
            kind="Deployment",
            content="""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
""",
            metadata={"kind": "Deployment"}
        ),
        IaCResource(
            name="redis",
            kind="Deployment",
            content="""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
""",
            metadata={"kind": "Deployment"}
        ),
        IaCResource(
            name="prometheus",
            kind="Deployment",
            content="""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
""",
            metadata={"kind": "Deployment"}
        )
    ]
    
    # Create chunker
    chunker = IaCAgenticChunker()
    
    # Chunk resources
    chunks = chunker.chunk_resources(example_resources, platform="kubernetes")
    
    # Print results
    print("\n=== Agentic Chunking Results ===")
    for chunk in chunks:
        print(f"\n{chunk.id}: {chunk.group_reason}")
        for res in chunk.resources:
            print(f"  - {res.name} ({res.kind})")
