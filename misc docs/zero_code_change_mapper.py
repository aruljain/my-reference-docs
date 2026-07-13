#!/usr/bin/env python3
"""
zero_code_change_mapper.py

Single script to:
  1. Discover all microservice repos in a GitLab group (recursively).
  2. Audit each repo for Kafka integration pattern (config-only vs needs-code-touch)
     to build the "zero code change" migration map for Apicurio adoption.
  3. Generate architecture / flow diagrams (Graphviz) illustrating the maker-checker
     flow, the fleet migration wave plan, and the classification decision tree.
  4. Build a Confluence-storage-format HTML page containing the summary, full
     audit table, and embedded diagrams.
  5. (Optional, gated behind --publish) Push the page + diagram attachments to
     Confluence Cloud via the REST API.

DEFAULT MODE IS DRY-RUN: running with no --publish flag only writes local files
(CSV, PNGs, HTML) under ./output/ so you can review before anything is pushed
to Confluence.

-------------------------------------------------------------------------------
REQUIRED ENVIRONMENT VARIABLES
-------------------------------------------------------------------------------
  GITLAB_URL            e.g. https://gitlab.yourorg.com
  GITLAB_TOKEN          Personal/Project access token with `read_api`, `read_repository`
  GITLAB_GROUP_ID       Top-level group ID containing all microservice repos

  CONFLUENCE_SITE        e.g. yourorg  (i.e. https://yourorg.atlassian.net)
  CONFLUENCE_EMAIL       Atlassian account email used to generate the API token
  CONFLUENCE_TOKEN       Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
  CONFLUENCE_SPACE_KEY   Target space key, e.g. ENG
  CONFLUENCE_PARENT_ID   (optional) parent page ID to nest the new page under

-------------------------------------------------------------------------------
USAGE
-------------------------------------------------------------------------------
  # Full dry-run: discover repos, audit, build diagrams + page HTML locally
  python3 zero_code_change_mapper.py all

  # Individual phases
  python3 zero_code_change_mapper.py discover
  python3 zero_code_change_mapper.py audit
  python3 zero_code_change_mapper.py diagrams
  python3 zero_code_change_mapper.py build-page

  # Only after reviewing ./output/confluence_page_body.html locally:
  python3 zero_code_change_mapper.py publish

  # Or do everything AND publish in one shot (use with care):
  python3 zero_code_change_mapper.py all --publish

  # Test the pipeline without GitLab access, using bundled sample data:
  python3 zero_code_change_mapper.py all --sample-data
-------------------------------------------------------------------------------
"""

import os
import sys
import csv
import json
import base64
import shutil
import argparse
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("ERROR: `requests` library is required. Install with: pip install requests --break-system-packages")
    sys.exit(1)

OUTPUT_DIR = Path("./output")
REPOS_FILE = OUTPUT_DIR / "repos.json"
AUDIT_CSV = OUTPUT_DIR / "audit-results.csv"
DIAGRAMS_DIR = OUTPUT_DIR / "diagrams"
PAGE_HTML_FILE = OUTPUT_DIR / "confluence_page_body.html"
PAGE_TITLE = "Zero-Code-Change Apicurio Migration Map"

WAVE_1_MIN_CONFIDENCE = "high"  # only high-confidence CONFIG_ONLY_SERDE_SWAP goes to wave 1


# ===========================================================================
# CONFIG
# ===========================================================================

class Config:
    def __init__(self):
        self.gitlab_url = os.environ.get("GITLAB_URL", "").rstrip("/")
        self.gitlab_token = os.environ.get("GITLAB_TOKEN", "")
        self.gitlab_group_id = os.environ.get("GITLAB_GROUP_ID", "")

        self.confluence_site = os.environ.get("CONFLUENCE_SITE", "")
        self.confluence_email = os.environ.get("CONFLUENCE_EMAIL", "")
        self.confluence_token = os.environ.get("CONFLUENCE_TOKEN", "")
        self.confluence_space_key = os.environ.get("CONFLUENCE_SPACE_KEY", "")
        self.confluence_parent_id = os.environ.get("CONFLUENCE_PARENT_ID", "")

    @property
    def confluence_base_url(self):
        return f"https://{self.confluence_site}.atlassian.net/wiki"

    def require_gitlab(self):
        missing = [n for n, v in [
            ("GITLAB_URL", self.gitlab_url),
            ("GITLAB_TOKEN", self.gitlab_token),
            ("GITLAB_GROUP_ID", self.gitlab_group_id),
        ] if not v]
        if missing:
            print(f"ERROR: missing required env vars for GitLab: {', '.join(missing)}")
            sys.exit(1)

    def require_confluence(self):
        missing = [n for n, v in [
            ("CONFLUENCE_SITE", self.confluence_site),
            ("CONFLUENCE_EMAIL", self.confluence_email),
            ("CONFLUENCE_TOKEN", self.confluence_token),
            ("CONFLUENCE_SPACE_KEY", self.confluence_space_key),
        ] if not v]
        if missing:
            print(f"ERROR: missing required env vars for Confluence: {', '.join(missing)}")
            sys.exit(1)


# ===========================================================================
# PHASE 1: GITLAB REPO DISCOVERY
# ===========================================================================

def discover_repos(cfg: Config) -> list:
    """Enumerate all projects under a GitLab group, including subgroups."""
    cfg.require_gitlab()
    headers = {"PRIVATE-TOKEN": cfg.gitlab_token}
    repos = []
    page = 1
    per_page = 100

    while True:
        url = (f"{cfg.gitlab_url}/api/v4/groups/{cfg.gitlab_group_id}/projects"
               f"?include_subgroups=true&per_page={per_page}&page={page}&archived=false")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for p in batch:
            repos.append({
                "id": p["id"],
                "path_with_namespace": p["path_with_namespace"],
                "http_url_to_repo": p["http_url_to_repo"],
                "default_branch": p.get("default_branch", "main"),
            })
        page += 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPOS_FILE.write_text(json.dumps(repos, indent=2))
    print(f"Discovered {len(repos)} repos -> {REPOS_FILE}")
    return repos


def load_repos() -> list:
    if not REPOS_FILE.exists():
        print(f"ERROR: {REPOS_FILE} not found. Run `discover` first (or use --sample-data).")
        sys.exit(1)
    return json.loads(REPOS_FILE.read_text())


# ===========================================================================
# PHASE 2: AUDIT — CLASSIFY EACH REPO
# ===========================================================================

# grep patterns used for classification signals
GREP_PATTERNS = {
    "reactive_messaging": [r"mp\.messaging\.\(incoming\|outgoing\)"],
    "raw_kafka_producer": [r"new KafkaProducer", r"KafkaProducer<"],
    "raw_kafka_consumer": [r"new KafkaConsumer", r"KafkaConsumer<"],
    "custom_serializer": [r"implements Serializer<", r"implements Deserializer<"],
    "avro_lib_usage": [r"io\.confluent\.kafka\.serializers", r"KafkaAvroSerializer", r"KafkaAvroDeserializer"],
    "quarkus_kafka_ext": [r"quarkus-messaging-kafka", r"quarkus-kafka-client"],
}

INCLUDE_GLOBS = {
    "reactive_messaging": ["*.properties", "*.yaml", "*.yml"],
    "raw_kafka_producer": ["*.java"],
    "raw_kafka_consumer": ["*.java"],
    "custom_serializer": ["*.java"],
    "avro_lib_usage": ["*.properties", "*.yaml", "*.java", "pom.xml"],
    "quarkus_kafka_ext": ["pom.xml", "build.gradle", "build.gradle.kts"],
}


def _grep_count(repo_dir: Path, patterns: list, globs: list) -> int:
    """Count files matching any pattern within given globs. Returns distinct-file count."""
    include_args = []
    for g in globs:
        include_args += ["--include", g]
    pattern_arg = "\\|".join(patterns)
    cmd = ["grep", "-rl"] + include_args + [pattern_arg, str(repo_dir)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode not in (0, 1):  # 1 = no matches, still valid
            return 0
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        return len(lines)
    except subprocess.TimeoutExpired:
        return 0


def audit_repo(cfg: Config, repo: dict, workdir: Path) -> dict:
    """Shallow clone a repo and classify its Kafka integration pattern."""
    repo_dir = workdir / str(repo["id"])
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    clone_url = repo["http_url_to_repo"]
    if cfg.gitlab_token and clone_url.startswith("https://"):
        clone_url = clone_url.replace("https://", f"https://oauth2:{cfg.gitlab_token}@", 1)

    clone_cmd = ["git", "clone", "--depth", "1", "--quiet", clone_url, str(repo_dir)]
    try:
        subprocess.run(clone_cmd, capture_output=True, text=True, timeout=120, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return {
            "repo": repo["path_with_namespace"], "category": "ERROR", "wave": "n/a",
            "reactive_messaging": 0, "raw_kafka_producer": 0, "raw_kafka_consumer": 0,
            "custom_serializer": 0, "avro_lib_usage": 0, "quarkus_kafka_ext": 0,
            "confidence": "n/a", "notes": f"clone_failed: {e}",
        }

    signals = {}
    for key, patterns in GREP_PATTERNS.items():
        signals[key] = _grep_count(repo_dir, patterns, INCLUDE_GLOBS[key])

    if signals["raw_kafka_producer"] > 0 or signals["raw_kafka_consumer"] > 0 or signals["custom_serializer"] > 0:
        category, confidence = "NEEDS_CODE_TOUCH", "high"
        notes = "hand-rolled Kafka client or custom serializer detected"
    elif signals["reactive_messaging"] > 0 and signals["avro_lib_usage"] > 0:
        category, confidence = "CONFIG_ONLY_SERDE_SWAP", "high"
        notes = "uses reactive messaging + existing Avro serde, just swap serializer class"
    elif signals["reactive_messaging"] > 0:
        category, confidence = "CONFIG_ONLY_NEW_SERDE", "medium"
        notes = "reactive messaging present, no existing Avro serde - verify payload format manually"
    else:
        category, confidence = "UNKNOWN_NO_KAFKA_DETECTED", "low"
        notes = "no Kafka usage pattern found - verify manually"

    if signals["quarkus_kafka_ext"] == 0 and category != "UNKNOWN_NO_KAFKA_DETECTED":
        notes += "; WARNING: quarkus-messaging-kafka extension not found in build file - verify dependency model"

    shutil.rmtree(repo_dir, ignore_errors=True)

    return {
        "repo": repo["path_with_namespace"],
        "category": category,
        "confidence": confidence,
        "notes": notes,
        **signals,
    }


def assign_waves(results: list) -> None:
    """Mutates results in-place, adding a 'wave' field based on category/confidence."""
    for r in results:
        if r["category"] == "CONFIG_ONLY_SERDE_SWAP" and r["confidence"] == "high":
            r["wave"] = "1"
        elif r["category"] == "CONFIG_ONLY_NEW_SERDE":
            r["wave"] = "2"
        elif r["category"] == "NEEDS_CODE_TOUCH":
            r["wave"] = "backlog-code-change"
        elif r["category"] == "ERROR":
            r["wave"] = "n/a-retry-audit"
        else:
            r["wave"] = "triage"


def run_audit(cfg: Config, repos: list) -> list:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="audit-workspace-") as workdir:
        workdir_path = Path(workdir)
        for i, repo in enumerate(repos, 1):
            print(f"[{i}/{len(repos)}] Auditing {repo['path_with_namespace']}...")
            results.append(audit_repo(cfg, repo, workdir_path))
    assign_waves(results)
    write_csv(results, AUDIT_CSV)
    print(f"Audit complete -> {AUDIT_CSV}")
    return results


def write_csv(results: list, path: Path):
    fieldnames = ["repo", "category", "wave", "confidence", "reactive_messaging",
                  "raw_kafka_producer", "raw_kafka_consumer", "custom_serializer",
                  "avro_lib_usage", "quarkus_kafka_ext", "notes"]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def load_audit_results() -> list:
    if not AUDIT_CSV.exists():
        print(f"ERROR: {AUDIT_CSV} not found. Run `audit` first (or use --sample-data).")
        sys.exit(1)
    with open(AUDIT_CSV, newline="") as f:
        return list(csv.DictReader(f))


def summarize(results: list) -> dict:
    total = len(results)
    by_category = {}
    for r in results:
        by_category[r["category"]] = by_category.get(r["category"], 0) + 1
    by_wave = {}
    for r in results:
        by_wave[r["wave"]] = by_wave.get(r["wave"], 0) + 1
    return {
        "total": total,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "by_category": by_category,
        "by_wave": by_wave,
    }


# ===========================================================================
# PHASE 3: DIAGRAM GENERATION (Graphviz)
# ===========================================================================

def _render_dot(dot_source: str, out_path: Path):
    proc = subprocess.run(["dot", "-Tpng", "-o", str(out_path)], input=dot_source,
                           capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"ERROR rendering {out_path.name}:\n{proc.stderr}")
        sys.exit(1)
    print(f"  generated {out_path}")


def generate_flow_diagrams(diagrams_dir: Path = DIAGRAMS_DIR):
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    print("Generating diagrams...")

    # --- Diagram 1: Maker-Checker flow (schema change -> registry -> deploy) ---
    maker_checker_dot = r"""
digraph MakerChecker {
    rankdir=LR;
    fontname="Helvetica";
    node [shape=box, style="rounded,filled", fontname="Helvetica", fillcolor="#EAF2FB", color="#3B6EA5"];
    edge [fontname="Helvetica", fontsize=10];

    Maker [label="Maker\nedits .avsc/.proto/.yaml\nopens MR", fillcolor="#FDEBD0", color="#CA8A17"];
    Lint [label="CI: Lint\n(avro-tools / buf / spectral)"];
    Compat [label="CI: Compatibility check\n(Apicurio /test endpoint)"];
    Checker [label="Checker\nCODEOWNERS approval\n(author cannot approve own MR)", fillcolor="#FDEBD0", color="#CA8A17"];
    Merge [label="Merge to main"];
    RegisterDev [label="Register artifact\nApicurio (dev group)"];
    PromoteStg [label="Manual gate:\nPromote to staging", fillcolor="#FADBD8", color="#B03A2E"];
    PromoteProd [label="Manual gate:\nPromote to production", fillcolor="#FADBD8", color="#B03A2E"];
    Deploy [label="K8s deploy\n(Helm, protected environment)"];

    Maker -> Lint -> Compat;
    Compat -> Checker [label="pass"];
    Compat -> Maker [label="fail: revise", style=dashed, color="#B03A2E", fontcolor="#B03A2E"];
    Checker -> Merge [label="approved"];
    Merge -> RegisterDev;
    RegisterDev -> PromoteStg -> PromoteProd -> Deploy;
}
"""
    _render_dot(maker_checker_dot, diagrams_dir / "maker_checker_flow.png")

    # --- Diagram 2: Fleet migration wave plan ---
    wave_plan_dot = r"""
digraph FleetWaves {
    rankdir=TB;
    fontname="Helvetica";
    node [shape=box, style="rounded,filled", fontname="Helvetica", fillcolor="#EAF2FB", color="#3B6EA5"];
    edge [fontname="Helvetica", fontsize=10];

    Audit [label="Fleet audit script\n(scans 700 repos)"];
    Bucket [label="Classification\n(config-only vs code-touch)"];
    Wave1 [label="Wave 1\nCONFIG_ONLY_SERDE_SWAP\n(high confidence)", fillcolor="#D5F5E3", color="#1E8449"];
    Wave2 [label="Wave 2\nCONFIG_ONLY_NEW_SERDE\n(medium confidence)", fillcolor="#FCF3CF", color="#B7950B"];
    Backlog [label="Backlog\nNEEDS_CODE_TOUCH\n(engineering review)", fillcolor="#FADBD8", color="#B03A2E"];
    Triage [label="Triage\nUNKNOWN_NO_KAFKA\n(verify manually)", fillcolor="#EBDEF0", color="#76448A"];

    Canary [label="Canary\n(5-10 services)"];
    Validate [label="Validate:\nKafka lag, error rate,\nApicurio hit metrics"];
    RolloutMgr [label="Release manager\napproves wave\n(protected environment)", fillcolor="#FDEBD0", color="#CA8A17"];
    FullWave [label="Roll out to\nfull wave"];

    Audit -> Bucket;
    Bucket -> Wave1;
    Bucket -> Wave2;
    Bucket -> Backlog;
    Bucket -> Triage;

    Wave1 -> Canary -> Validate -> RolloutMgr -> FullWave;
    Wave2 -> Canary;
}
"""
    _render_dot(wave_plan_dot, diagrams_dir / "fleet_migration_waves.png")

    # --- Diagram 3: Classification decision tree ---
    decision_tree_dot = r"""
digraph DecisionTree {
    rankdir=TB;
    fontname="Helvetica";
    node [shape=box, style="rounded,filled", fontname="Helvetica", fillcolor="#F4F6F7", color="#5D6D7E"];
    edge [fontname="Helvetica", fontsize=10, labeldistance=2];

    Start [label="Repo scanned", shape=ellipse, fillcolor="#EAF2FB", color="#3B6EA5"];
    Q1 [label="Raw KafkaProducer/\nConsumer or custom\nSerializer in src/main?"];
    Q2 [label="Uses reactive\nmessaging channels\n(mp.messaging.*)?"];
    Q3 [label="Existing Avro serde\nconfigured\n(Confluent/other)?"];

    NeedsCode [label="NEEDS_CODE_TOUCH\n(engineering backlog)", fillcolor="#FADBD8", color="#B03A2E"];
    ConfigSwap [label="CONFIG_ONLY_SERDE_SWAP\n(Wave 1)", fillcolor="#D5F5E3", color="#1E8449"];
    ConfigNew [label="CONFIG_ONLY_NEW_SERDE\n(Wave 2)", fillcolor="#FCF3CF", color="#B7950B"];
    Unknown [label="UNKNOWN_NO_KAFKA\n(triage)", fillcolor="#EBDEF0", color="#76448A"];

    Start -> Q1;
    Q1 -> NeedsCode [label="yes"];
    Q1 -> Q2 [label="no"];
    Q2 -> Q3 [label="yes"];
    Q2 -> Unknown [label="no"];
    Q3 -> ConfigSwap [label="yes"];
    Q3 -> ConfigNew [label="no"];
}
"""
    _render_dot(decision_tree_dot, diagrams_dir / "classification_decision_tree.png")

    return [
        diagrams_dir / "maker_checker_flow.png",
        diagrams_dir / "fleet_migration_waves.png",
        diagrams_dir / "classification_decision_tree.png",
    ]


# ===========================================================================
# PHASE 4: BUILD CONFLUENCE PAGE (storage format HTML)
# ===========================================================================

def _image_macro(filename: str, caption: str) -> str:
    return f'''
<ac:image ac:align="center" ac:width="750">
  <ri:attachment ri:filename="{filename}" />
</ac:image>
<p style="text-align:center;"><em>{caption}</em></p>
'''


def build_confluence_html(results: list, summary: dict) -> str:
    by_cat = summary["by_category"]
    by_wave = summary["by_wave"]

    cat_rows = "".join(
        f"<tr><td>{cat}</td><td>{count}</td></tr>"
        for cat, count in sorted(by_cat.items(), key=lambda x: -x[1])
    )
    wave_rows = "".join(
        f"<tr><td>{wave}</td><td>{count}</td></tr>"
        for wave, count in sorted(by_wave.items())
    )

    audit_rows = ""
    for r in results:
        audit_rows += (
            "<tr>"
            f"<td>{r['repo']}</td>"
            f"<td>{r['category']}</td>"
            f"<td>{r['wave']}</td>"
            f"<td>{r['confidence']}</td>"
            f"<td>{r['notes']}</td>"
            "</tr>"
        )

    html = f"""
<h1>{PAGE_TITLE}</h1>
<p><em>Generated: {summary['generated_at']} | Total repos scanned: {summary['total']}</em></p>

<ac:structured-macro ac:name="info">
  <ac:rich-text-body>
    <p>This page is auto-generated by <code>zero_code_change_mapper.py</code>. It maps all
    scanned microservice repositories to a zero-code-change Apicurio Schema Registry migration
    wave, based on static analysis of Kafka integration patterns. Do not hand-edit — rerun the
    script and republish instead.</p>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>1. Maker-Checker Flow</h2>
<p>Schema changes (.avsc / .proto / OpenAPI) flow through GitLab MR review, automated Apicurio
compatibility checks, and manual promotion gates before reaching production.</p>
{_image_macro("maker_checker_flow.png", "Figure 1: Maker-checker flow from schema MR to production deployment")}

<h2>2. Fleet Migration Wave Plan</h2>
<p>Repos are bucketed by migratability and rolled out wave-by-wave, each wave gated by a
release-manager approval on a protected environment.</p>
{_image_macro("fleet_migration_waves.png", "Figure 2: Fleet-wide rollout waves")}

<h2>3. Classification Decision Tree</h2>
<p>The audit script applies this logic to every repo to determine its migration bucket.</p>
{_image_macro("classification_decision_tree.png", "Figure 3: Repo classification decision tree")}

<h2>4. Summary — By Category</h2>
<table>
  <thead><tr><th>Category</th><th>Repo Count</th></tr></thead>
  <tbody>{cat_rows}</tbody>
</table>

<h2>5. Summary — By Wave</h2>
<table>
  <thead><tr><th>Wave</th><th>Repo Count</th></tr></thead>
  <tbody>{wave_rows}</tbody>
</table>

<h2>6. Full Audit Results</h2>
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">Click to expand full repo-by-repo audit table ({summary['total']} repos)</ac:parameter>
  <ac:rich-text-body>
    <table>
      <thead><tr><th>Repo</th><th>Category</th><th>Wave</th><th>Confidence</th><th>Notes</th></tr></thead>
      <tbody>{audit_rows}</tbody>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>7. Next Steps</h2>
<ul>
  <li>Wave 1 (CONFIG_ONLY_SERDE_SWAP, high confidence): proceed directly via Helm library chart bump, no source MR.</li>
  <li>Wave 2 (CONFIG_ONLY_NEW_SERDE): confirm payload schema with owning team before assigning an .avsc, then include in next wave.</li>
  <li>Backlog (NEEDS_CODE_TOUCH): file engineering tickets to replace hand-rolled Kafka clients / custom serializers with reactive messaging channels.</li>
  <li>Triage (UNKNOWN_NO_KAFKA): confirm whether these services use Kafka at all, or a different messaging pattern out of scope for this migration.</li>
</ul>
"""
    return html


def build_page(results=None, summary=None) -> str:
    if results is None:
        results = load_audit_results()
    if summary is None:
        summary = summarize(results)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html = build_confluence_html(results, summary)
    PAGE_HTML_FILE.write_text(html)
    print(f"Confluence page body written -> {PAGE_HTML_FILE}")
    print(f"Diagrams expected in -> {DIAGRAMS_DIR} (run `diagrams` phase if not yet generated)")
    return html


# ===========================================================================
# PHASE 5: PUBLISH TO CONFLUENCE CLOUD
# ===========================================================================

def _confluence_auth_header(cfg: Config) -> dict:
    token = base64.b64encode(f"{cfg.confluence_email}:{cfg.confluence_token}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _find_existing_page(cfg: Config, title: str):
    headers = _confluence_auth_header(cfg)
    url = (f"{cfg.confluence_base_url}/rest/api/content"
           f"?title={requests.utils.quote(title)}&spaceKey={cfg.confluence_space_key}&expand=version")
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0] if results else None


def _create_page(cfg: Config, title: str, html_body: str) -> dict:
    headers = _confluence_auth_header(cfg)
    payload = {
        "type": "page",
        "title": title,
        "space": {"key": cfg.confluence_space_key},
        "body": {"storage": {"value": html_body, "representation": "storage"}},
    }
    if cfg.confluence_parent_id:
        payload["ancestors"] = [{"id": cfg.confluence_parent_id}]
    resp = requests.post(f"{cfg.confluence_base_url}/rest/api/content", headers=headers,
                          data=json.dumps(payload), timeout=30)
    if not resp.ok:
        print(f"ERROR creating page: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json()


def _update_page(cfg: Config, page_id: str, title: str, html_body: str, current_version: int) -> dict:
    headers = _confluence_auth_header(cfg)
    payload = {
        "id": page_id,
        "type": "page",
        "title": title,
        "space": {"key": cfg.confluence_space_key},
        "body": {"storage": {"value": html_body, "representation": "storage"}},
        "version": {"number": current_version + 1},
    }
    resp = requests.put(f"{cfg.confluence_base_url}/rest/api/content/{page_id}", headers=headers,
                         data=json.dumps(payload), timeout=30)
    if not resp.ok:
        print(f"ERROR updating page: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    return resp.json()


def _upload_attachment(cfg: Config, page_id: str, filepath: Path):
    token = base64.b64encode(f"{cfg.confluence_email}:{cfg.confluence_token}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "X-Atlassian-Token": "no-check"}

    # Check if attachment already exists -> update it, else create
    list_url = f"{cfg.confluence_base_url}/rest/api/content/{page_id}/child/attachment?filename={filepath.name}"
    resp = requests.get(list_url, headers={"Authorization": f"Basic {token}"}, timeout=30)
    resp.raise_for_status()
    existing = resp.json().get("results", [])

    with open(filepath, "rb") as f:
        files = {"file": (filepath.name, f, "image/png")}
        if existing:
            att_id = existing[0]["id"]
            url = f"{cfg.confluence_base_url}/rest/api/content/{page_id}/child/attachment/{att_id}/data"
        else:
            url = f"{cfg.confluence_base_url}/rest/api/content/{page_id}/child/attachment"
        resp = requests.post(url, headers=headers, files=files, timeout=60)
    if not resp.ok:
        print(f"ERROR uploading attachment {filepath.name}: {resp.status_code} {resp.text}")
        resp.raise_for_status()
    print(f"  uploaded attachment: {filepath.name}")


def publish_to_confluence(cfg: Config):
    cfg.require_confluence()

    if not PAGE_HTML_FILE.exists():
        print(f"ERROR: {PAGE_HTML_FILE} not found. Run `build-page` first.")
        sys.exit(1)
    html_body = PAGE_HTML_FILE.read_text()

    image_files = sorted(DIAGRAMS_DIR.glob("*.png")) if DIAGRAMS_DIR.exists() else []
    if not image_files:
        print("WARNING: no diagram PNGs found — page will publish without embedded images.")

    print(f"Publishing page '{PAGE_TITLE}' to space '{cfg.confluence_space_key}'...")
    existing = _find_existing_page(cfg, PAGE_TITLE)
    if existing:
        page = _update_page(cfg, existing["id"], PAGE_TITLE, html_body, existing["version"]["number"])
        print(f"Updated existing page (id={page['id']}, version={page['version']['number']})")
    else:
        page = _create_page(cfg, PAGE_TITLE, html_body)
        print(f"Created new page (id={page['id']})")

    for img in image_files:
        _upload_attachment(cfg, page["id"], img)

    page_url = f"{cfg.confluence_base_url}/spaces/{cfg.confluence_space_key}/pages/{page['id']}"
    print(f"\nDone. View the page at: {page_url}")


# ===========================================================================
# SAMPLE DATA (for testing the pipeline without live GitLab/Confluence access)
# ===========================================================================

def generate_sample_data():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sample_repos = [
        {"id": 1, "path_with_namespace": "team-a/order-service", "http_url_to_repo": "sample", "default_branch": "main"},
        {"id": 2, "path_with_namespace": "team-b/legacy-payment-svc", "http_url_to_repo": "sample", "default_branch": "main"},
        {"id": 3, "path_with_namespace": "team-c/notification-service", "http_url_to_repo": "sample", "default_branch": "main"},
        {"id": 4, "path_with_namespace": "team-d/reporting-service", "http_url_to_repo": "sample", "default_branch": "main"},
        {"id": 5, "path_with_namespace": "team-e/inventory-service", "http_url_to_repo": "sample", "default_branch": "main"},
    ]
    REPOS_FILE.write_text(json.dumps(sample_repos, indent=2))

    sample_results = [
        {"repo": "team-a/order-service", "category": "CONFIG_ONLY_SERDE_SWAP", "confidence": "high",
         "notes": "uses reactive messaging + existing Avro serde, just swap serializer class",
         "reactive_messaging": 1, "raw_kafka_producer": 0, "raw_kafka_consumer": 0,
         "custom_serializer": 0, "avro_lib_usage": 1, "quarkus_kafka_ext": 1},
        {"repo": "team-b/legacy-payment-svc", "category": "NEEDS_CODE_TOUCH", "confidence": "high",
         "notes": "hand-rolled Kafka client or custom serializer detected",
         "reactive_messaging": 0, "raw_kafka_producer": 2, "raw_kafka_consumer": 1,
         "custom_serializer": 1, "avro_lib_usage": 0, "quarkus_kafka_ext": 0},
        {"repo": "team-c/notification-service", "category": "CONFIG_ONLY_NEW_SERDE", "confidence": "medium",
         "notes": "reactive messaging present, no existing Avro serde - verify payload format manually",
         "reactive_messaging": 1, "raw_kafka_producer": 0, "raw_kafka_consumer": 0,
         "custom_serializer": 0, "avro_lib_usage": 0, "quarkus_kafka_ext": 1},
        {"repo": "team-d/reporting-service", "category": "UNKNOWN_NO_KAFKA_DETECTED", "confidence": "low",
         "notes": "no Kafka usage pattern found - verify manually",
         "reactive_messaging": 0, "raw_kafka_producer": 0, "raw_kafka_consumer": 0,
         "custom_serializer": 0, "avro_lib_usage": 0, "quarkus_kafka_ext": 0},
        {"repo": "team-e/inventory-service", "category": "CONFIG_ONLY_SERDE_SWAP", "confidence": "high",
         "notes": "uses reactive messaging + existing Avro serde, just swap serializer class",
         "reactive_messaging": 1, "raw_kafka_producer": 0, "raw_kafka_consumer": 0,
         "custom_serializer": 0, "avro_lib_usage": 1, "quarkus_kafka_ext": 1},
    ]
    assign_waves(sample_results)
    write_csv(sample_results, AUDIT_CSV)
    print(f"Sample repos -> {REPOS_FILE}")
    print(f"Sample audit results -> {AUDIT_CSV}")
    return sample_repos, sample_results


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Zero-code-change Apicurio fleet mapper")
    parser.add_argument("phase", choices=["discover", "audit", "diagrams", "build-page", "publish", "all"],
                         help="Which phase to run")
    parser.add_argument("--publish", action="store_true",
                         help="When used with `all`, also publish to Confluence at the end")
    parser.add_argument("--sample-data", action="store_true",
                         help="Use bundled sample data instead of live GitLab access (for dry-testing the pipeline)")
    args = parser.parse_args()

    cfg = Config()

    if args.sample_data and args.phase in ("discover", "audit", "all"):
        repos, results = generate_sample_data()
        if args.phase == "all":
            generate_flow_diagrams()
            summary = summarize(results)
            build_page(results, summary)
            if args.publish:
                publish_to_confluence(cfg)
        return

    if args.phase == "discover":
        discover_repos(cfg)
    elif args.phase == "audit":
        repos = load_repos()
        run_audit(cfg, repos)
    elif args.phase == "diagrams":
        generate_flow_diagrams()
    elif args.phase == "build-page":
        build_page()
    elif args.phase == "publish":
        publish_to_confluence(cfg)
    elif args.phase == "all":
        repos = discover_repos(cfg)
        results = run_audit(cfg, repos)
        generate_flow_diagrams()
        summary = summarize(results)
        build_page(results, summary)
        if args.publish:
            publish_to_confluence(cfg)
        else:
            print("\nDry-run complete. Review ./output/confluence_page_body.html and "
                  "./output/diagrams/*.png, then run:\n  python3 zero_code_change_mapper.py publish")


if __name__ == "__main__":
    main()
