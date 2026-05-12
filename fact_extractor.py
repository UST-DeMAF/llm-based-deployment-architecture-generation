import yaml
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
import json

# Env variable name patterns that typically point to another service.
# Technology-agnostic — works for Kubernetes, Terraform, and Ansible.
RELATION_ENV_PATTERNS = re.compile(
    r'.*(_ADDR|_HOST|_URL|_SERVICE_ADDR|_SERVICE_HOST|_SERVICE_URL|_ENDPOINT|_URI|_DSN|_BROKER|_BOOTSTRAP)$',
    re.IGNORECASE
)


def _extract_service_name_from_value(value: str) -> Optional[str]:
    """
    Strip port numbers and protocols from a service address, returning only the hostname.

    Examples:
      "opentelemetry-demo-cartservice:8080"    -> "opentelemetry-demo-cartservice"
      "http://opentelemetry-demo-otelcol:4317" -> "opentelemetry-demo-otelcol"
    """
    if not isinstance(value, str):
        return None
    value = re.sub(r'^jdbc:[a-z]+://', '', value)       # strip jdbc:postgresql:// etc.
    value = re.sub(r'^amqp://', '', value)              # strip amqp://
    value = re.sub(r'^redis://', '', value)             # strip redis://
    value = re.sub(r'^mongodb://', '', value)           # strip mongodb://
    value = re.sub(r'^https?://|^grpc://', '', value)   # strip http(s):// or grpc://
    # Handle user:pass@hostname → keep hostname
    if '@' in value:
        value = value.split('@')[-1]
    value = re.sub(r':\d+.*$', '', value)               # strip port
    value = re.sub(r'/.*$', '', value)                  # strip URL path
    value = re.sub(r'\?.*$', '', value)                 # strip query params
    value = value.strip()
    if not value or re.match(r'^\d+\.\d+\.\d+\.\d+$', value) or value in ('localhost', '0.0.0.0', '127.0.0.1'):
        return None
    if len(value) < 3:
        return None
    return value


class ExtractedFact:
    def __init__(
        self,
        name: str,
        source_type: str,
        technology: str,
        image: str = None,
        ports: List[int] = None,
        envs: List[str] = None,
        env_values: Dict[str, str] = None,       # NEW: {env_key: raw_value}
        inferred_connects_to: List[str] = None,  # NEW: inferred service dependencies
    ):
        self.name = name
        self.source_type = source_type           # e.g. "Deployment", "docker_container", "ansible_role"
        self.technology = technology             # "kubernetes", "terraform", "ansible"
        self.image = image
        self.ports = ports or []
        self.envs = envs or []                               # key-only list (backwards compatible)
        self.env_values = env_values or {}                   # key -> value map
        self.inferred_connects_to = inferred_connects_to or []  # result of relation inference

    def to_dict(self):
        return {
            "name": self.name,
            "type": self.source_type,
            "technology": self.technology,
            "image": self.image,
            "ports": self.ports,
            "env_vars": self.envs,
            "env_values": self.env_values,
            "inferred_connects_to": self.inferred_connects_to,
        }

    def __repr__(self):
        return (
            f"Fact(name={self.name}, tech={self.technology}, "
            f"image={self.image}, ports={self.ports}, "
            f"connects_to={self.inferred_connects_to})"
        )


def _infer_connects_to(env_values: Dict[str, str]) -> List[str]:
    """
    Derive ConnectsTo candidates from env variable values.
    Technology-agnostic: same logic for Kubernetes, Terraform, and Ansible.

    Examples:
      CART_SERVICE_ADDR: opentelemetry-demo-cartservice:8080
        -> "opentelemetry-demo-cartservice"

      OTEL_EXPORTER_OTLP_ENDPOINT: http://opentelemetry-demo-otelcol:4317
        -> "opentelemetry-demo-otelcol"
    """
    candidates = []
    for key, value in env_values.items():
        if RELATION_ENV_PATTERNS.match(key):
            svc = _extract_service_name_from_value(value)
            if svc and svc not in candidates:
                candidates.append(svc)
    return candidates


class FactExtractor:
    def extract(self, file_path: str, content: str = None) -> List[ExtractedFact]:
        """
        Entry point. Detects technology from file_path and dispatches
        to the appropriate parser (_extract_k8s, _extract_terraform, _extract_ansible).
        """
        path = Path(file_path)
        if content is None:
            content = path.read_text(encoding='utf-8', errors='ignore')

        # Strip markdown code fences (may be present in RAG chunk content)
        content = re.sub(r"^```[a-zA-Z]*\n", "", content, flags=re.MULTILINE)
        content = content.replace("```", "")

        if path.name == "main.tf" or path.suffix == ".tf":
            return self._extract_terraform(content)
        elif "ansible" in str(path).lower() or "playbook" in str(path).lower() or path.name == "main.yaml":
            if self._is_ansible_playbook(content):
                return self._extract_ansible(content, path.parent)
            else:
                return self._extract_k8s(content)  # fallback to generic YAML check
        elif path.suffix in ['.yaml', '.yml']:
            # K8s manifests always contain 'kind:' and 'apiVersion:'
            # Application config files (otelcol, prometheus, etc.) do not — skip them
            if "kind:" not in content and "apiVersion:" not in content:
                return []
            return self._extract_k8s(content)
        else:
            return []

    def _extract_k8s(self, content: str) -> List[ExtractedFact]:
        """Parse Kubernetes YAML manifests and extract component facts."""
        facts = []
        try:
            docs = yaml.safe_load_all(content)
            for doc in docs:
                if not isinstance(doc, dict):
                    continue

                kind = doc.get("kind")
                if kind in ["Deployment", "StatefulSet", "DaemonSet", "Pod"]:
                    metadata = doc.get("metadata", {})
                    name = metadata.get("name")
                    spec = doc.get("spec", {})

                    # Deployments/StatefulSets nest the pod spec under template.spec
                    if kind != "Pod":
                        spec = spec.get("template", {}).get("spec", {})

                    containers = spec.get("containers", [])
                    for container in containers:
                        image = container.get("image")
                        ports = []
                        for p in container.get("ports", []):
                            if "containerPort" in p:
                                ports.append(int(p["containerPort"]))

                        envs = []
                        env_values = {}
                        for e in container.get("env", []):
                            if not isinstance(e, dict) or "name" not in e:
                                continue
                            k = e["name"]
                            envs.append(k)
                            # Skip valueFrom refs (ConfigMap/Secret) — no literal value available
                            if "value" in e and isinstance(e["value"], str):
                                env_values[k] = e["value"]

                        # Resolve K8s $(VAR_NAME) env var references before inference
                        for k in list(env_values.keys()):
                            v = env_values[k]
                            if isinstance(v, str) and "$(" in v:
                                env_values[k] = re.sub(
                                    r"\$\(([^)]+)\)",
                                    lambda m: env_values.get(m.group(1), m.group(0)),
                                    v
                                )

                        connects_to = _infer_connects_to(env_values)

                        facts.append(ExtractedFact(
                            name=name,
                            source_type=kind,
                            technology="kubernetes",
                            image=image,
                            ports=ports,
                            envs=envs,
                            env_values=env_values,
                            inferred_connects_to=connects_to,
                        ))

                elif kind == "Service":
                    metadata = doc.get("metadata", {})
                    name = metadata.get("name")
                    spec = doc.get("spec", {})
                    ports = []
                    for p in spec.get("ports", []):
                        if "port" in p:
                            ports.append(int(p["port"]))

                    # Services have no image but map to EDMM components
                    facts.append(ExtractedFact(
                        name=name,
                        source_type="Service",
                        technology="kubernetes",
                        ports=ports,
                    ))

        except Exception as e:
            print(f"Error parsing K8s YAML: {e}")
        return facts
    
    def _extract_terraform(self, content: str) -> List[ExtractedFact]:
        """Parse Terraform HCL and extract docker_container resource facts."""
        facts = []
        # Match top-level docker_container resource blocks
        resource_pattern = re.compile(
            r'resource\s+"docker_container"\s+"([^"]+)"\s+\{(.*?)\n\}', re.DOTALL
        )

        matches = resource_pattern.findall(content)
        for res_name, block_content in matches:
            name_match = re.search(r'name\s*=\s*"([^"]+)"', block_content)
            name = name_match.group(1) if name_match else res_name

            image_match = re.search(r'image\s*=\s*"([^"]+)"', block_content)
            image = image_match.group(1) if image_match else None

            # Extract internal port numbers from: ports { internal = N }
            ports = []
            for pm in re.finditer(r'ports\s*\{[^}]*internal\s*=\s*(\d+)', block_content):
                ports.append(int(pm.group(1)))

            # Extract env vars from: env = ["KEY=VALUE", ...]
            envs = []
            env_values = {}
            env_block_match = re.search(r'env\s*=\s*\[(.*?)\]', block_content, re.DOTALL)
            if env_block_match:
                env_content = env_block_match.group(1)
                for m in re.finditer(r'"([^"=]+)=([^"]*)"', env_content):
                    k, v = m.group(1), m.group(2)
                    envs.append(k)
                    env_values[k] = v

            connects_to = _infer_connects_to(env_values)

            facts.append(ExtractedFact(
                name=name,
                source_type="docker_container",
                technology="terraform",
                image=image,
                ports=ports,
                envs=envs,
                env_values=env_values,
                inferred_connects_to=connects_to,
            ))

        return facts

    def _is_ansible_playbook(self, content: str) -> bool:
        """Heuristic: a playbook is a list of dicts that each have a 'hosts' key."""
        try:
            data = yaml.safe_load(content)
            if isinstance(data, list) and len(data) > 0 and 'hosts' in data[0]:
                return True
        except Exception:
            pass
        return False

    def _extract_ansible(self, content: str, base_dir: Path) -> List[ExtractedFact]:
        """Parse an Ansible playbook and resolve role task files for facts."""
        facts = []
        try:
            plays = yaml.safe_load(content)
            for play in plays:
                roles = play.get("roles", [])
                for role in roles:
                    role_name = role if isinstance(role, str) else role.get("role")
                    if not role_name:
                        continue

                    # Try both .yml and .yaml extensions for the role task file
                    role_path = base_dir / "roles" / role_name / "tasks" / "main.yml"
                    if not role_path.exists():
                        role_path = base_dir / "roles" / role_name / "tasks" / "main.yaml"

                    if role_path.exists():
                        facts.extend(self._parse_ansible_role(role_path, role_name))
                    else:
                        # Role file not found — record the role name as a minimal fact
                        facts.append(ExtractedFact(
                            name=role_name,
                            source_type="ansible_role",
                            technology="ansible",
                        ))
        except Exception as e:
            print(f"Error parsing Ansible: {e}")
        return facts

    def _parse_ansible_role(self, role_path: Path, role_name: str) -> List[ExtractedFact]:
        """
        Extract facts from an Ansible role task file.
        Looks for community.docker.docker_container or docker_container tasks.
        """
        content = role_path.read_text(encoding='utf-8', errors='ignore')
        facts = []
        try:
            tasks = yaml.safe_load(content)
            if not tasks:
                return []

            for task in tasks:
                docker_mod = (
                    task.get("community.docker.docker_container")
                    or task.get("docker_container")
                )
                if not docker_mod:
                    continue

                name = docker_mod.get("name", role_name)
                image = docker_mod.get("image")

                # Ansible ports can be strings like "80:80" or bare integers
                ports = []
                for p in docker_mod.get("ports", []):
                    if isinstance(p, str):
                        ports.append(int(p.split(":")[-1]) if ":" in p else int(p))
                    elif isinstance(p, int):
                        ports.append(p)

                env = docker_mod.get("env", {}) or {}
                envs = list(env.keys())
                # Only keep string values; Jinja2 templates cannot be resolved here
                env_values = {k: str(v) for k, v in env.items() if isinstance(v, str)}

                connects_to = _infer_connects_to(env_values)

                facts.append(ExtractedFact(
                    name=name,
                    source_type="ansible_task",
                    technology="ansible",
                    image=image,
                    ports=ports,
                    envs=envs,
                    env_values=env_values,
                    inferred_connects_to=connects_to,
                ))
        except Exception:
            pass

        if not facts:
            # Fallback: at least record that the role exists
            facts.append(ExtractedFact(
                name=role_name,
                source_type="ansible_role",
                technology="ansible",
            ))
        return facts


if __name__ == "__main__":
    import sys
    extractor = FactExtractor()
    if len(sys.argv) > 1:
        fpath = sys.argv[1]
        print(f"Extracting from {fpath}...")
        results = extractor.extract(fpath)
        for r in results:
            print(json.dumps(r.to_dict(), indent=2))