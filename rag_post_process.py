import yaml
import re
from collections import Counter

# --- Configuration & Constants ---
FORBIDDEN = ("configmap", "clusterrole", "rolebinding", "serviceaccount", "secret", "test", "pod", "job")
UPPER_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
KEY_REGEX = re.compile(r"^[A-Za-z0-9_.-]+$")
FORBIDDEN_KEYS = ("apiVersion", "kind", "metadata", "status", "spec", "selector", "template")

_RELATION_TYPE_NORMALIZE = {
    "hostedOn": "HostedOn", "hostedon": "HostedOn",
    "connectsTo": "ConnectsTo", "connectsto": "ConnectsTo",
    "attachesTo": "AttachesTo", "attachesto": "AttachesTo",
    "dependsOn": "DependsOn", "dependson": "DependsOn",
}
_CLOUD_CLUSTER_TYPES = (
    "azurerm_kubernetes_cluster", "aws_eks_cluster",
    "google_container_cluster", "oci_containerengine_cluster",
    "digitalocean_kubernetes_cluster",
)



from typing import Dict, List, Any, Optional, Union

def lom_to_dict(lst: Union[List[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    """Converts a List of Maps into a standard Dictionary.
    Handles two formats:
    1. Old Structure: [{"compName": {"type": "..."}}] -> {"compName": {"type": "..."}}
    2. New Structure: [{"name": "compName", "type": "..."}] -> {"compName": {"type": "..."}}
    """
    if isinstance(lst, dict):
        # If it's already a dictionary but contains "name" as a key, handle it
        if "name" in lst and "type" in lst:
            name = lst.pop("name")
            return {name: lst}
        return lst
        
    out = {}
    
    def merge_component_body(existing: Dict[str, Any], new_body: Dict[str, Any]) -> Dict[str, Any]:
        # Merge type (prefer non-empty and non-default)
        if new_body.get("type") and (not existing.get("type") or existing.get("type") == "SoftwareApplication"):
            existing["type"] = new_body["type"]
            
        # Helper to merge lists safely
        def merge_lists(key):
            e_list = existing.get(key, [])
            n_list = new_body.get(key, [])
            if not isinstance(e_list, list): e_list = []
            if not isinstance(n_list, list): n_list = []
            
            # Simple list deduplication (preserves order)
            merged = e_list + n_list
            seen = []
            res = []
            for i in merged:
                if i not in seen:
                    seen.append(i)
                    res.append(i)
            existing[key] = res

        merge_lists("properties")
        merge_lists("operations")
        merge_lists("artifacts")
        return existing

    for item in lst or []:
        if isinstance(item, dict):
            # Check for New Structure: {name: "database", type: "db", ...}
            if "name" in item:
                # Copy the item to avoid mutating the original
                body = dict(item)
                name_key = body.pop("name")
                if name_key in out:
                    out[name_key] = merge_component_body(out[name_key], body)
                else:
                    out[name_key] = body
            # Handle Old Structure: {"database": {type: "db", ...}}
            else:
                for k, v in item.items():
                    if k in out and isinstance(v, dict):
                        out[k] = merge_component_body(out[k], v)
                    else:
                        out[k] = v
    return out

def dict_to_lom(d):
    """{k: v} -> [{k: v}] (sorted by key)
    If values are complex (like component bodies), keep them intact.
    """
    if isinstance(d, list):
        return d
    return [{k: d[k]} for k in sorted(d.keys())]

def props_lom_to_dict(props):
    """Safely convert properties list-of-maps OR direct dict to a flat dict"""
    if isinstance(props, dict):
        return props.copy()
    d = {}
    for item in props or []:
        if isinstance(item, dict):
            for k, v in item.items():
                d[k] = v
    return d

def props_dict_to_lom(d):
    if isinstance(d, list):
        return d
    return [{k: d[k]} for k in sorted(d.keys())]

def guess_prefix(names):
    # candidate: first two dash-separated tokens
    cands = []
    for n in names:
        parts = n.split("-")
        if len(parts) >= 3:
            cands.append("-".join(parts[:2]) + "-")
    if not cands:
        return None
    try:
        pref, cnt = Counter(cands).most_common(1)[0]
        # require that it actually prefixes multiple names
        if sum(1 for n in names if n.startswith(pref)) >= 3:
            return pref
    except:
        pass
    return None

def _derive_type_from_image(image: str, comp_name: str) -> str:
    """Derive semantic EDMM type from a Docker image string."""
    img = image.lower().split(":")[0]  # strip tag
    last = img.split("/")[-1]          # last path segment

    DB_KEYWORDS = ("postgres", "mysql", "mariadb", "mongo", "redis", "valkey",
                   "cassandra", "elasticsearch", "opensearch", "mssql", "oracle",
                   "influxdb", "cockroach", "clickhouse")
    MB_KEYWORDS = ("kafka", "rabbitmq", "activemq", "nats", "pulsar", "zookeeper")

    if any(k in last for k in DB_KEYWORDS):
        return f"{last}-DatabaseSystem"
    if any(k in last for k in MB_KEYWORDS):
        return f"{last}-MessageBroker"
        
    # Fallback to comp_name if the parsed image segment is a generic monorepo name
    if last in ("demo", "app", "service", "microservice"):
        return f"{comp_name}-SoftwareApplication"
        
    # Fall back to parsed image segment normally
    return f"{last}-SoftwareApplication"

def fix_component_type(comp_name: str, type_name: Optional[str]) -> str:
    short = comp_name.lower()
    # Basic fallbacks if not set
    if not type_name or type_name == "None":
        return f"{comp_name}-SoftwareApplication"

    return type_name

def resolve_placeholders(val, props_dict):
    if not isinstance(val, str):
        return val
    # $(VAR) replacement if VAR exists
    def repl(m):
        var = m.group(1)
        if var in props_dict and props_dict[var] not in (None, ""):
            return str(props_dict[var])
        return m.group(0)

    out = re.sub(r"\$\(([^)]+)\)", repl, val)
    out = out.replace("http://*:", "http://:")  # normalize K8s wildcard host format
    return out

def normalize_ports(props):
    # containerPort_* must be int; exposedPort_* must be "a:b"
    # special: grafana service 80 -> 3000 if containerPort_grafana exists
    if "exposedPort_service" in props:
        v = props["exposedPort_service"]
        # If it's just '80', try to find target port
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            svc_port = int(v)
            cps = [props[k] for k in props if k.startswith("containerPort_")]
            target = cps[0] if cps else svc_port
            props["exposedPort_service"] = f"{svc_port}:{int(target)}"

    for k in list(props.keys()):
        v = props[k]
        if k.startswith("containerPort_"):
            if isinstance(v, str) and v.isdigit():
                props[k] = int(v)
        if k.startswith("exposedPort_"):
            if isinstance(v, int):
                props[k] = f"{v}:{v}"
            elif isinstance(v, str) and v.isdigit():
                props[k] = f"{v}:{v}"
    return props

def normalize_property_keys(props):
    new = {}
    for k, v in props.items():
        # drop extras later via allowlist
        nk = k
        if nk.startswith("env_var_"):
            nk = nk[len("env_var_"):]
        if nk.startswith("env_"):
            nk = nk[len("env_"):]
        # (no domain-specific key renaming — keep LLM output as-is)
        new[nk] = v
    return new

def filter_properties(props):
    keep = {}
    for k, v in props.items():
        # Keep all properties without filtering by infrastructure blacklists

        # Force k to be a string for string methods
        k_str = str(k)
        
        # Filter strictly forbidden keys (k8s metadata leaking)
        if k_str in FORBIDDEN_KEYS:
            continue

        # Always keep port keys
        if k_str.startswith("containerPort_") or k_str.startswith("exposedPort_"):
            keep[k] = v
            continue
            
        # Allow Upper Case Env Vars
        if UPPER_ENV_RE.match(k):
            keep[k] = v
            continue
            
        # Allow standard identifier keys (for Ansible/Terraform compatibility)
        # e.g. "instance_type", "ami", "hosts", "vpc_id", "ansible_connection"
        if KEY_REGEX.match(k):
            keep[k] = v
            continue
            
    return keep

# SANITIZATION FIXES

def fix_infra_as_source(comps: dict, rels: dict) -> None:
    """
    Infrastructure platform nodes (clusters, cloud providers, docker engines) 
    cannot be ConnectsTo relation sources. They can be HostedOn sources 
    (e.g. cluster_HostedOn_CloudProvider is valid). Any invalid ConnectsTo 
    from an infrastructure node is deleted.
    """
    INFRA_TYPE_KEYWORDS = (
        "kubernetescluster", "defaultkubernetescluster",
        "cloudprovider", "dockerengine", "containerplatform",
        "azurerm_kubernetes_cluster", "aws_eks_cluster",
        "google_container_cluster",
    )
    infra_names = {
        cname for cname, cbody in comps.items()
        if any(kw in (cbody or {}).get("type", "").lower()
               for kw in INFRA_TYPE_KEYWORDS)
    }
    to_remove = [
        k for k, v in rels.items()
        if v.get("source") in infra_names
        and v.get("type", "").lower() == "connectsto"
    ]
    for k in to_remove:
        v = rels[k]
        print(f"🔧 [SANITIZE] Removing invalid relation "
              f"(infra node as source): "
              f"{v.get('source')} → {v.get('type')} → {v.get('target')}", flush=True)
        del rels[k]


def fix_cluster_redirect(comps: dict, rels_new: dict) -> None:
    """If both a real TF cluster AND defaultKubernetesCluster exist, 
    redirect all relations to the real cluster and remove the dummy."""
    
    MANAGED_CLUSTER_TYPES = (
        "azurerm_kubernetes_cluster",
        "aws_eks_cluster", 
        "google_container_cluster",
        "oci_containerengine_cluster",
        "digitalocean_kubernetes_cluster",
    )
    
    real_clusters = [
        name for name, body in comps.items()
        if isinstance(body, dict) 
        and body.get("type", "").lower() in [t.lower() for t in MANAGED_CLUSTER_TYPES]
    ]
    
    if real_clusters and "defaultKubernetesCluster" in comps:
        target_cluster = real_clusters[0]
        print(f"🔧 [SANITIZE] Redirecting defaultKubernetesCluster → {target_cluster}", flush=True)
        
        for k, v in rels_new.items():
            if v.get("target") == "defaultKubernetesCluster":
                v["target"] = target_cluster
            if v.get("source") == "defaultKubernetesCluster":
                v["source"] = target_cluster
        
        del comps["defaultKubernetesCluster"]


def fix_strip_infra_imagepullpolicy(comps: dict) -> None:
    """Remove imagePullPolicy from infrastructure components that are not container workloads."""
    
    INFRA_TYPE_KEYWORDS = (
        "cloudprovider", "kubernetescluster", "defaultkubernetescluster",
        "containerplatform", "dockerengine", "storage",
        "azurerm_kubernetes_cluster", "aws_eks_cluster", 
        "google_container_cluster",
    )
    
    for name, body in comps.items():
        if not isinstance(body, dict):
            continue
        comp_type = (body.get("type", "") or "").lower()
        
        if any(kw in comp_type for kw in INFRA_TYPE_KEYWORDS):
            props = body.get("properties", [])
            if isinstance(props, list):
                body["properties"] = [
                    p for p in props 
                    if not (isinstance(p, dict) and "imagePullPolicy" in p)
                ]
            elif isinstance(props, dict) and "imagePullPolicy" in props:
                del props["imagePullPolicy"]


def fix_clean_empty_artifacts(comps: dict) -> None:
    """Remove artifacts with empty/none name or fileURI."""
    
    for name, body in comps.items():
        if not isinstance(body, dict):
            continue
        arts = body.get("artifacts", [])
        if not isinstance(arts, list):
            continue
        
        cleaned = []
        for art in arts:
            if not isinstance(art, dict):
                cleaned.append(art)
                continue
            
            # Check if artifact content is empty/none
            is_empty = False
            for art_type, art_body in art.items():
                if isinstance(art_body, dict):
                    name_val = str(art_body.get("name", "")).strip().lower()
                    uri_val = str(art_body.get("fileURI", "")).strip().lower()
                    if name_val in ("", "none", "null") and uri_val in ("", "none", "null"):
                        is_empty = True
                        break
            
            if not is_empty:
                cleaned.append(art)
        
        body["artifacts"] = cleaned


def fix_nonsensical_connectsto(comps: dict, rels_new: dict) -> None:
    """Remove ConnectsTo relations targeting infrastructure components."""
    
    INFRA_TYPE_KEYWORDS = (
        "cloudprovider", "kubernetescluster", "defaultkubernetescluster",
        "containerplatform", "dockerengine", "storage",
        "azurerm_kubernetes_cluster", "aws_eks_cluster",
        "google_container_cluster",
    )
    
    # Build set of infra component names
    infra_names = set()
    for cname, cbody in comps.items():
        if not isinstance(cbody, dict):
            continue
        comp_type = (cbody.get("type", "") or "").lower()
        if any(kw in comp_type for kw in INFRA_TYPE_KEYWORDS):
            infra_names.add(cname)
    
    # Remove ConnectsTo relations where target is infra
    keys_to_remove = []
    for k, v in rels_new.items():
        if (v.get("type", "").lower() == "connectsto" 
                and v.get("target", "") in infra_names):
            print(f"🔧 [SANITIZE] Removing nonsensical ConnectsTo: "
                  f"{v.get('source')} → {v.get('target')}", flush=True)
            keys_to_remove.append(k)
    
    for k in keys_to_remove:
        del rels_new[k]


def fix_self_reference_relations(rels: dict) -> None:
    """Remove relations where source == target (nonsensical self-loops)."""
    keys_to_remove = [
        k for k, v in rels.items()
        if v.get("source") == v.get("target")
    ]
    for k in keys_to_remove:
        v = rels[k]
        print(f"🔧 [SANITIZE] Removing self-reference: "
              f"{v.get('source')} → {v.get('type')} → {v.get('target')}", flush=True)
        del rels[k]

def fix_ansible_operation_order(comps: dict, platform: str) -> None:
    """Ensure Pull operations come before Deploy operations in Ansible."""
    
    if "ansible" not in platform.lower():
        return
    
    for name, body in comps.items():
        if not isinstance(body, dict) or name == "localhost":
            continue
        
        ops = body.get("operations", [])
        if not isinstance(ops, list) or len(ops) != 2:
            continue
        
        # Get operation names
        op_names = []
        for op in ops:
            if isinstance(op, dict):
                op_names.append(list(op.keys())[0] if op else "")
        
        if len(op_names) == 2:
            # If Deploy comes before Pull, swap them
            if ("deploy" in op_names[0].lower() or "run" in op_names[0].lower()) \
               and ("pull" in op_names[1].lower()):
                body["operations"] = [ops[1], ops[0]]
                print(f"🔧 [SANITIZE] Swapped operation order for {name}: "
                      f"Pull before Deploy", flush=True)

def fix_attachesto_direction(comps: dict, rels: dict) -> None:
    """
    By EDMM abstract_relations definition, in an AttachesTo relation,
    the source is always a Storage/volume component, and the target is a service component.
    This function corrects relations generated in the reverse direction.
    """
    storage_names = {
        cname for cname, cbody in comps.items()
        if isinstance(cbody, dict) and 
        (cbody.get("type", "").lower() == "storage" or
         "volume" in cname.lower())
    }
    
    for k, v in list(rels.items()):
        if v.get("type", "").lower() != "attachesto":
            continue
        src = v.get("source", "")
        tgt = v.get("target", "")
        
        if src not in storage_names and tgt in storage_names:
            v["source"] = tgt
            v["target"] = src
            new_key = f"{tgt}_AttachesTo_{src}"
            rels[new_key] = v
            del rels[k]
            print(f"🔧 [SANITIZE] Fixed AttachesTo direction: "
                  f"{src} → {tgt} corrected to {tgt} → {src}", flush=True)

def fix_relation_type_casing(rels: dict) -> None:
    """Normalize relation type values to PascalCase."""
    for rel in rels.values():
        t = rel.get("type", "")
        rel["type"] = _RELATION_TYPE_NORMALIZE.get(t, t)



def sort_edmm_recursively(data):
    """
    Sorts dictionaries and lists of dictionaries recursively to ensure deterministic output.
    """
    if isinstance(data, dict):
        return {k: sort_edmm_recursively(v) for k, v in sorted(data.items())}
    if isinstance(data, list):
        sorted_list = [sort_edmm_recursively(x) for x in data]
        try:
            sorted_list.sort(key=lambda x: str(next(iter(x))) if isinstance(x, dict) and x else str(x))
        except:
            pass 
        return sorted_list
    return data

def post_process_edmm(edmm: dict, platform: str = "", strict_integrity: bool = True) -> dict:
    if not isinstance(edmm, dict): return {}
    
    # ensure top-level keys
    edmm.setdefault("properties", [])
    edmm.setdefault("component_types", [])
    edmm.setdefault("relation_types", [])
    edmm.setdefault("components", [])
    edmm.setdefault("relations", [])

    comps = lom_to_dict(edmm["components"])
    rels = lom_to_dict(edmm["relations"])
    
    # drop forbidden components early
    for name in list(comps.keys()):
        body = comps[name] or {}
        t = str(body.get("type","")).lower()
        if any(x in name.lower() for x in FORBIDDEN):
            del comps[name]
        elif t and any(x in t for x in FORBIDDEN):
            del comps[name]
        
        # Clean up imagePullPolicy from generic Cluster components
        if "cluster" in t:
            props = body.get("properties", {})
            if isinstance(props, dict) and "imagePullPolicy" in props:
                del props["imagePullPolicy"]
            elif isinstance(props, list):
                # If properties is a list of dicts or strings
                body["properties"] = [p for p in props if not (isinstance(p, dict) and "imagePullPolicy" in p)]

        # Ensure 'Pull' operation comes before 'Deploy' operation (especially for Ansible)
        ops = body.get("operations", [])
        if isinstance(ops, list) and len(ops) == 2:
            op_names = [list(o.keys())[0] if isinstance(o, dict) and o else "" for o in ops]
            if "Deploy" in op_names[0] and "Pull" in op_names[1]:
                body["operations"] = [ops[1], ops[0]]  # swap

    # Detect if this is a Kubernetes deployment.
    # We now use the explicit platform parameter passed from ui.py/rag.py,
    # which is 100% reliable. Previously we tried to guess from component
    # content but the LLM rarely generates defaultKubernetesCluster as a
    # component, causing the detection to silently fail and prefix-stripping
    # to run, renaming e.g. 'opentelemetry-demo-cartservice' -> 'cartservice'.
    _k8s_types = ("defaultkubernetescluster", "kubernetescluster", "containerplatform")
    _ct_raw = lom_to_dict(edmm.get("component_types", []))
    is_kubernetes_output = (
        "kubernetes" in (platform or "").lower()
    )
    if is_kubernetes_output:
        print(f"🔵 Kubernetes platform detected (platform='{platform}'): skipping prefix/kebab merging", flush=True)

    # merge prefixed/unprefixed duplicates
    # ONLY for non-Kubernetes platforms (Ansible/Terraform).
    # Kubernetes names like 'opentelemetry-demo-cartservice' must be preserved as-is.
    if not is_kubernetes_output:
        names = list(comps.keys())
        svc_names = [n for n in names if n != "defaultKubernetesCluster"]
        pref = guess_prefix(svc_names)
        
        if pref:
            grouped = {}
            for n in list(comps.keys()):
                if n == "defaultKubernetesCluster":
                    grouped.setdefault(n, []).append(n)
                    continue
                short = n[len(pref):] if n.startswith(pref) else n
                grouped.setdefault(short, []).append(n)

            merged_comps = {}
            for short, variants in grouped.items():
                if short == "defaultKubernetesCluster":
                    merged_comps["defaultKubernetesCluster"] = comps["defaultKubernetesCluster"]
                    continue
                
                canonical = pref + short
                if canonical not in variants:
                    canonical = variants[0]
                
                base = comps.get(canonical) or {}
                if not isinstance(base, dict): base = {}

                for vname in variants:
                    if vname == canonical: 
                        continue
                    other = comps.get(vname) or {}
                    if not isinstance(other, dict): continue
                    
                    base.setdefault("properties", {})
                    base.setdefault("artifacts", [])
                    base.setdefault("operations", [])
                    
                    if other.get("properties"):
                        p_other = other["properties"]
                        if isinstance(base["properties"], list):
                             if not base["properties"]: 
                                 base["properties"] = {}
                             else:
                                 base["properties"] = props_lom_to_dict(base["properties"])

                        if isinstance(p_other, list):
                            p_other = props_lom_to_dict(p_other)

                        if isinstance(base["properties"], dict) and isinstance(p_other, dict):
                            base["properties"].update(p_other)

                    if other.get("artifacts"):
                        base["artifacts"] += other["artifacts"]
                    if other.get("operations"):
                        base["operations"] += other["operations"]
                        
                merged_comps[canonical] = base
            comps = merged_comps

    # Generic kebab-case → camelCase duplicate merger
    # e.g. "ad-service" merged into "adservice" if both exist
    # ONLY for non-Kubernetes platforms. On Kubernetes, names like
    # 'opentelemetry-demo-cartservice' must NOT have dashes stripped.
    if not is_kubernetes_output:
        for name in list(comps.keys()):
            if "-" not in name:
                continue
            camel = name.replace("-", "")
            if camel in comps and camel != name:
                base = comps[camel] or {}
                other = comps[name] or {}
                if not isinstance(base, dict): base = {}
                if not isinstance(other, dict): other = {}
                base_type = base.get("type", "") or ""
                other_type = other.get("type", "") or ""
                if base_type.lower() in ("", "none", "unknown") and other_type.lower() not in ("", "none", "unknown"):
                    base["type"] = other_type
                p_base = props_lom_to_dict(base.get("properties", []))
                p_other = props_lom_to_dict(other.get("properties", []))
                p_base.update({k: v for k, v in p_other.items() if k not in p_base})
                base["properties"] = p_base
                base.setdefault("artifacts", [])
                for art in (other.get("artifacts") or []):
                    if art not in base["artifacts"]:
                        base["artifacts"].append(art)
                comps[camel] = base
                del comps[name]
                print(f"🔧 Merged kebab '{name}' → camelCase '{camel}'", flush=True)

    # normalize components
    for name, body in list(comps.items()):
        # FIX: Skip None or empty components
        if not body or not isinstance(body, dict):
            print(f"⚠️  Skipping invalid component '{name}': {type(body)}", flush=True)
            del comps[name]
            continue
            
        body.setdefault("description", None)
        body.setdefault("operations", [])
        body.setdefault("artifacts", [])
        body.setdefault("properties", [])

        # Terraform Docker: docker_container is not a semantic type — derive from image
        if body.get("type") in ("docker_container", "DockerContainer"):
            props_d = props_lom_to_dict(body.get("properties", []))
            image = str(props_d.get("image", ""))
            if image:
                body["type"] = _derive_type_from_image(image, name)
            else:
                body["type"] = f"{name}-SoftwareApplication"

        # fix type using outer key
        body["type"] = fix_component_type(name, body.get("type"))

        # properties: LOM -> dict -> normalize -> dict_to_LOM
        pd = props_lom_to_dict(body["properties"])
        pd = normalize_property_keys(pd)

        # placeholder resolution
        for pk in list(pd.keys()):
            pd[pk] = resolve_placeholders(pd[pk], pd)

        # type conversions: non-port values become strings (expected)
        for pk in list(pd.keys()):
            if pk.startswith("containerPort_"):
                # keep int
                if isinstance(pd[pk], str) and pd[pk].isdigit():
                    pd[pk] = int(pd[pk])
            elif pk.startswith("exposedPort_"):
                # handled by normalize_ports
                pass
            else:
                if isinstance(pd[pk], int):
                    pd[pk] = str(pd[pk])

        pd = normalize_ports(pd)
        pd = filter_properties(pd)

        body["properties"] = pd  # Keep as dict, not list
        
        # FIX: Filter generic placeholder components
        # 1. Matches generic "component1", "host1"
        # 2. Matches NUMBERED localhost variants (localhost1, localhost99) but NOT plain "localhost"
        # 3. Matches template variables like <deployment_name> or {{ value }}
        if (re.match(r'^component\d+$', name) or 
            re.match(r'^host\d+$', name) or 
            re.match(r'^localhost\d+$', name) or  # FIXED: Only numbered localhost, not plain "localhost"
            name.startswith('<') or
            name.endswith(('.yaml', '.yml', '.json', '.conf', '.cfg', '.ini', '.xml', '.toml')) or
            name in ['kubernetes', 'logging', 'servicemonitor', 'container']):
            
            print(f"⚠️  Skipping specific placeholder/noise component '{name}'", flush=True)
            del comps[name]
            continue

        comps[name] = body

    
    if is_kubernetes_output:
        svc_names = [n for n in comps if n != "defaultKubernetesCluster"]
        helm_prefix = guess_prefix(svc_names)  # e.g. "opentelemetry-demo-"
        
        if helm_prefix:
            print(f"🔵 K8s: stripping Helm prefix '{helm_prefix}' from type names", flush=True)
            
            # 1. Fix the `type` field inside each component instance
            for body in comps.values():
                if not isinstance(body, dict):
                    continue
                t = body.get("type", "")
                if isinstance(t, str) and t.startswith(helm_prefix):
                    body["type"] = t[len(helm_prefix):]
            
            # 2. Rename component_types keys and fix their `extends` fields
            ct_raw = lom_to_dict(edmm.get("component_types", []))
            new_ct_lom = []
            for ct_name, ct_body in ct_raw.items():
                new_name = ct_name[len(helm_prefix):] if ct_name.startswith(helm_prefix) else ct_name
                if isinstance(ct_body, dict):
                    ext = ct_body.get("extends", "")
                    if isinstance(ext, str) and ext.startswith(helm_prefix):
                        ct_body = dict(ct_body)
                        ct_body["extends"] = ext[len(helm_prefix):]
                new_ct_lom.append({new_name: ct_body})
            edmm["component_types"] = new_ct_lom

    # relation_types: enforce expected set based on platform
    is_ansible = "ansible" in platform.lower()
    edmm["relation_types"] = [
        {"AttachesTo": {"extends": "DependsOn", "description": None, "properties": [{"location": {"type": "STRING", "required": True, "default_value": ""}}], "operations": []}},
        {"ConnectsTo": {"extends": "DependsOn", "description": None, "properties": [], "operations": []}},
        {"DependsOn": {"extends": "-", "description": None, "properties": [], "operations": []}},
        {"HostedOn": {"extends": "DependsOn", "description": None, "properties": [], "operations": []}},
    ]

    # rebuild relations: keep existing valid relations — deduplicate by (source, target, type)
    # Also enforce referential integrity: skip relations whose source/target aren't known components
    comp_names_set = set(comps.keys())
    rels_new = {}
    seen_rel_tuples = set()  # (source, target, type)
    valid_rt = [rt.lower() for rt in ("HostedOn", "ConnectsTo", "AttachesTo", "DependsOn")]

    for k, v in rels.items():
        if isinstance(v, dict):
            rtype = str(v.get("type", ""))
            if rtype.lower() in valid_rt:
                src = str(v.get("source", ""))
                tgt = str(v.get("target", ""))
                
                rtype = rtype[:1].upper() + rtype[1:]
                v["type"] = rtype

                # Referential integrity: skip phantom components not in component list
                if strict_integrity:
                    if src not in comp_names_set:
                        print(f"  [PHANTOM] Dropping relation {k}: source '{src}' not in components", flush=True)
                        continue
                    if tgt not in comp_names_set:
                        print(f"  [PHANTOM] Dropping relation {k}: target '{tgt}' not in components", flush=True)
                        continue
                key = (src, tgt, rtype)
                if key not in seen_rel_tuples:
                    seen_rel_tuples.add(key)
                    
                    v.setdefault("description", None)
                    v.setdefault("properties", [])
                    v.setdefault("operations", [])
                    v.setdefault("operations", [])
                    
                    rels_new[k] = v

    comp_names = list(comps.keys())
    
   
    # Dynamic Host Detection
    
    target_host = None
    for cname, cbody in comps.items():
        ctype = (cbody or {}).get("type", "").lower()
        if "cluster" in ctype or cname.lower() == "localhost" or "compute" in ctype:
            target_host = cname
            break

    cloud_providers = [cname for cname, cbody in comps.items() if cbody.get("type", "").lower() == "cloudprovider"]


    # component_types: base + per-service (simple generate)
    base_types = {
        "BaseType": {"extends": "-", "description": None, "properties": [], "operations": []},
        "ContainerPlatform": {"extends": "BaseType", "description": None, "properties": [], "operations": []},
        "DockerEngine": {"extends": "ContainerPlatform", "description": None, "properties": [], "operations": []},
        "DefaultDockerEngine": {"extends": "DockerEngine", "description": None, "properties": [], "operations": []},
        "KubernetesCluster": {"extends": "ContainerPlatform", "description": None, "properties": [], "operations": []},
        "SoftwareApplication": {"extends": "BaseType", "description": None, "properties": [], "operations": []},
        "DatabaseSystem": {"extends": "SoftwareApplication", "description": None, "properties": [], "operations": []},
        "MessageBroker": {"extends": "SoftwareApplication", "description": None, "properties": [], "operations": []}
    }
    
    # Only add DefaultKubernetesCluster to base types if the LLM explicitly created it
    if "defaultKubernetesCluster" in comps:
        base_types["DefaultKubernetesCluster"] = {"extends": "KubernetesCluster", "description": None, "properties": [], "operations": []}

    # rebuild component_types from components (only referenced types)
    type_defs = dict(base_types)
    
    # 1. Collect all properties for each type
    type_props = {}
    for cname, body in comps.items():
        tname = body.get("type", "SoftwareApplication")
        if not tname: continue
        
        pd = props_lom_to_dict(body.get("properties", []))
        if tname not in type_props:
            type_props[tname] = {}
        
        # Merge properties (latest wins strategy is fine for schema generation)
        type_props[tname].update(pd)

    # 2. Build Type Definitions
    for tname, all_props in type_props.items():
        if tname in type_defs:
            # Updating base types is risky, skip unless custom logic needed
            continue
            
        # EDMM Schema Rules: extends heuristics
        ext = "SoftwareApplication"
        if "DatabaseSystem" in str(tname):
            ext = "DatabaseSystem"
        elif "MessageBroker" in str(tname):
            ext = "MessageBroker"
        elif "Storage" == str(tname):
            ext = "BaseType"
        elif tname == "CloudProvider":
            ext = "BaseType"
        elif any(x in str(tname) for x in _CLOUD_CLUSTER_TYPES):
            # e.g. azurerm_kubernetes_cluster, aws_eks_cluster, google_container_cluster
            ext = "KubernetesCluster"

        props_meta = {}
        for pk, pv in all_props.items():
            if pk.startswith("containerPort_"):
                props_meta[pk] = {"type": "INTEGER", "required": True, "default_value": int(pv)}
            elif pk.startswith("exposedPort_"):
                props_meta[pk] = {"type": "STRING", "required": True, "default_value": str(pv)}
            elif pk == "imagePullPolicy":
                # Optional — Kubernetes has a built-in default (IfNotPresent)
                props_meta[pk] = {"type": "STRING", "required": False, "default_value": str(pv)}
            elif pk == "storage_size":
                props_meta[pk] = {"type": "STRING", "required": True, "default_value": str(pv)}
            else:
                val = pv
                if isinstance(val, bool): val = str(val).lower()
                # All other properties (env vars, config keys) are required — app needs them
                props_meta[pk] = {"type": "STRING", "required": True, "default_value": str(val)}
        
        # Convert to List of Maps (sorted)
        props_list = [{k: v} for k, v in sorted(props_meta.items())]
        type_defs[tname] = {"extends": ext, "description": None, "properties": props_list, "operations": []}

    # Convert component properties/operations/artifacts from dict to List of Maps (sorted)
    for cname, body in comps.items():
        if "properties" in body and isinstance(body["properties"], dict):
            body["properties"] = props_dict_to_lom(body["properties"])
        if "operations" in body and isinstance(body["operations"], dict):
            body["operations"] = props_dict_to_lom(body["operations"])
        if "artifacts" in body and isinstance(body["artifacts"], dict):
            body["artifacts"] = props_dict_to_lom(body["artifacts"])

    # --- Sanitization Fixes ---
    fix_infra_as_source(comps, rels_new)
    fix_cluster_redirect(comps, rels_new)
    fix_strip_infra_imagepullpolicy(comps)
    fix_clean_empty_artifacts(comps)
    fix_nonsensical_connectsto(comps, rels_new)
    fix_self_reference_relations(rels_new)
    fix_attachesto_direction(comps, rels_new)
    fix_relation_type_casing(rels_new)              
    fix_ansible_operation_order(comps, platform)
    # --- End Sanitization ---

    edmm["components"] = dict_to_lom(comps)
    edmm["relations"]  = dict_to_lom(rels_new)
    edmm["component_types"] = dict_to_lom(type_defs)
    
    # 3. Ensure root properties is ALWAYS a list to match ground truth expectations.
    # LLM might occasionally output {} instead of []
    if "properties" in edmm and isinstance(edmm["properties"], dict):
        edmm["properties"] = dict_to_lom(edmm["properties"])
    elif "properties" not in edmm:
        edmm["properties"] = []
    
    return sort_edmm_recursively(edmm)


# Interface for rag.py usage
def post_process_structure(data):
    # This is called on chunks, but checks basic structure
    return data

def merge_edmm_data(target, source, platform: str = ""):
    """
    Merging using the robust post_processing logic.
    For simplicity, we will merge the raw Lists of Maps from source into target,
    then apply the heavy cleaning on the combined result.
    The platform parameter is forwarded to post_process_edmm so it can make
    reliable platform-specific decisions (e.g. skip prefix-stripping on kubernetes).
    """
    if not isinstance(target, dict): target = {}
    if not isinstance(source, dict): return target
    
    # Naive merge of lists first
    for key in ["components", "relations", "component_types"]:
        t_list = target.get(key, [])
        s_list = source.get(key, [])
        if not isinstance(t_list, list): t_list = []
        if not isinstance(s_list, list): s_list = []
        target[key] = t_list + s_list
        
    # Then apply the Master Cleaner with explicit platform knowledge
    return post_process_edmm(target, platform=platform)
