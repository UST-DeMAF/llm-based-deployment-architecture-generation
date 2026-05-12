import os

# AGGRESSIVE FIX: Disable all OTEL/Telemetry before any other imports
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["OTEL_PYTHON_DISABLED"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

import streamlit as st
import tempfile
from pathlib import Path
import yaml
import re
import json

def simple_json_repair(s):
    """Attempt to fix truncated JSON by balancing braces/quotes."""
    if s.count('"') % 2 != 0:
        s += '"'
    open_braces = s.count('{') - s.count('}')
    open_brackets = s.count('[') - s.count(']')
    if open_braces > 0:
        s += '}' * open_braces
    if open_brackets > 0:
        s += ']' * open_brackets
    return s

# Page Config
st.set_page_config(page_title="EDMM RAG Assistant", layout="wide")

st.title("🧩 EDMM RAG Assistant")
st.markdown("Upload infrastructure files (Kubernetes, Terraform, Ansible) to convert them into **EDMM YAML**.")

# Sidebar Settings
st.sidebar.header("Configuration")

# GPU/Device Info
import torch
try:
    device_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    device_type = "cuda" if torch.cuda.is_available() else "cpu"
    st.sidebar.success(f"Running on: **{device_name}** ({device_type})")
except Exception:
    st.sidebar.warning("Could not detect device")

case_name = st.sidebar.text_input(
    "Case Name (Optional)",
    placeholder="e.g. OTEL-Shop-Kubernetes, T2Store-Microservices",
    help="Used for ChromaDB filtering and few-shot example selection.\n"
         "T2Store → uses T2Store example\nOTEL-Shop → uses OTEL example"
)
selected_platforms = st.sidebar.multiselect(
    "Platform(s) ⚠️ Required",
    options=["kubernetes", "terraform", "ansible"],
    default=[],
    help=(
        "Select all platforms present in your input files:\n"
        "• kubernetes  → OTEL-Shop-Kubernetes, T2Store k8/*.yaml, T2Store-Modulith\n"
        "• terraform   → OTEL-Shop-Terraform, T2Store terraform/*.tf, Meitrex\n"
        "• ansible     → OTEL-Shop-Ansible\n\n"
        "For T2Store: select BOTH kubernetes + terraform.\n"
        "Per-file detection handles the rest automatically."
    )
)
if not selected_platforms:
    st.sidebar.error("⛔ Please select at least one platform before running.")

# Model: env var ile override edilebilir, yoksa gpt-oss:latest
model_name = os.getenv("LANGUAGE_MODEL", "gpt-oss:latest")
st.sidebar.info(f"Using Model: **{model_name}**")
st.session_state["model_name"] = model_name

# File Uploader & Directory Selector
st.markdown("### 📂 Input Selection")

# Option A
st.subheader("Option A: Upload Files")
uploaded_files = st.file_uploader(
    "Select infrastructure files",
    type=["yaml", "yml", "tf", "tfvars", "hcl", "sh"],
    accept_multiple_files=True,
    label_visibility="collapsed"
)

st.markdown("---")

# Option B
st.subheader("Option B: Select Local Folder")
st.caption("Useful for large projects already on the server.")

default_path = st.session_state.get("selected_dir", "")
local_dir = st.text_input(
    "Local Directory Path",
    value=default_path,
    placeholder="e.g. /app/project_folder/...",
    help="Paste the absolute path to the directory on the server."
)

if local_dir:
    clean_path = local_dir.strip().strip('"').strip("'")
    if os.name != 'nt' and "\\" in clean_path:
        clean_path = clean_path.replace("\\", "/")
    st.session_state.selected_dir = clean_path
    local_dir = clean_path

load_dir = st.checkbox("Enable Folder Scan", value=bool(local_dir))

all_files = []

# 1. Process Uploads
if uploaded_files:
    for u_file in uploaded_files:
        all_files.append((u_file.name, u_file.getvalue().decode("utf-8")))

# 2. Process Directory
if load_dir and local_dir:
    if os.path.exists(local_dir):
        dir_path = Path(local_dir)
        found_files = []
        for ext in ["*.yaml", "*.yml", "*.tf", "*.hcl", "*.tfvars", "*.sh"]:
            found_files.extend(list(dir_path.rglob(ext)))
        for f_path in found_files:
            if f_path.is_file():
                try:
                    if any(part.startswith(".") for part in f_path.parts):
                        continue
                    content = f_path.read_text(encoding="utf-8", errors="ignore")
                    all_files.append((f_path.as_posix(), content))
                except Exception as e:
                    st.warning(f"Skipping {f_path}: {e}")
    else:
        st.error(f"❌ Path not found: `{local_dir}`")
        st.warning(f"Current Working Directory: `{os.getcwd()}`")
        if "Users" in local_dir and os.name != 'nt':
            st.info("💡 Hint: You are running in a Linux/Docker environment.")

if all_files:
    st.info(f"Loaded {len(all_files)} files.")

    # === EXPECTED FILE UPLOAD ===
    st.markdown("---")
    st.subheader("📊 Evaluation (Optional)")
    uploaded_expected_file = st.file_uploader(
        "📂 Upload Expected EDMM for Comparison",
        type=["yaml", "yml"],
        help="Upload your ground truth EDMM to see color-coded differences"
    )

    expected_data = None
    source_name = ""

    if uploaded_expected_file:
        try:
            expected_data = yaml.safe_load(uploaded_expected_file)
            source_name = uploaded_expected_file.name
            st.success(f"✅ Expected file loaded: **{source_name}**")
        except Exception as e:
            st.error(f"Error parsing expected file: {e}")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📄 Input Files")
        with st.expander("View File List", expanded=False):
            for fname, _ in all_files:
                st.text(f"- {fname}")
        for fname, content in all_files[:3]:
            with st.expander(f"Preview: {fname}"):
                st.code(content[:1000] + "\n...", language="yaml" if fname.endswith(("yaml", "yml")) else "hcl")

    # Conversion Button
    if st.button("Convert to EDMM", type="primary"):
        progress_bar = st.progress(0, text="Initializing RAG engine (this may take a moment)...")
        status_text = st.empty()

        import rag
        from rag_post_process import merge_edmm_data

        final_edmm = {
            "component_types": [],
            "components": [],
            "relations": [],
            "properties": {}
        }

        all_docs = []
        grouped_files = all_files.copy()

        for fname, content in grouped_files:
            try:
                file_docs = list(yaml.safe_load_all(content))
            except Exception:
                file_docs = [content]
            for doc in file_docs:
                if doc:
                    all_docs.append((doc, fname))

        if not all_docs:
            st.warning("No documents found in uploaded files.")
            st.stop()

        NON_WORKLOAD_KINDS = {
            "ConfigMap", "Secret", "ServiceAccount", "Role", "ClusterRole",
            "RoleBinding", "ClusterRoleBinding", "Namespace", "PodDisruptionBudget",
            "HorizontalPodAutoscaler", "NetworkPolicy", "LimitRange", "ResourceQuota",
            "Pod", "Job", "CronJob",
        }
        filtered_docs = []
        for doc, filename in all_docs:
            if isinstance(doc, dict) and doc.get("kind") in NON_WORKLOAD_KINDS:
                print(f"⏭️ Skipping non-workload Kubernetes resource: kind={doc.get('kind')}", flush=True)
                continue
            filtered_docs.append((doc, filename))


        if not filtered_docs:
            st.warning("All provided documents were non-workload Kubernetes resources. Nothing to process.")
            st.stop()

        # hostname:port pattern for config injection
        HOSTNAME_PORT_RE = re.compile(r'[a-zA-Z][a-zA-Z0-9-]+:\d{3,5}')
        MAX_INJECTION_CHARS = 2000

        with st.container():
            platform_arg = ",".join(selected_platforms)

            # Helm Release Expansion — expand helm_release resources into real K8s manifests
            # so that Deployment/StatefulSet/DaemonSet workloads are visible to the pipeline.
            if "terraform" in platform_arg.lower():
                import subprocess
                helm_expanded_docs = []
                # Known Helm repo URL → local repo name mappings (add more as needed)
                HELM_REPOS = {
                    "https://dapr.github.io/helm-charts": "dapr",
                    "https://charts.bitnami.com/bitnami": "bitnami",
                    "https://charts.keel.sh": "keel",
                }
                for fname, content in all_files:
                    if not fname.lower().endswith(".tf"):
                        continue
                    # Match helm_release resource blocks (supports one level of nested braces)
                    releases = re.findall(
                        r'resource\s+"helm_release"\s+"([^"]+)"\s+\{((?:[^{}]|\{[^{}]*\})*)\}',
                        content, re.DOTALL
                    )
                    for release_name, block in releases:
                        # Helm release name: underscore to dash (Helm DNS-1123 rule)
                        helm_release_name = release_name.replace("_", "-")

                        repo_match = re.search(r'repository\s*=\s*"([^"]+)"', block)
                        chart_match = re.search(r'chart\s*=\s*"([^"]+)"', block)
                        if not repo_match or not chart_match:
                            continue
                        repo = repo_match.group(1)
                        chart = chart_match.group(1)
                        # OCI registries use bitnami layout by convention
                        if repo.startswith("oci://"):
                            chart_full = f"{repo}/{chart}"
                            # OCI: helm template content-service-db oci://registry-1.docker.io/bitnamicharts/postgresql
                        else:
                            repo_name = HELM_REPOS.get(repo)
                            if not repo_name:
                                print(f"  [HELM] Unknown repo '{repo}', skipping", flush=True)
                                continue
                            chart_full = f"{repo_name}/{chart}"
                        print(f"  [HELM] Expanding: helm template {helm_release_name} {chart_full}", flush=True)
                        try:
                            # Pull first for OCI, then use local cache
                            if chart_full.startswith("oci://"):
                                subprocess.run(
                                    ["helm", "pull", chart_full, "--untar", "--untardir", "/tmp/helm_charts"],
                                    capture_output=True, text=True, timeout=60
                                )
                                # Get chart name (last segment)
                                chart_name = chart_full.split("/")[-1]
                                local_chart = f"/tmp/helm_charts/{chart_name}"
                                result = subprocess.run(
                                    ["helm", "template", helm_release_name, local_chart],
                                    capture_output=True, text=True, timeout=60
                                )
                            else:
                                result = subprocess.run(
                                    ["helm", "template", helm_release_name, chart_full],
                                    capture_output=True, text=True, timeout=60
                                )
                            print(f"  [HELM DEBUG] returncode={result.returncode} stdout_len={len(result.stdout)} stderr={result.stderr[:50]}", flush=True)
                            if result.returncode == 0:
                                for helm_doc in yaml.safe_load_all(result.stdout):
                                    if not isinstance(helm_doc, dict):
                                        continue
                                    if helm_doc.get("kind") in ("Deployment", "StatefulSet", "DaemonSet"):
                                        helm_expanded_docs.append((helm_doc, fname))
                                        name = (helm_doc.get("metadata") or {}).get("name", "")
                                        print(f"  [HELM] Found {helm_doc.get('kind')}: {name}", flush=True)
                            else:
                                print(f"  [HELM] Failed: {result.stderr[:100]}", flush=True)
                        except Exception as e:
                            print(f"  [HELM] Error: {e}", flush=True)
                # Parse helm install commands from .sh files
                for fname, content in all_files:
                    if not fname.lower().endswith(".sh"):
                        continue
                    sh_releases = re.findall(
                        r'helm\s+install\s+([\w-]+)\s+(?:--set\s+\S+\s+)*([a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+)(?:\s+--version\s+([\d.]+))?',
                        content
                    )
                    for release_name, chart_full, version in sh_releases:
                        if release_name.startswith("-"):
                            continue
                        print(f"  [HELM-SH] Found: helm install {release_name} {chart_full} version={version or 'latest'}", flush=True)
                        try:
                            helm_cmd = ["helm", "template", release_name, chart_full]
                            if version:
                                helm_cmd += ["--version", version]
                            result = subprocess.run(
                                helm_cmd,
                                capture_output=True, text=True, timeout=60
                            )
                            print(f"  [HELM-SH] returncode={result.returncode} stdout_len={len(result.stdout)}", flush=True)
                            if result.returncode == 0:
                                for helm_doc in yaml.safe_load_all(result.stdout):
                                    if not isinstance(helm_doc, dict):
                                        continue
                                    if helm_doc.get("kind") in ("Deployment", "StatefulSet", "DaemonSet"):
                                        helm_expanded_docs.append((helm_doc, fname))
                                        name = (helm_doc.get("metadata") or {}).get("name", "")
                                        print(f"  [HELM-SH] Added {helm_doc.get('kind')}: {name}", flush=True)
                            else:
                                print(f"  [HELM-SH] Failed: {result.stderr[:200]}", flush=True)
                        except Exception as e:
                            print(f"  [HELM-SH] Error: {e}", flush=True)
                if helm_expanded_docs:
                    filtered_docs = helm_expanded_docs + filtered_docs
                    print(f"  [HELM] Added {len(helm_expanded_docs)} expanded K8s resources", flush=True)

            # For Terraform-only runs: keep only .tf/.hcl files, skip config/files/ injection fragments
            if "terraform" in platform_arg.lower() and "kubernetes" not in platform_arg.lower():
                filtered_docs = [
                    (doc, fname) for doc, fname in filtered_docs
                    if fname.lower().endswith(".tf") or fname.lower().endswith(".hcl")
                ]
                print(f"[TF FILTER] Kept only .tf/.hcl: {len(filtered_docs)} fragments", flush=True)

            # Terraform Docker: split main.tf into resources
            if "terraform" in platform_arg.lower() and "kubernetes" not in platform_arg.lower():
                tf_split_docs = []
                for doc, fname in filtered_docs:
                    # Helm expanded docs are dicts — do not split
                    if isinstance(doc, dict):
                        tf_split_docs.append((doc, fname))
                        continue
                    if not fname.lower().endswith(".tf"):
                        tf_split_docs.append((doc, fname))
                        continue
                    # Split docker_container resources
                    content = str(doc)
                    blocks = re.split(r'(?=resource\s+"docker_container")', content)
                    for block in blocks:
                        if block.strip():
                            tf_split_docs.append((block, fname))
                filtered_docs = tf_split_docs
                print(f"[TF SPLIT] Split into {len(filtered_docs)} resource blocks", flush=True)

            for i, (doc, filename) in enumerate(filtered_docs):
                doc_name = "Part"
                if isinstance(doc, dict):
                    md = doc.get("metadata", {})
                    doc_name = md.get("name") or doc.get("name") or "Part"
                status_text.text(f"Processing: {filename} - {doc_name} ({i+1}/{len(filtered_docs)})")

                doc_str = yaml.dump(doc) if isinstance(doc, (dict, list)) else str(doc)

                # ─── 3c. Config file injection per workload ───────────────────────────────
                # K8s: ConfigMap data alanı (isim bazlı eşleştirme)
                # Ansible: roles/{name}/files/ klasörü (klasör yapısı bazlı)
                # Terraform: files/ klasörü (hostname:port pattern bazlı)
                # All platforms: hostname:port pattern ile filtre
                related_configs = ""

                is_k8s_workload = (
                    isinstance(doc, dict) and
                    doc.get("kind") in ("Deployment", "StatefulSet", "DaemonSet")
                )
                _is_ansible = "ansible" in platform_arg.lower()
                _is_terraform = "terraform" in platform_arg.lower()

                # K8s: valueFrom referanslarını resolve et
                if is_k8s_workload and isinstance(doc, dict):
                    containers = (doc.get("spec", {})
                                     .get("template", {})
                                     .get("spec", {})
                                     .get("containers", []))
                    resolved_envs = {}
                    for container in containers:
                        for env in container.get("env", []):
                            env_name = env.get("name", "")
                            if "valueFrom" in env:
                                vf = env["valueFrom"]
                                ref_name = None
                                ref_key = None
                                if "configMapKeyRef" in vf:
                                    ref_name = vf["configMapKeyRef"].get("name")
                                    ref_key = vf["configMapKeyRef"].get("key")
                                elif "secretKeyRef" in vf:
                                    ref_name = vf["secretKeyRef"].get("name")
                                    ref_key = vf["secretKeyRef"].get("key")
                                if ref_name and ref_key:
                                    for cfname, cfcontent in all_files:
                                        try:
                                            for cf_doc in yaml.safe_load_all(cfcontent):
                                                if not isinstance(cf_doc, dict): continue
                                                cm_name = (cf_doc.get("metadata") or {}).get("name", "")
                                                if cm_name != ref_name: continue
                                                data = cf_doc.get("data", {})
                                                if ref_key in data:
                                                    resolved_envs[env_name] = data[ref_key]
                                        except Exception:
                                            pass
                    if resolved_envs:
                        doc_str += "\n# Resolved env vars from ConfigMap/Secret:\n"
                        for k, v in resolved_envs.items():
                            doc_str += f"# {k}: {v}\n"
                        print(f"  [RESOLVE] {len(resolved_envs)} env vars resolved for {doc_name}", flush=True)

                # K8s: ConfigMap matching
                if is_k8s_workload:
                    comp_name_lower = doc_name.lower()
                    for cfname, cfcontent in all_files:
                        try:
                            cf_docs = list(yaml.safe_load_all(cfcontent))
                        except Exception:
                            cf_docs = []
                        for cf_doc in cf_docs:
                            if not isinstance(cf_doc, dict): continue
                            if cf_doc.get("kind") != "ConfigMap": continue
                            cm_content = yaml.dump(cf_doc)
                            if HOSTNAME_PORT_RE.search(cm_content):
                                cm_name = (cf_doc.get("metadata") or {}).get("name", "")
                                related_configs += f"\n# ConfigMap: {cm_name}\n"
                                related_configs += cm_content[:MAX_INJECTION_CHARS]
                                print(f"  [CONFIG] K8s ConfigMap added '{cm_name}' for '{doc_name}'", flush=True)

                # Ansible: Jinja2 variable resolution
                if _is_ansible and "/tasks/" in filename.lower():
                    role_name_for_defaults = None
                    if "/roles/" in filename.lower():
                        role_name_for_defaults = filename.lower().split("/roles/")[1].split("/")[0]
                    if role_name_for_defaults:
                        role_defaults = {}
                        for cfname, cfcontent in all_files:
                            if f"/roles/{role_name_for_defaults}/defaults/" in cfname.lower() or \
                               f"/roles/{role_name_for_defaults}/vars/" in cfname.lower():
                                try:
                                    defaults = yaml.safe_load(cfcontent) or {}
                                    if isinstance(defaults, dict):
                                        role_defaults.update(defaults)
                                except Exception:
                                    pass
                        if role_defaults:
                            for k, v in role_defaults.items():
                                doc_str = doc_str.replace(f"{{{{ {k} }}}}", str(v))
                                doc_str = doc_str.replace(f"{{{{{k}}}}}", str(v))
                            print(f"  [JINJA2] Resolved {len(role_defaults)} vars for '{role_name_for_defaults}'", flush=True)

                # Ansible: roles/{name}/files/ directory
                if _is_ansible:
                    role_name = None
                    fname_lower = filename.lower()
                    if "/roles/" in fname_lower:
                        parts = fname_lower.split("/roles/")
                        if len(parts) > 1:
                            role_name = parts[1].split("/")[0]
                    # ONLY add config when processing tasks/ file
                    # skip during defaults/main.yml, meta/main.yml iterations
                    is_tasks_file = "tasks" in fname_lower
                    if role_name and is_tasks_file:
                        for cfname, cfcontent in all_files:
                            if f"/roles/{role_name}/files/" not in cfname.lower(): continue
                            if cfname.lower().endswith(".json"): continue
                            if not HOSTNAME_PORT_RE.search(cfcontent): continue
                            related_configs += f"\n# Role config file: {cfname}\n"
                            related_configs += cfcontent[:500]
                            print(f"  [CONFIG] Ansible role file added '{cfname}' for role '{role_name}'", flush=True)

                # Terraform: files/ directory
                elif _is_terraform:
                    for cfname, cfcontent in all_files:
                        if "/files/" not in cfname.lower(): continue
                        if cfname.lower().endswith(".json"): continue
                        if not HOSTNAME_PORT_RE.search(cfcontent): continue
                        related_configs += f"\n# Terraform config file: {cfname}\n"
                        related_configs += cfcontent[:MAX_INJECTION_CHARS]
                        print(f"  [CONFIG] Terraform file added '{cfname}' for '{doc_name}'", flush=True)

                if related_configs:
                    doc_str += f"\n\n# Related config files (do NOT create components — use ONLY for ConnectsTo relations):\n{related_configs}"
                # ─── END 3c ───────────────────────────────────────────────────────────────

                query = f"""
                Task: Convert the following specific infrastructure fragment to EDMM YAML.
                Filename: {filename}
                
                Fragment Content:
                ```yaml
                {doc_str}
                ```
                """

                if not selected_platforms:
                    st.error(f"⛔ Cannot determine platform for '{filename}'. Please select a platform.")
                    st.stop()

                st.caption(f"📌 `{filename}` → processing: **{doc_name}** with rules for: **{platform_arg}**")

                try:
                    target_res_arg = doc_name if doc_name != "Part" else None

                    try:
                        chunk_answer = rag.answer(
                            query=query,
                            case=case_name,
                            platform=platform_arg,
                            target_resource=target_res_arg,
                            output_format="edmm_expected_schema",
                            model_name=st.session_state.get("model_name", "gpt-oss")
                        )
                    except TypeError:
                        print("WARN: rag.answer signature mismatch, using fallback call without model_name.")
                        chunk_answer = rag.answer(
                            query=query,
                            case=case_name,
                            platform=platform_arg,
                            target_resource=target_res_arg,
                            output_format="edmm_expected_schema"
                        )

                    try:
                        if isinstance(chunk_answer, dict):
                            partial_data = chunk_answer
                        else:
                            cleaned_answer = chunk_answer.replace("```yaml", "").replace("```", "").strip()
                            if cleaned_answer.startswith("**"):
                                cleaned_answer = cleaned_answer.replace("**", "").strip()
                            partial_data = yaml.safe_load(cleaned_answer)
                    except Exception as e:
                        print(f"Failed to parse YAML from RAG: {e}")
                        partial_data = None

                    if not isinstance(partial_data, dict):
                        print(f"WARN: RAG output was not a dictionary (Type: {type(partial_data)}). Skipping chunk.")
                        continue

                    if isinstance(partial_data, dict):
                        final_edmm = merge_edmm_data(final_edmm, partial_data, platform=platform_arg)

                except Exception as e:
                    st.error(f"Error on chunk {i}: {e}")

                progress_bar.progress((i + 1) / len(filtered_docs))

        # ─── PHASE 3 + 3b: Shared Setup ──────────────────────────────────────────
        from rag_post_process import lom_to_dict

        comp_list = final_edmm.get("components", {})
        if isinstance(comp_list, list):
            comp_list = lom_to_dict(comp_list)

        CONN_KEYS = re.compile(
            r'(HOST|ADDR|URL|ENDPOINT|URI|NAME|PORT|SERVICE|COLLECTOR)',
            re.IGNORECASE
        )

        comp_summary = ""
        for cname, cbody in comp_list.items():
            if not isinstance(cbody, dict):
                continue
            props = cbody.get("properties", [])
            relevant_props = []

            if isinstance(props, list):
                items = [(list(p.items())[0]) for p in props if isinstance(p, dict)]
            elif isinstance(props, dict):
                items = list(props.items())
            else:
                items = []

            for k, v in items:
                v_str = str(v)
                # check contain another component's name
                has_comp_ref = any(
                    other in v_str
                    for other in comp_list
                    if other != cname and other != "defaultKubernetesCluster"
                )
                # check contain host:port pattern?
                has_host_port = bool(re.search(r'[a-zA-Z][a-zA-Z0-9-]+:\d{3,5}', v_str))
                # check related to connection
                has_conn_key = bool(CONN_KEYS.search(str(k)))

                if has_comp_ref or has_host_port or has_conn_key:
                    relevant_props.append(f"{k}={v_str}")

            # Hard cap: maksimum 10 property per component
            prop_str = ", ".join(relevant_props[:10])
            comp_summary += f"- {cname}: {prop_str}\n"

        is_ansible = "ansible" in platform_arg.lower()
        has_docker_container = any(
            'resource "docker_container"' in content
            for fname, content in all_files
            if fname.lower().endswith(".tf")
        )
        is_terraform_docker = (
            "terraform" in platform_arg.lower()
            and "kubernetes" not in platform_arg.lower()
            and has_docker_container
        )
        rel_naming = "source_connectsTo_target" if is_ansible else "source_ConnectsTo_target"
        rel_type_word = "connectsTo" if is_ansible else "ConnectsTo"

        # ─── Phase 3 config injection — general for three platforms ───────────────────
        # add config files containing hostname:port pattern to Phase 3 prompt
        # K8s: ConfigMap data fields
        # Ansible: roles/*/files/ directory
        # Terraform: files/ directory
        phase3_config_injection = ""

        for fname, content in all_files:
            fname_lower = fname.lower()

            # Kubernetes: ConfigMap data fields
            if "kubernetes" in platform_arg.lower():
                try:
                    for cfgdoc in yaml.safe_load_all(content):
                        if not isinstance(cfgdoc, dict): continue
                        if cfgdoc.get("kind") != "ConfigMap": continue
                        data = cfgdoc.get("data", {})
                        for key, val in data.items():
                            if HOSTNAME_PORT_RE.search(str(val)):
                                cm_name = (cfgdoc.get("metadata") or {}).get("name", "")
                                phase3_config_injection += f"\n# ConfigMap {cm_name} [{key}]:\n{str(val)[:1000]}\n"
                                print(f"[PHASE3] K8s ConfigMap added: {cm_name}/{key}", flush=True)
                except Exception:
                    pass

            # Ansible: roles/*/files/ directory
            if "ansible" in platform_arg.lower():
                if "/roles/" in fname_lower and "/files/" in fname_lower:
                    if not fname_lower.endswith(".json"):
                        if HOSTNAME_PORT_RE.search(content):
                            phase3_config_injection += f"\n# Ansible config ({fname}):\n{content[:1000]}\n"
                            print(f"[PHASE3] Ansible role file added: {fname}", flush=True)

            # Terraform: files/ directory
            if "terraform" in platform_arg.lower():
                if "/files/" in fname_lower and not fname_lower.endswith(".json"):
                    if HOSTNAME_PORT_RE.search(content):
                        phase3_config_injection += f"\n# Terraform config ({fname}):\n{content[:1000]}\n"
                        print(f"[PHASE3] Terraform config file added: {fname}", flush=True)

        print(f"[PHASE3] Component count: {len(comp_list)}", flush=True)
        print(f"[PHASE3] comp_summary preview:\n{comp_summary[:500]}", flush=True)

        _llm = None
        try:
            try:
                from langchain_ollama import OllamaLLM as _LLM
            except ImportError:
                from langchain_community.llms import Ollama as _LLM
            _llm = _LLM(
                model=st.session_state.get("model_name", "gpt-oss"),
                base_url=os.getenv("OLLAMA_HOST", "http://localhost:11437"),
                timeout=120.0,
                num_ctx=16384
            )
        except Exception as e:
            print(f"[PHASE3] ⚠️ LLM init failed: {e}", flush=True)

        def resolve_to_full_name(short_name, comp_names):
            if not short_name: return None
            if short_name in comp_names: return short_name
            for full in comp_names:
                if full.endswith(f"-{short_name}") or full == short_name:
                    return full
            return None

        # ─── PHASE 3: Global ConnectsTo Extraction ────────────────────────────────
        # Single LLM call with ALL components visible — catches cross-fragment
        # relations that Phase 2 missed because it only had local per-fragment context.
        # NOT RAG — no ChromaDB query, all context already available.
        status_text.text("Phase 3: Extracting cross-component relations (global view)...")
        if _llm is not None and not is_ansible and not is_terraform_docker:
            try:
                config_prompt_part = ""
                if phase3_config_injection:
                    config_prompt_part = (
                        "Config files provided above contain service connection references.\n"
                        "For each hostname:port pattern in the config files, check if the \n"
                        "hostname matches a component name. If yes, create a ConnectsTo \n"
                        "relation from the component that OWNS this config to the matched component:\n"
                        + phase3_config_injection
                    )

                phase3_prompt = f"""You are an EDMM relation extractor.

Given the following components and their properties, identify ALL ConnectsTo relations.

For each component, scan its property VALUES for references to other component names.
Strip protocol prefixes (http://, https://, jdbc:*://, redis://, amqp://) and port 
suffixes (:NNNN) before matching. A reference can be an exact or substring match.

Components:
{comp_summary}

{config_prompt_part}

Rules:
- Only create ConnectsTo between components in the list above
- Do NOT create HostedOn relations
- Relation key naming: {rel_naming}
- IMPORTANT: Use the EXACT component names listed above — do not shorten or remove prefixes
- Output ONLY valid YAML with root key 'relations'
- End your output with [OUTPUT END]
"""

                p3_raw = _llm.invoke(phase3_prompt)
                print(f"[PHASE3] Raw LLM output:\n{p3_raw[:1000]}", flush=True)
                p3_raw_clean = p3_raw.split("[END]")[0].split("[OUTPUT END]")[0]
                p3_raw_clean = re.sub(r"```[a-zA-Z]*\n?", "", p3_raw_clean).replace("```", "").strip()
                if p3_raw_clean.lstrip().startswith("relations:"):
                    try:
                        p3_data = yaml.safe_load(p3_raw_clean) or {}
                    except Exception as pe:
                        print(f"[PHASE3] YAML parse error: {pe}", flush=True)
                        p3_data = {}
                else:
                    try:
                        p3_data = yaml.safe_load("relations:\n" + p3_raw_clean) or {}
                    except Exception as pe:
                        print(f"[PHASE3] YAML parse error: {pe}", flush=True)
                        p3_data = {}
                print(f"[PHASE3] Parsed relations count: {len(p3_data.get('relations', {})) if isinstance(p3_data.get('relations'), dict) else p3_data.get('relations', [])}", flush=True)

                if isinstance(p3_data, dict) and p3_data.get("relations"):
                    existing_rels = final_edmm.get("relations", {})
                    if isinstance(existing_rels, list):
                        existing_rels = lom_to_dict(existing_rels)
                    new_rels = p3_data.get("relations", {})
                    added = 0

                    sep = "_connectsTo_" if is_ansible else "_ConnectsTo_"

                    if isinstance(new_rels, dict):
                        for k, v in new_rels.items():
                            if k in existing_rels:
                                continue
                            parts = k.split(sep) if sep in k else k.split("_ConnectsTo_") if "_ConnectsTo_" in k else k.split("_connectsTo_")
                            if isinstance(v, dict):
                                v["type"] = rel_type_word
                                src = v.get("source") or (parts[0] if len(parts) == 2 else None)
                                tgt = v.get("target") or (parts[1] if len(parts) == 2 else None)
                                src = resolve_to_full_name(src, comp_list)
                                tgt = resolve_to_full_name(tgt, comp_list)
                                if not src or not tgt: continue
                                v["source"] = src
                                v["target"] = tgt
                                rkey = f"{src}{sep}{tgt}"
                                if rkey not in existing_rels:
                                    existing_rels[rkey] = v
                                    added += 1
                                    print(f"  [PHASE3] Added: {rkey}", flush=True)
                            else:
                                if len(parts) != 2: continue
                                src = resolve_to_full_name(parts[0], comp_list)
                                tgt = resolve_to_full_name(parts[1], comp_list)
                                if not src or not tgt: continue
                                rkey = f"{src}{sep}{tgt}"
                                if rkey not in existing_rels:
                                    existing_rels[rkey] = {"type": rel_type_word, "source": src, "target": tgt}
                                    added += 1
                                    print(f"  [PHASE3] Added: {rkey}", flush=True)

                    elif isinstance(new_rels, list):
                        for item in new_rels:
                            if isinstance(item, str) and ("→" in item or "->" in item):
                                arrow = "→" if "→" in item else "->"
                                arrow_parts = item.split(arrow)
                                if len(arrow_parts) == 2:
                                    src_short = arrow_parts[0].strip()
                                    tgt_short = arrow_parts[1].strip()
                                    src_full = resolve_to_full_name(src_short, comp_list)
                                    tgt_full = resolve_to_full_name(tgt_short, comp_list)
                                    if src_full and tgt_full:
                                        rkey = f"{src_full}{sep}{tgt_full}"
                                        if rkey not in existing_rels:
                                            existing_rels[rkey] = {"type": rel_type_word, "source": src_full, "target": tgt_full}
                                            added += 1
                                            print(f"  [PHASE3] Added (parsed arrow): {rkey}", flush=True)
                                continue

                            if not isinstance(item, dict): continue
                            src = item.get("source") or item.get("from")
                            tgt = item.get("target") or item.get("to")
                            src = resolve_to_full_name(src, comp_list)
                            tgt = resolve_to_full_name(tgt, comp_list)
                            if not src or not tgt: continue
                            rkey = f"{src}{sep}{tgt}"
                            if rkey not in existing_rels:
                                existing_rels[rkey] = {"type": rel_type_word, "source": src, "target": tgt}
                                added += 1
                                print(f"  [PHASE3] Added: {rkey}", flush=True)

                    final_edmm["relations"] = existing_rels
                    print(f"[PHASE3] ✅ Added {added} new ConnectsTo relations", flush=True)

            except Exception as e:
                print(f"[PHASE3] ⚠️ Failed: {e}", flush=True)

        # ─── PHASE 3b: Feedback Loop ──────────────────────────────────────────────
        # "Any missing relations?"
        status_text.text("Phase 3b: Checking for missing relations (feedback loop)...")
        if _llm is not None and not is_ansible and not is_terraform_docker:
            try:
                existing_rels = final_edmm.get("relations", {})
                if isinstance(existing_rels, list):
                    existing_rels = lom_to_dict(existing_rels)

                rel_summary = "\n".join(
                    f"- {v.get('source')} → {v.get('target')}"
                    for v in existing_rels.values()
                    if isinstance(v, dict) and v.get("type", "").lower() == "connectsto"
                )

                feedback_prompt = f"""You are reviewing an EDMM deployment model for completeness.

Components:
{comp_summary}

ConnectsTo relations already identified:
{rel_summary if rel_summary else "(none yet)"}

Task: Are there any ConnectsTo relations MISSING from the list above?
Carefully check each component's property values for references to other 
components that are NOT yet in the relations list.

Output ONLY the MISSING relations as valid YAML with root key 'relations'.
If nothing is missing, output exactly:
relations: []

End your output with [OUTPUT END]
"""

                p3b_raw = _llm.invoke(feedback_prompt)
                print(f"[PHASE3b] Raw LLM output:\n{p3b_raw[:1000]}", flush=True)
                p3b_raw_clean = p3b_raw.split("[END]")[0].split("[OUTPUT END]")[0]
                p3b_raw_clean = re.sub(r"```[a-zA-Z]*\n?", "", p3b_raw_clean).replace("```", "").strip()
                if p3b_raw_clean.lstrip().startswith("relations:"):
                    try:
                        p3b_data = yaml.safe_load(p3b_raw_clean) or {}
                    except Exception as pe:
                        print(f"[PHASE3b] YAML parse error: {pe}", flush=True)
                        p3b_data = {}
                else:
                    try:
                        p3b_data = yaml.safe_load("relations:\n" + p3b_raw_clean) or {}
                    except Exception as pe:
                        print(f"[PHASE3b] YAML parse error: {pe}", flush=True)
                        p3b_data = {}
                print(f"[PHASE3b] Parsed relations count: {len(p3b_data.get('relations', {})) if isinstance(p3b_data.get('relations'), dict) else p3b_data.get('relations', [])}", flush=True)

                if isinstance(p3b_data, dict):
                    new_rels = p3b_data.get("relations", {})
                    added = 0
                    sep = "_connectsTo_" if is_ansible else "_ConnectsTo_"

                    if isinstance(new_rels, dict):
                        for k, v in new_rels.items():
                            if k in existing_rels: continue
                            parts = k.split(sep) if sep in k else k.split("_ConnectsTo_") if "_ConnectsTo_" in k else k.split("_connectsTo_")
                            if isinstance(v, dict):
                                v["type"] = rel_type_word
                                src = v.get("source") or (parts[0] if len(parts) == 2 else None)
                                tgt = v.get("target") or (parts[1] if len(parts) == 2 else None)
                                src = resolve_to_full_name(src, comp_list)
                                tgt = resolve_to_full_name(tgt, comp_list)
                                if not src or not tgt: continue
                                v["source"] = src
                                v["target"] = tgt
                                rkey = f"{src}{sep}{tgt}"
                                if rkey not in existing_rels:
                                    existing_rels[rkey] = v
                                    added += 1
                                    print(f"  [PHASE3b] Added: {rkey}", flush=True)
                            else:
                                if len(parts) != 2: continue
                                src = resolve_to_full_name(parts[0], comp_list)
                                tgt = resolve_to_full_name(parts[1], comp_list)
                                if not src or not tgt: continue
                                rkey = f"{src}{sep}{tgt}"
                                if rkey not in existing_rels:
                                    existing_rels[rkey] = {"type": rel_type_word, "source": src, "target": tgt}
                                    added += 1
                                    print(f"  [PHASE3b] Added: {rkey}", flush=True)

                    elif isinstance(new_rels, list):
                        for item in new_rels:
                            if isinstance(item, str) and ("→" in item or "->" in item):
                                arrow = "→" if "→" in item else "->"
                                arrow_parts = item.split(arrow)
                                if len(arrow_parts) == 2:
                                    src_short = arrow_parts[0].strip()
                                    tgt_short = arrow_parts[1].strip()
                                    src_full = resolve_to_full_name(src_short, comp_list)
                                    tgt_full = resolve_to_full_name(tgt_short, comp_list)
                                    if src_full and tgt_full:
                                        rkey = f"{src_full}{sep}{tgt_full}"
                                        if rkey not in existing_rels:
                                            existing_rels[rkey] = {"type": rel_type_word, "source": src_full, "target": tgt_full}
                                            added += 1
                                            print(f"  [PHASE3b] Added (parsed arrow): {rkey}", flush=True)
                                continue

                            if not isinstance(item, dict): continue
                            src = item.get("source") or item.get("from")
                            tgt = item.get("target") or item.get("to")
                            src = resolve_to_full_name(src, comp_list)
                            tgt = resolve_to_full_name(tgt, comp_list)
                            if not src or not tgt: continue
                            rkey = f"{src}{sep}{tgt}"
                            if rkey not in existing_rels:
                                existing_rels[rkey] = {"type": rel_type_word, "source": src, "target": tgt}
                                added += 1
                                print(f"  [PHASE3b] Added: {rkey}", flush=True)

                    final_edmm["relations"] = existing_rels
                    print(f"[PHASE3b] ✅ Added {added} new relations via feedback loop", flush=True)

            except Exception as e:
                print(f"[PHASE3b] ⚠️ Failed: {e}", flush=True)

        # ─── defaultKubernetesCluster injection ───────────────────────────────────
        if "kubernetes" in platform_arg.lower():
            existing_comp_names = []
            if isinstance(final_edmm.get("components"), list):
                for c in final_edmm["components"]:
                    if isinstance(c, dict):
                        existing_comp_names.extend(c.keys())
            elif isinstance(final_edmm.get("components"), dict):
                existing_comp_names = list(final_edmm["components"].keys())

            if "defaultKubernetesCluster" not in existing_comp_names:
                print("⚠️ defaultKubernetesCluster missing — injecting it.", flush=True)
                cluster_comp = {"defaultKubernetesCluster": {
                    "type": "DefaultKubernetesCluster",
                    "properties": [], "operations": [], "artifacts": []
                }}
                if isinstance(final_edmm["components"], list):
                    final_edmm["components"].insert(0, cluster_comp)
                else:
                    final_edmm["components"]["defaultKubernetesCluster"] = cluster_comp["defaultKubernetesCluster"]

        # Final post-process: normalize Phase 3 relations
        from rag_post_process import post_process_edmm
        final_edmm = post_process_edmm(final_edmm, platform=platform_arg)

        # --- REFORMATTING FOR FINAL YAML ---
        # components and relations are now processed by post_process_edmm
        formatted_edmm = final_edmm.copy()

        st.session_state["generated_edmm"] = formatted_edmm
        st.success("Conversion Complete! Results cached.")

    # --- DISPLAY RESULTS ---
    if "generated_edmm" in st.session_state:
        formatted_edmm = st.session_state["generated_edmm"]
        final_yaml = yaml.dump(formatted_edmm, sort_keys=False)

        if expected_data:
            st.markdown("---")
            st.markdown("## 📊 EDMM Comparison View")

            yaml_col1, yaml_col2 = st.columns(2)

            with yaml_col1:
                st.subheader("✨ Generated EDMM (Actual)")
                from edmm_annotate import annotate_by_objects
                annotated_html = annotate_by_objects(formatted_edmm, expected_data)
                st.markdown(
                    f'<div style="font-family: \'Courier New\', monospace; font-size: 13px; line-height: 1.6; background: #fafafa; border: 1px solid #ddd; border-radius: 5px; padding: 15px;">{annotated_html}</div>',
                    unsafe_allow_html=True
                )
                st.caption("✓ = Match | ✗ = Different | + = Extra | - = Missing")
                st.download_button(
                    label="⬇️ Download Actual YAML",
                    data=final_yaml,
                    file_name="generated_edmm.yaml",
                    mime="text/yaml",
                    key="download_actual"
                )

            with yaml_col2:
                st.subheader("📄 Expected EDMM (Reference)")
                expected_yaml = yaml.dump(expected_data, sort_keys=False)
                st.code(expected_yaml, language="yaml")

        else:
            st.subheader("✨ EDMM Output (Merged)")
            st.code(final_yaml, language="yaml")
            st.download_button(
                label="Download Full YAML",
                data=final_yaml,
                file_name="combined_edmm.yaml",
                mime="text/yaml"
            )

# Info
st.markdown("---")
st.markdown("*Powered by LangChain, Ollama & ChromaDB*")
