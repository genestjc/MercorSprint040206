#!/usr/bin/env python3
"""
Claude Code A/B Testing Submit Script
Validates experiment data and uploads to Supabase for analysis.
"""
import os
import sys
import json
import re
import zipfile
import shutil
import time
import gzip
import html as html_mod
from pathlib import Path
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from supabase import create_client, Client
    from tusclient import client as tus_client
except ImportError as e:
    print("❌ ERROR: Required packages not found.")
    print("   Please install them with the following command:")
    print("   pip install supabase tuspy")
    print(f"   (Missing: {e})")
    print("✨ Tip: Copy and paste the install command above into your terminal to continue.✨")
    sys.exit(1)

# Supabase configuration
# Use direct storage hostname for better performance with large files (per Supabase docs)
SUPABASE_URL = "https://sdippjgffrptdvlmlurv.supabase.co"
SUPABASE_STORAGE_URL = "https://sdippjgffrptdvlmlurv.storage.supabase.co"
ANON_KEY = "sb_publishable_ReTMY8aH1JgV3pPiOnXKAA_ZVcYIimL"
BUCKET_NAME = "code-preferences-submissions-v2"
SETUP_BUCKET_NAME = "code-preferences-setup-files-v2"

# Feature flags
CAPTURE_USER_MCP_CONFIG = True  # Capture ~/.claude.json (user-level MCP server configs)

# Sensitive key patterns for obfuscation in user settings
# Any env/headers/oauth key containing these substrings (case-insensitive) will be redacted
SENSITIVE_KEY_PATTERNS = ["KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL"]

# TUS upload configuration (per Supabase requirements)
# IMPORTANT: Chunk size MUST be exactly 6MB for Supabase Storage
TUS_CHUNK_SIZE = 6 * 1024 * 1024  # 6MB - required by Supabase

# Initialize Supabase client
# File uploads use Tus resumable protocol which handles large files with chunking
supabase: Client = create_client(SUPABASE_URL, ANON_KEY)

def print_error(message):
    """Print error message and exit."""
    print(f"❌ ERROR: {message}", file=sys.stderr)
    sys.exit(1)

def print_success(message):
    """Print success message."""
    print(f"✅ {message}")

def print_info(message):
    """Print info message."""
    print(f"ℹ️  {message}")

def print_warning(message):
    """Print warning message."""
    print(f"⚠️  WARNING: {message}")

# Import snapshot utilities
from snapshot_utils import create_repository_snapshot_zip, create_git_diff_patch, get_base_commit_for_model

# Import backfill utility for missing session summaries
from backfill_session_summary import backfill_session_summary

def take_end_snapshots():
    """Take end snapshots of both model directories."""
    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(exist_ok=True)

    model_dirs = {"model_a": Path("model_a"), "model_b": Path("model_b")}

    for model_lane, model_dir in model_dirs.items():
        if not model_dir.exists():
            print_warning(f"Skipping end snapshot for {model_lane} - directory not found")
            continue

        # Create end snapshot zip
        snapshot_zip = snapshots_dir / f"{model_lane}_end.zip"
        if create_repository_snapshot_zip(str(model_dir), str(snapshot_zip)):
            print_success(f"Created end snapshot for {model_lane}")
        else:
            print_warning(f"Failed to create end snapshot for {model_lane}")

        # Get base commit from session logs
        base_commit = get_base_commit_for_model("logs", model_lane)
        if not base_commit:
            print_warning(f"Could not find base commit for {model_lane} - diff may be incomplete")

        # Create diff patch from base commit
        patch_file = snapshots_dir / f"{model_lane}_diff.patch"
        if create_git_diff_patch(str(model_dir), str(patch_file), base_commit):
            if base_commit:
                print_success(f"Created diff patch for {model_lane} (from {base_commit[:8]})")
            else:
                print_success(f"Created diff patch for {model_lane}")
        else:
            print_warning(f"Failed to create diff patch for {model_lane}")

    return True

def download_sprint_config():
    """Download sprint configuration from Supabase (in memory only)."""
    try:
        import requests
    except ImportError:
        print_error("'requests' library not found. Install with: pip install requests")
    
    url = f"{SUPABASE_URL}/storage/v1/object/{SETUP_BUCKET_NAME}/config/sprint_config.json"
    headers = {
        "apikey": ANON_KEY,
        "apikey": ANON_KEY
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        config = response.json()
        return config
        
    except Exception as e:
        print_error(f"Failed to download sprint configuration: {e}")
        return None

def validate_input(prompt, validator=None, error_msg="Invalid input"):
    """Get and validate user input."""
    while True:
        try:
            value = input(f"{prompt}: ").strip()
            if not value:
                print(f"❌ {error_msg}: Input cannot be empty")
                continue
            if validator and not validator(value):
                print(f"❌ {error_msg}")
                continue
            return value
        except KeyboardInterrupt:
            print("\n❌ Submission cancelled by user")
            sys.exit(1)

def validate_folder_name(name):
    """Validate user folder name format."""
    if not name:
        return False
    # Check for valid characters (alphanumeric, underscore, hyphen)
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', name)) and len(name) >= 3

def read_manifest():
    """Read and validate manifest.json file."""
    manifest_path = Path("manifest.json")
    
    if not manifest_path.exists():
        print_error("manifest.json not found. Make sure you're in the experiment directory.")
    
    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        required_fields = ["expert_name", "task_id", "timestamp", "repo_url", "assignments"]
        missing_fields = [field for field in required_fields if field not in manifest]
        
        if missing_fields:
            print_error(f"Invalid manifest.json. Missing fields: {', '.join(missing_fields)}")
        
        return manifest
        
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in manifest.json: {e}")
    except Exception as e:
        print_error(f"Failed to read manifest.json: {e}")

def extract_session_id(filename):
    """Extract session ID from filename like 'session_abc123.jsonl' or 'session_abc123_raw.jsonl'."""
    match = re.search(r'session_([^.]+)', filename)
    if match:
        session_id = match.group(1)
        # Remove _raw suffix if present (it's a valid variation of the same session)
        session_id = session_id.replace('_raw', '')
        return session_id
    return None

def check_session_summary_exists(session_file_path):
    """Check if session_summary event exists in a session log file."""
    try:
        with open(session_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    # Check for both old 'event_type' and new 'type' field for compatibility
                    if event.get('type') == 'session_summary' or event.get('event_type') == 'session_summary':
                        return True
                except json.JSONDecodeError:
                    continue
        return False
    except Exception as e:
        print_warning(f"Failed to read session file {session_file_path}: {e}")
        return False


def validate_experiment_files():
    """Validate that all required experiment files exist."""
    # Check manifest.json exists
    if not Path("manifest.json").is_file():
        print_error("manifest.json not found in current directory")
    
    # Check snapshots folder exists
    if not Path("snapshots").is_dir():
        print_error("snapshots folder not found in current directory")
    
    required_files = [
        "manifest.json",
        "model_a/.claude/settings.local.json",
        "model_b/.claude/settings.local.json"
    ]
    
    required_dirs = [
        "model_a",
        "model_b",
        "logs",
        "snapshots"
    ]
    
    # Check required files
    missing_files = []
    for file_path in required_files:
        if not Path(file_path).is_file():
            missing_files.append(file_path)
    
    # Check required directories
    missing_dirs = []
    for dir_path in required_dirs:
        if not Path(dir_path).is_dir():
            missing_dirs.append(dir_path)
    
    # Check for session logs with simplified validation
    # Required: mandatory session file (session_*.jsonl, not _raw.jsonl)
    # Required: raw session file (session_*_raw.jsonl) - blocks submission if missing
    logs_dir = Path("logs")
    if logs_dir.exists():
        # Validate model_a logs
        model_a_dir = logs_dir / "model_a"
        model_a_all_logs = list(model_a_dir.glob("session_*.jsonl"))
        
        # Separate mandatory and raw files
        model_a_mandatory = [f for f in model_a_all_logs if not f.name.endswith("_raw.jsonl")]
        model_a_raw = [f for f in model_a_all_logs if f.name.endswith("_raw.jsonl")]
        
        # Require exactly 1 mandatory session file
        if not model_a_mandatory:
            print_error("No mandatory session log file found in logs/model_a/ (expected session_*.jsonl)")
        elif len(model_a_mandatory) > 1:
            print_error(f"Found {len(model_a_mandatory)} mandatory session files in logs/model_a/, expected exactly 1")
        else:
            mandatory_file = model_a_mandatory[0]
            session_id_a = extract_session_id(mandatory_file.name)
            print_success(f"Model A: Found mandatory session file '{mandatory_file.name}' with session ID '{session_id_a}'")
            
            # Check for session_summary in the mandatory file
            if not check_session_summary_exists(mandatory_file):
                print_warning(f"Model A: session_summary event not found in '{mandatory_file.name}'")
                print_info("Model A: Attempting to generate fallback session_summary...")
                if backfill_session_summary(str(mandatory_file)):
                    print_success(f"Model A: Fallback session_summary generated successfully")
                else:
                    print_warning(f"Model A: Failed to generate fallback session_summary - API extraction may fail")
            else:
                print_success(f"Model A: session_summary event found in '{mandatory_file.name}'")
            
            # Check for corresponding raw file (mandatory)
            if not model_a_raw:
                print_error(f"Model A: Raw session file (session_{session_id_a}_raw.jsonl) not found — cannot submit without raw transcript")
            else:
                raw_file = model_a_raw[0]
                raw_session_id = extract_session_id(raw_file.name)
                if raw_session_id == session_id_a:
                    print_success(f"Model A: Found raw session file '{raw_file.name}'")
                else:
                    print_warning(f"Model A: Raw session file has different session ID (expected '{session_id_a}', found '{raw_session_id}')")
        
        # Validate model_b logs
        model_b_dir = logs_dir / "model_b"
        model_b_all_logs = list(model_b_dir.glob("session_*.jsonl"))
        
        # Separate mandatory and raw files
        model_b_mandatory = [f for f in model_b_all_logs if not f.name.endswith("_raw.jsonl")]
        model_b_raw = [f for f in model_b_all_logs if f.name.endswith("_raw.jsonl")]
        
        # Require exactly 1 mandatory session file
        if not model_b_mandatory:
            print_error("No mandatory session log file found in logs/model_b/ (expected session_*.jsonl)")
        elif len(model_b_mandatory) > 1:
            print_error(f"Found {len(model_b_mandatory)} mandatory session files in logs/model_b/, expected exactly 1")
        else:
            mandatory_file = model_b_mandatory[0]
            session_id_b = extract_session_id(mandatory_file.name)
            print_success(f"Model B: Found mandatory session file '{mandatory_file.name}' with session ID '{session_id_b}'")
            
            # Check for session_summary in the mandatory file
            if not check_session_summary_exists(mandatory_file):
                print_warning(f"Model B: session_summary event not found in '{mandatory_file.name}'")
                print_info("Model B: Attempting to generate fallback session_summary...")
                if backfill_session_summary(str(mandatory_file)):
                    print_success(f"Model B: Fallback session_summary generated successfully")
                else:
                    print_warning(f"Model B: Failed to generate fallback session_summary - API extraction may fail")
            else:
                print_success(f"Model B: session_summary event found in '{mandatory_file.name}'")
            
            # Check for corresponding raw file (mandatory)
            if not model_b_raw:
                print_error(f"Model B: Raw session file (session_{session_id_b}_raw.jsonl) not found — cannot submit without raw transcript")
            else:
                raw_file = model_b_raw[0]
                raw_session_id = extract_session_id(raw_file.name)
                if raw_session_id == session_id_b:
                    print_success(f"Model B: Found raw session file '{raw_file.name}'")
                else:
                    print_warning(f"Model B: Raw session file has different session ID (expected '{session_id_b}', found '{raw_session_id}')")
    
    # Check for snapshots
    snapshots_dir = Path("snapshots")
    if snapshots_dir.exists():
        expected_snapshots = [
            "model_a_start.zip",
            "model_a_end.zip", 
            "model_a_diff.patch",
            "model_b_start.zip",
            "model_b_end.zip",
            "model_b_diff.patch"
        ]
        
        missing_snapshots = []
        for snapshot in expected_snapshots:
            snapshot_path = snapshots_dir / snapshot
            if not snapshot_path.exists():
                missing_snapshots.append(f"snapshots/{snapshot}")
        
        if missing_snapshots:
            print_warning(f"Some snapshots are missing: {', '.join(missing_snapshots)}")
            print_warning("This might indicate incomplete sessions. Continuing anyway...")
    
    # Report missing items
    all_missing = missing_files + missing_dirs
    if all_missing:
        print_error(f"Validation failed. Missing required items:\n" + 
                   "\n".join(f"  - {item}" for item in all_missing))
    
    print_success("Experiment files validation passed")
    return True

def create_snapshots_zip():
    """Create a zip file of the entire snapshots directory.

    Also writes snapshots_inventory.json listing which files are present,
    so the extraction API can verify contents without downloading the zip.
    """
    snapshots_dir = Path("snapshots")
    if not snapshots_dir.exists():
        return None

    zip_filename = "snapshots.zip"
    print_info(f"Creating snapshots archive: {zip_filename}")

    try:
        included_files = []
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in snapshots_dir.rglob("*"):
                if file_path.is_file():
                    # Add file to zip with relative path from current directory
                    arcname = str(file_path).replace('\\', '/')
                    zipf.write(file_path, arcname=arcname)
                    included_files.append(arcname)
                    print_info(f"  Added to archive: {arcname}")

        # Write inventory so extraction API knows what's inside without unzipping
        expected_files = [
            "snapshots/model_a_start.zip",
            "snapshots/model_a_end.zip",
            "snapshots/model_a_diff.patch",
            "snapshots/model_b_start.zip",
            "snapshots/model_b_end.zip",
            "snapshots/model_b_diff.patch",
        ]
        inventory = {
            "included": included_files,
            "missing": [f for f in expected_files if f not in included_files],
        }
        with open("snapshots_inventory.json", 'w') as f:
            json.dump(inventory, f, indent=2)

        if inventory["missing"]:
            print_warning(f"Snapshots missing from archive: {', '.join(inventory['missing'])}")

        print_success(f"Created snapshots archive: {zip_filename}")
        return zip_filename
    except Exception as e:
        print_warning(f"Failed to create snapshots archive: {e}")
        return None

def get_upload_path_from_version(sprint_folder, task_id, version):
    """Generate upload path based on version number."""
    if version == 0:
        return f"{sprint_folder}/{task_id}"
    else:
        return f"{sprint_folder}/{task_id}_v{version}"

def update_manifest_version(manifest_path, new_version):
    """Update manifest.json with new last_submission_version."""
    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        manifest["last_submission_version"] = new_version
        
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        return True
    except Exception as e:
        print_warning(f"Failed to update manifest version: {e}")
        return False

def generate_transcript_html(jsonl_path):
    """Generate an HTML viewer from a deduplicated JSONL transcript.

    Produces a self-contained HTML file with search, dark theme, and all
    content types rendered. Model names are already stripped from the JSONL.
    Output file is placed alongside the JSONL with .html extension.
    """
    events = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not events:
        return None

    def _ts(ts):
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%H:%M:%S")
        except Exception:
            return ""

    def _tool_result_content(content):
        if isinstance(content, str):
            return html_mod.escape(content)
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(html_mod.escape(item.get("text", "")))
                    elif item.get("type") == "image":
                        parts.append("[image]")
                    else:
                        parts.append(html_mod.escape(json.dumps(item, indent=2)))
                else:
                    parts.append(html_mod.escape(str(item)))
            return "\n".join(parts)
        return html_mod.escape(str(content))

    # Build tool_use_id -> tool_result mapping
    tr_map = {}
    for ev in events:
        if ev.get("type") == "user":
            content = ev.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        if tid:
                            tr_map[tid] = block

    total = len(events)
    turn_count = 0

    page = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Transcript Viewer</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#fafafa;color:#1a1a1a;max-width:960px;margin:0 auto;padding:20px 24px;line-height:1.5}}
h1{{color:#111;font-size:20px;margin-bottom:4px}}
.meta{{color:#888;font-size:13px;margin-bottom:28px}}
.search-bar{{position:sticky;top:0;z-index:100;background:#fafafa;padding:12px 0;border-bottom:1px solid #e5e5e5;margin-bottom:16px}}
.search-bar input{{width:100%;padding:10px 14px;font-size:14px;background:#fff;color:#1a1a1a;border:1px solid #d4d4d4;border-radius:6px;outline:none}}
.search-bar input:focus{{border-color:#7c3aed;box-shadow:0 0 0 2px rgba(124,58,237,0.1)}}
.search-info{{color:#888;font-size:12px;margin-top:6px}}
mark{{background:#fef08a;color:#1a1a1a;padding:1px 2px;border-radius:2px}}
mark.current{{background:#c084fc;color:#fff}}
.turn-divider{{border-top:1px solid #e5e5e5;margin:28px 0 16px 0}}
.event{{margin-bottom:12px;border-radius:8px;padding:14px 18px}}
.user-msg{{background:#f0f7ff;border-left:3px solid #3b82f6}}
.assistant-msg{{background:#f5f3ff;border-left:3px solid #7c3aed}}
.system-msg{{background:#fef2f2;border-left:3px solid #ef4444;font-size:13px}}
.event-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.role{{font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.6px}}
.role-user{{color:#2563eb}}.role-assistant{{color:#6d28d9}}.role-system{{color:#dc2626}}
.timestamp{{color:#999;font-size:11px;font-family:monospace}}
.text-content{{white-space:pre-wrap;font-size:14px;line-height:1.7;word-wrap:break-word;color:#333}}
details{{margin:8px 0}}details summary{{cursor:pointer;font-size:13px;font-weight:500;padding:4px 0}}
.thinking{{background:#f9f5ff;border:1px solid #e9d5ff;border-radius:6px;padding:12px 16px;margin:8px 0}}
.thinking summary{{color:#7c3aed}}.thinking .text-content{{color:#666;font-size:13px}}
.tool-block{{background:#fff;border:1px solid #e5e5e5;border-radius:8px;margin:10px 0;overflow:hidden}}
.tool-header{{background:#f5f5f5;padding:8px 14px;border-bottom:1px solid #e5e5e5}}
.tool-name{{color:#0369a1;font-weight:600;font-size:13px;font-family:monospace}}
.tool-input{{padding:10px 14px;font-family:monospace;font-size:12px;color:#666;white-space:pre-wrap;word-wrap:break-word}}
.tool-input summary{{color:#888}}
.tool-result{{background:#f0fdf4;border-top:1px solid #e5e5e5;padding:10px 14px;font-family:monospace;font-size:12px;color:#166534;white-space:pre-wrap;word-wrap:break-word;max-height:600px;overflow-y:auto}}
.tool-result summary{{color:#16a34a}}
.tool-result-error{{background:#fef2f2;color:#991b1b}}
.filters{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:10px}}
.filters-label{{font-size:12px;color:#888;font-weight:500;text-transform:uppercase;letter-spacing:0.5px}}
.toggle{{display:inline-flex;align-items:center;gap:6px;padding:5px 12px;font-size:12px;font-weight:500;border-radius:20px;border:1px solid #e0e0e0;background:#fff;color:#888;cursor:pointer;user-select:none;transition:all 0.15s}}
.toggle:hover{{border-color:#bbb;color:#555}}
.toggle .dot{{width:8px;height:8px;border-radius:50%;background:#ccc;transition:background 0.15s}}
.toggle.active{{border-color:#7c3aed;color:#4a2d8a;background:#f5f0ff}}
.toggle.active .dot{{background:#7c3aed}}
.hidden-by-filter{{display:none}}
</style>
</head>
<body>
<script>
let matches=[],currentMatch=-1;
const activeFilters=new Set(['user','assistant','thinking','tools','system']);

function toggleFilter(type){{
  const btn=document.getElementById('filter-'+type);if(!btn)return;
  if(activeFilters.has(type)){{activeFilters.delete(type);btn.classList.remove('active')}}
  else{{activeFilters.add(type);btn.classList.add('active')}}
  applyFilters();
  doSearch();
}}

function applyFilters(){{
  document.querySelectorAll('[data-event-type]').forEach(el=>{{
    const t=el.getAttribute('data-event-type');
    if(activeFilters.has(t))el.classList.remove('hidden-by-filter');
    else el.classList.add('hidden-by-filter');
  }});
  document.querySelectorAll('.thinking').forEach(el=>{{
    if(activeFilters.has('thinking'))el.classList.remove('hidden-by-filter');
    else el.classList.add('hidden-by-filter');
  }});
  document.querySelectorAll('.tool-block').forEach(el=>{{
    if(activeFilters.has('tools'))el.classList.remove('hidden-by-filter');
    else el.classList.add('hidden-by-filter');
  }});
}}

function doSearch(){{
  const q=document.getElementById('searchInput').value.trim().toLowerCase();
  const info=document.getElementById('searchInfo');
  document.querySelectorAll('mark').forEach(m=>{{const p=m.parentNode;p.replaceChild(document.createTextNode(m.textContent),m);p.normalize()}});
  matches=[];currentMatch=-1;
  if(!q||q.length<2){{info.textContent='';return}}
  // Expand collapsed details that contain the query (even in hidden sections)
  document.querySelectorAll('details').forEach(d=>{{if(d.textContent.toLowerCase().includes(q))d.open=true}});
  // Search all visible text nodes in transcript-content
  const walker=document.createTreeWalker(document.querySelector('.transcript-content'),NodeFilter.SHOW_TEXT,null,false);
  const nodes=[];
  while(walker.nextNode())nodes.push(walker.currentNode);
  for(const node of nodes){{
    // Skip nodes inside hidden-by-filter elements
    let parent=node.parentElement;
    let hidden=false;
    while(parent){{if(parent.classList&&parent.classList.contains('hidden-by-filter')){{hidden=true;break}}parent=parent.parentElement}}
    if(hidden)continue;
    const t=node.textContent;const l=t.toLowerCase();
    if(!l.includes(q))continue;
    const frag=document.createDocumentFragment();
    let last=0;let idx=l.indexOf(q);
    while(idx!==-1){{
      frag.appendChild(document.createTextNode(t.slice(last,idx)));
      const mk=document.createElement('mark');
      mk.textContent=t.slice(idx,idx+q.length);
      frag.appendChild(mk);matches.push(mk);
      last=idx+q.length;idx=l.indexOf(q,last);
    }}
    frag.appendChild(document.createTextNode(t.slice(last)));
    node.parentNode.replaceChild(frag,node);
  }}
  if(matches.length>0){{
    currentMatch=0;matches[0].classList.add('current');
    matches[0].scrollIntoView({{behavior:'smooth',block:'center'}});
    info.textContent=`1 of ${{matches.length}} matches`;
  }}else{{info.textContent='No matches'}}
}}
function nextMatch(d){{if(!matches.length)return;matches[currentMatch].classList.remove('current');currentMatch=(currentMatch+d+matches.length)%matches.length;matches[currentMatch].classList.add('current');matches[currentMatch].scrollIntoView({{behavior:'smooth',block:'center'}});document.getElementById('searchInfo').textContent=`${{currentMatch+1}} of ${{matches.length}}`}}
document.addEventListener('keydown',function(e){{if(e.key==='Enter'&&document.activeElement.id==='searchInput'){{e.preventDefault();nextMatch(e.shiftKey?-1:1)}}if((e.ctrlKey||e.metaKey)&&e.key==='f'){{e.preventDefault();document.getElementById('searchInput').focus()}}}});
</script>
<div class="search-bar">
<input type="text" id="searchInput" placeholder="Search transcript... (Ctrl+F)" oninput="doSearch()">
<div class="search-info" id="searchInfo"></div>
<div class="filters">
<span class="filters-label">Show:</span>
<button class="toggle active" id="filter-user" onclick="toggleFilter('user')"><span class="dot"></span>User</button>
<button class="toggle active" id="filter-assistant" onclick="toggleFilter('assistant')"><span class="dot"></span>Assistant</button>
<button class="toggle active" id="filter-thinking" onclick="toggleFilter('thinking')"><span class="dot"></span>Thinking</button>
<button class="toggle active" id="filter-tools" onclick="toggleFilter('tools')"><span class="dot"></span>Tools</button>
<button class="toggle active" id="filter-system" onclick="toggleFilter('system')"><span class="dot"></span>System</button>
</div>
</div>
<h1>Session Transcript</h1>
<div class="meta">{total} events</div>
<div class="transcript-content">
"""

    for ev in events:
        ev_type = ev.get("type", "")
        ts = _ts(ev.get("timestamp"))

        if ev_type == "user":
            msg = ev.get("message", {})
            content = msg.get("content", "")
            text_parts = []
            only_tool_results = True
            if isinstance(content, str):
                if content.strip():
                    text_parts.append(content.strip())
                    only_tool_results = False
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "").strip()
                        if t:
                            text_parts.append(t)
                            only_tool_results = False
            if only_tool_results and not text_parts:
                continue
            if text_parts:
                combined = "\n\n".join(text_parts)
                if combined.startswith("<command-"):
                    continue
                turn_count += 1
                page += '<div class="turn-divider"></div>\n'
                page += f'<div class="event user-msg" data-event-type="user"><div class="event-header"><span class="role role-user">User (Turn {turn_count})</span><span class="timestamp">{ts}</span></div>'
                page += f'<div class="text-content">{html_mod.escape(combined)}</div></div>\n'

        elif ev_type == "assistant":
            msg = ev.get("message", {})
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            blocks = ""
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                if btype == "thinking":
                    txt = block.get("thinking", "")
                    if txt:
                        blocks += f'<details class="thinking"><summary>Thinking ({len(txt):,} chars)</summary><div class="text-content">{html_mod.escape(txt)}</div></details>\n'
                elif btype == "text":
                    txt = block.get("text", "")
                    if txt.strip():
                        blocks += f'<div class="text-content">{html_mod.escape(txt)}</div>\n'
                elif btype == "tool_use":
                    tool_id = block.get("id", "")
                    name = block.get("name", "?")
                    inp = block.get("input", {})
                    inp_str = json.dumps(inp, indent=2) if isinstance(inp, dict) else str(inp)
                    blocks += '<div class="tool-block">\n'
                    blocks += f'<div class="tool-header"><span class="tool-name">{html_mod.escape(name)}</span></div>\n'
                    blocks += f'<details class="tool-input"><summary>Input</summary>{html_mod.escape(inp_str)}</details>\n'
                    if tool_id in tr_map:
                        tr = tr_map[tool_id]
                        is_error = tr.get("is_error", False)
                        tr_content = _tool_result_content(tr.get("content", ""))
                        err_cls = " tool-result-error" if is_error else ""
                        blocks += f'<details open class="tool-result{err_cls}"><summary>Result{" (error)" if is_error else ""}</summary>{tr_content}</details>\n'
                    blocks += '</div>\n'
            if blocks:
                page += f'<div class="event assistant-msg" data-event-type="assistant"><div class="event-header"><span class="role role-assistant">Assistant</span><span class="timestamp">{ts}</span></div>{blocks}</div>\n'

        elif ev_type == "system":
            subtype = ev.get("subtype", "")
            content = ev.get("content", "")
            if content:
                meta = ev.get("compactMetadata", {})
                extra = ""
                if meta.get("preTokens"):
                    extra = f' (pre-compact tokens: {meta["preTokens"]:,})'
                page += f'<div class="event system-msg" data-event-type="system"><div class="event-header"><span class="role role-system">System: {html_mod.escape(subtype)}</span><span class="timestamp">{ts}</span></div>'
                page += f'<div class="text-content">{html_mod.escape(str(content))}{extra}</div></div>\n'

    page += "</div>\n</body></html>"

    html_path = str(jsonl_path).replace(".jsonl", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)

    return html_path


def generate_html_viewers():
    """Generate HTML viewers for all deduplicated session transcripts."""
    logs_dir = Path("logs")
    if not logs_dir.exists():
        return

    generated = 0
    for model in ["model_a", "model_b"]:
        model_dir = logs_dir / model
        if not model_dir.exists():
            continue
        # Find deduplicated session files (not _raw)
        for jsonl_file in model_dir.glob("session_*.jsonl"):
            if "_raw.jsonl" in jsonl_file.name:
                continue
            try:
                html_path = generate_transcript_html(jsonl_file)
                if html_path:
                    print_success(f"Generated HTML viewer: {html_path}")
                    generated += 1
            except Exception as e:
                print_warning(f"Failed to generate HTML for {jsonl_file.name}: {e}")

    if generated > 0:
        print_info(f"Generated {generated} HTML transcript viewer(s)")


def _obfuscate_value(value):
    """Obfuscate a sensitive string value, keeping first 2 chars visible."""
    if not isinstance(value, str) or len(value) == 0:
        return "****"
    if len(value) <= 2:
        return "****"
    return value[:2] + "****"


def _is_sensitive_key(key):
    """Check if a key name matches sensitive patterns."""
    key_upper = key.upper()
    return any(pattern in key_upper for pattern in SENSITIVE_KEY_PATTERNS)


def _obfuscate_sensitive_block(obj, block_type):
    """Obfuscate values in a sensitive block (env, headers, oauth).

    For 'env' blocks: only obfuscate values whose key matches sensitive patterns.
    For 'headers' and 'oauth' blocks: obfuscate ALL values (almost always credentials).
    """
    if not isinstance(obj, dict):
        return obj
    result = {}
    for k, v in obj.items():
        if block_type in ("headers", "oauth"):
            # Blanket redact all values in headers/oauth
            result[k] = _obfuscate_value(v) if isinstance(v, str) else v
        elif block_type == "env":
            # Only redact values with sensitive key names
            if _is_sensitive_key(k) and isinstance(v, str):
                result[k] = _obfuscate_value(v)
            else:
                result[k] = v
        else:
            result[k] = v
    return result


def _obfuscate_settings_recursive(obj):
    """Recursively walk a parsed JSON object and obfuscate sensitive blocks.

    Targets any dict key named 'env', 'headers', or 'oauth' and obfuscates
    their values according to the block type rules.
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k in ("env", "headers", "oauth") and isinstance(v, dict):
                result[k] = _obfuscate_sensitive_block(v, k)
            else:
                result[k] = _obfuscate_settings_recursive(v)
        return result
    elif isinstance(obj, list):
        return [_obfuscate_settings_recursive(item) for item in obj]
    else:
        return obj


def capture_settings_for_upload():
    """Capture Claude Code settings files into a settings/ folder for upload.

    Captures:
    - model_a/.claude/settings.local.json (mandatory — blocks submission if missing)
    - model_b/.claude/settings.local.json (mandatory — blocks submission if missing)
    - ~/.claude/settings.json (optional — warning if missing, obfuscated)
    - ~/.claude.json (optional — warning if missing, obfuscated, behind CAPTURE_USER_MCP_CONFIG flag)

    Returns True if mandatory files are present, False otherwise.
    """
    settings_dir = Path("settings")
    settings_dir.mkdir(exist_ok=True)

    mandatory_ok = True

    # 1. Copy local project settings (mandatory, no obfuscation — these are ours)
    for model in ["model_a", "model_b"]:
        local_settings = Path(model) / ".claude" / "settings.local.json"
        dest = settings_dir / f"{model}_settings_local.json"
        if local_settings.exists():
            try:
                shutil.copy2(str(local_settings), str(dest))
                print_success(f"Captured {model} local settings")
            except Exception as e:
                print_warning(f"Failed to copy {model} local settings: {e}")
                mandatory_ok = False
        else:
            print_error(f"Missing mandatory file: {local_settings} — cannot submit without it")
            mandatory_ok = False

    if not mandatory_ok:
        return False

    # 2. Capture global user settings (optional, obfuscated)
    global_settings_path = Path.home() / ".claude" / "settings.json"
    if global_settings_path.exists():
        try:
            with open(global_settings_path, 'r', encoding='utf-8') as f:
                global_settings = json.load(f)
            obfuscated = _obfuscate_settings_recursive(global_settings)
            dest = settings_dir / "user_settings.json"
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(obfuscated, f, indent=2)
            print_success("Captured global user settings (sensitive values obfuscated)")
        except Exception as e:
            print_warning(f"Failed to read global settings at {global_settings_path}: {e}")
    else:
        print_warning(f"No global Claude settings found at {global_settings_path} — this is fine if you haven't customized global settings")

    # 3. Capture global Claude config (mandatory — this file always exists after any Claude Code usage)
    if CAPTURE_USER_MCP_CONFIG:
        claude_json_path = Path.home() / ".claude.json"
        if claude_json_path.exists():
            try:
                with open(claude_json_path, 'r', encoding='utf-8') as f:
                    claude_json = json.load(f)
                obfuscated = _obfuscate_settings_recursive(claude_json)
                dest = settings_dir / "user_claude_config.json"
                with open(dest, 'w', encoding='utf-8') as f:
                    json.dump(obfuscated, f, indent=2)
                print_success("Captured global Claude config (sensitive values obfuscated)")
            except Exception as e:
                print_error(f"Failed to read Claude config at {claude_json_path}: {e}")
        else:
            print_error(f"Claude config not found at {claude_json_path} — this file is created automatically by Claude Code and must be present to submit")

    print_info("Your Claude Code settings will be submitted for cross-verification of your session.")

    return True


def get_file_list_for_upload():
    """Get list of all files to upload."""
    upload_files = []

    # Always include manifest
    upload_files.append("manifest.json")

    # Include all logs (JSONL and HTML)
    logs_dir = Path("logs")
    if logs_dir.exists():
        for log_file in logs_dir.rglob("*.jsonl"):
            # Convert to forward slashes for consistent paths
            upload_files.append(str(log_file).replace('\\', '/'))
        for html_file in logs_dir.rglob("*.html"):
            upload_files.append(str(html_file).replace('\\', '/'))
    
    # Create and include snapshots zip file (instead of individual files)
    snapshots_zip = create_snapshots_zip()
    if snapshots_zip:
        upload_files.append(snapshots_zip)
    # Include snapshot inventory (lists what's inside the zip)
    if Path("snapshots_inventory.json").exists():
        upload_files.append("snapshots_inventory.json")
    
    # Include model configurations (but not the full repos)
    for model in ["model_a", "model_b"]:
        claude_dir = Path(model) / ".claude"
        if claude_dir.exists():
            for config_file in claude_dir.rglob("*"):
                if config_file.is_file():
                    # Skip cache files, bytecode, and system files
                    file_path_str = str(config_file)
                    file_name = config_file.name
                    
                    # Skip patterns
                    if '__pycache__' in file_path_str:
                        continue
                    if file_name.endswith(('.pyc', '.pyo', '.DS_Store')):
                        continue
                    if file_name in {'.DS_Store', 'Thumbs.db', 'desktop.ini'}:
                        continue
                    
                    # Convert to forward slashes for consistent paths
                    upload_files.append(file_path_str.replace('\\', '/'))

    # Include captured settings files
    settings_dir = Path("settings")
    if settings_dir.exists():
        for settings_file in settings_dir.glob("*.json"):
            upload_files.append(str(settings_file).replace('\\', '/'))

    return upload_files

def compress_file_to_gzip(local_file_path):
    """Compress a file using gzip and return the path to the compressed file.
    
    Args:
        local_file_path: Path to the file to compress
        
    Returns:
        str: Path to the compressed file (original_path.gz)
    """
    gz_path = f"{local_file_path}.gz"
    try:
        with open(local_file_path, 'rb') as f_in:
            with gzip.open(gz_path, 'wb', compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        original_size = Path(local_file_path).stat().st_size
        compressed_size = Path(gz_path).stat().st_size
        ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
        print_info(f"  Compressed {local_file_path} -> {gz_path} ({ratio:.1f}% reduction)")
        return gz_path
    except Exception as e:
        print_warning(f"Failed to compress {local_file_path}: {e}")
        return None

def upload_file_to_supabase(local_file_path, remote_file_path):
    """Upload a single file to Supabase storage using Tus resumable upload (supports large files).
    
    Includes retry logic with exponential backoff for network/server errors.
    TUS protocol automatically resumes partial uploads.
    On 403 error for .jsonl files, automatically compresses to .gz and retries.
    
    Returns:
        tuple: (success: bool, error_code: str or None)
        error_code can be '403', '409', '500', or 'other'
    """
    try:
        file_path = Path(local_file_path)
        file_size = file_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        print_info(f"  File size: {file_size_mb:.2f} MB")
        
        # Retry loop for network/server errors with exponential backoff
        # More retries and longer backoff for 500 errors (Supabase intermittent issues)
        max_upload_retries = 5
        last_error = None
        is_server_error = False
        
        for retry_attempt in range(max_upload_retries):
            try:
                # Create Tus client for resumable uploads
                # Use direct storage hostname for better performance (per Supabase docs)
                my_client = tus_client.TusClient(
                    f"{SUPABASE_STORAGE_URL}/storage/v1/upload/resumable",
                    headers={
                        "apikey": ANON_KEY
                    }
                )
                
                # Open file and upload with chunking
                # IMPORTANT: Chunk size MUST be exactly 6MB for Supabase Storage
                # Determine content type from file extension
                content_type_map = {
                    ".html": "text/html",
                    ".json": "application/json",
                    ".jsonl": "application/jsonl",
                    ".zip": "application/zip",
                    ".patch": "text/plain",
                    ".py": "text/plain",
                    ".gz": "application/gzip",
                }
                file_ext = Path(local_file_path).suffix.lower()
                content_type = content_type_map.get(file_ext, "application/octet-stream")

                with open(local_file_path, 'rb') as file_stream:
                    uploader = my_client.uploader(
                        file_stream=file_stream,
                        chunk_size=TUS_CHUNK_SIZE,  # 6MB - required by Supabase
                        metadata={
                            "bucketName": BUCKET_NAME,
                            "objectName": remote_file_path,
                            "contentType": content_type,
                            "cacheControl": "3600"
                        }
                    )
                    uploader.upload()
                
                # Upload successful
                return (True, None)
                
            except (ConnectionError, OSError, TimeoutError) as network_error:
                # Network/SSL/timeout errors - retry with exponential backoff
                last_error = network_error
                is_server_error = False
                
                if retry_attempt < max_upload_retries - 1:
                    # Calculate exponential backoff: 2s, 4s, 8s, 16s
                    backoff_delay = 2 ** (retry_attempt + 1)
                    print_info(f"  Network error, retrying in {backoff_delay}s... (attempt {retry_attempt + 1}/{max_upload_retries})")
                    time.sleep(backoff_delay)
                    continue
                else:
                    # Final retry failed
                    print_warning(f"Failed to upload {local_file_path} after {max_upload_retries} attempts: {network_error}")
                    return (False, "other")
                    
            except Exception as upload_error:
                error_msg = str(upload_error).lower()
                
                # Check for server errors (5xx) - these are retryable
                is_5xx = any(f'status {code}' in error_msg or f'status={code}' in error_msg 
                            for code in ['500', '502', '503', '504'])
                
                # Check for network-related errors
                is_network = any(keyword in error_msg 
                                for keyword in ['ssl', 'connection', 'timeout', 'network', 'refused', 'reset', 'eof'])
                
                if is_5xx or is_network:
                    last_error = upload_error
                    is_server_error = is_5xx
                    
                    if retry_attempt < max_upload_retries - 1:
                        # Longer backoff for server errors: 3s, 6s, 12s, 24s
                        if is_5xx:
                            backoff_delay = 3 * (2 ** retry_attempt)
                            print_info(f"  Server error (5xx), retrying in {backoff_delay}s... (attempt {retry_attempt + 1}/{max_upload_retries})")
                        else:
                            backoff_delay = 2 ** (retry_attempt + 1)
                            print_info(f"  Connection error, retrying in {backoff_delay}s... (attempt {retry_attempt + 1}/{max_upload_retries})")
                        time.sleep(backoff_delay)
                        continue
                    else:
                        # Final retry failed
                        print_warning(f"Failed to upload {local_file_path} after {max_upload_retries} attempts: {upload_error}")
                        if is_5xx:
                            return (False, "500")
                        return (False, "other")
                else:
                    # Non-retryable error (like 403/409) - propagate to outer catch
                    raise
        
        # Should not reach here, but handle edge case
        if last_error:
            print_warning(f"Failed to upload {local_file_path}: {last_error}")
            if is_server_error:
                return (False, "500")
            return (False, "other")
            
    except Exception as e:
        error_msg = str(e)
        
        # Detect error type for version retry logic
        if "403" in error_msg or "forbidden" in error_msg.lower():
            # On 403 for .jsonl files, try compressing to .gz and retry
            if local_file_path.endswith(".jsonl") and not local_file_path.endswith(".gz"):
                print_info(f"  403 error for {local_file_path} - attempting gzip compression and retry...")
                gz_path = compress_file_to_gzip(local_file_path)
                if gz_path:
                    # Retry upload with compressed file
                    gz_remote_path = f"{remote_file_path}.gz"
                    print_info(f"  Retrying upload as {gz_remote_path}...")
                    return upload_file_to_supabase(gz_path, gz_remote_path)
            
            print_warning(f"Failed to upload {local_file_path}: {e}")
            return (False, "403")
        elif "409" in error_msg or "conflict" in error_msg.lower():
            print_warning(f"Failed to upload {local_file_path}: {e}")
            return (False, "409")
        else:
            print_warning(f"Failed to upload {local_file_path}: {e}")
            return (False, "other")

def upload_experiment_data(task_id, user_folder, upload_files, manifest):
    """Upload all experiment files to Supabase with simple parallelization (5 workers).
    
    Includes automatic retry for files that fail with 500 server errors.
    
    Returns:
        tuple: (success: bool, had_conflict_errors: bool, uploaded_count: int)
        had_conflict_errors is True if any 403/409 errors occurred
        uploaded_count is the number of successfully uploaded files
    """
    print_info(f"Uploading {len(upload_files)} files...")
    
    uploaded_count = 0
    failed_files = []
    failed_files_with_500 = []  # Track files that failed with 500 errors specifically
    conflict_error_codes = set()  # Track error codes
    
    def upload_batch(files_to_upload):
        """Upload a batch of files and return results."""
        nonlocal uploaded_count
        batch_failed = []
        batch_failed_500 = []
        batch_error_codes = set()
        
        # Use ThreadPoolExecutor with 3 workers for parallel uploads
        # Reduced from 5 to avoid overwhelming Supabase's connection pool (causes 500 errors)
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all upload tasks
            future_to_file = {}
            for local_file in files_to_upload:
                # Create remote path: TASK_ID/local_file_path (normalize path separators for cross-platform)
                normalized_file_path = local_file.replace('\\', '/')  # Convert Windows backslashes to forward slashes
                remote_file_path = f"{task_id}/{normalized_file_path}"
                
                future = executor.submit(upload_file_to_supabase, local_file, remote_file_path)
                future_to_file[future] = local_file
            
            # Process completed uploads as they finish
            for future in as_completed(future_to_file):
                local_file = future_to_file[future]
                print_info(f"Uploading {local_file}...")
                
                try:
                    success, error_code = future.result()
                    if success:
                        uploaded_count += 1
                        print_success(f"Uploaded {local_file}")
                    else:
                        batch_failed.append(local_file)
                        if error_code:
                            batch_error_codes.add(error_code)
                            if error_code == "500":
                                batch_failed_500.append(local_file)
                except Exception as e:
                    print_warning(f"Exception uploading {local_file}: {e}")
                    batch_failed.append(local_file)
        
        return batch_failed, batch_failed_500, batch_error_codes
    
    # First upload attempt
    failed_files, failed_files_with_500, conflict_error_codes = upload_batch(upload_files)
    
    # If we have 500 errors, automatically retry those files after a delay
    if failed_files_with_500:
        max_500_retries = 2
        for retry_round in range(max_500_retries):
            print("\n" + "=" * 60)
            print(f"🔄 {len(failed_files_with_500)} files failed with server errors (500).")
            print(f"   Waiting 10 seconds before retry {retry_round + 1}/{max_500_retries}...")
            print("=" * 60)
            time.sleep(10)
            
            print_info(f"Retrying {len(failed_files_with_500)} files...")
            
            # Retry only the 500-failed files
            retry_failed, retry_failed_500, retry_error_codes = upload_batch(failed_files_with_500)
            
            # Update tracking
            # Remove successfully uploaded files from failed_files
            successfully_retried = set(failed_files_with_500) - set(retry_failed)
            failed_files = [f for f in failed_files if f not in successfully_retried]
            
            # Update 500 tracking for next round
            failed_files_with_500 = retry_failed_500
            conflict_error_codes.update(retry_error_codes)
            
            if not failed_files_with_500:
                print_success("All server-error files uploaded successfully on retry!")
                break
    
    if failed_files:
        print_warning(f"Upload failed for {len(failed_files)} files:\n" +
                     "\n".join(f"  - {file}" for file in failed_files))
        if "500" in conflict_error_codes or "other" in conflict_error_codes or (not conflict_error_codes and failed_files):
            print("\n" + "=" * 60)
            print("⚠️  Some files failed to upload due to a Supabase server error.")
            print("   This is a temporary issue on Supabase's side, not a problem")
            print("   with your data.")
            print("")
            print("   What to do:")
            print("   1. Wait a few minutes and run submit.py again")
            print("   2. If it keeps failing, upload your experiment folder to")
            print("      Google Drive and share the link with the team")
            print("=" * 60 + "\n")

    print_success(f"Successfully uploaded {uploaded_count}/{len(upload_files)} files")
    
    had_conflict_errors = bool(conflict_error_codes & {"403", "409"})
    return (len(failed_files) == 0, had_conflict_errors, uploaded_count)

def create_submission_summary(manifest, user_folder, upload_files):
    """Create a submission summary file."""
    summary = {
        "submission_timestamp": datetime.now(timezone.utc).isoformat(),
        "user_folder_name": user_folder,
        "expert_name": manifest["expert_name"],
        "task_id": manifest["task_id"],
        "experiment_timestamp": manifest["timestamp"],
        "last_submission_version": manifest.get("last_submission_version"),
        "uploaded_files_count": len(upload_files),
        "uploaded_files": upload_files,
        "submission_metadata": {
            "submit_script_version": "2.0.0",
            "upload_path": f"{user_folder}/"
        }
    }
    
    try:
        with open("submission_summary.json", 'w') as f:
            json.dump(summary, f, indent=2)
        
        # Upload the summary as well (normalize path for cross-platform)
        remote_path = f"{user_folder}/submission_summary.json"
        success, _ = upload_file_to_supabase("submission_summary.json", remote_path)
        if success:
            print_success("Created and uploaded submission summary")
            return True
        else:
            print_warning("Created submission summary but failed to upload it")
            return False
            
    except Exception as e:
        print_warning(f"Failed to create submission summary: {e}")
        return False

def cleanup_temp_files():
    """Remove temporary files created during submission."""
    temp_files = ["snapshots.zip", "submission_summary.json", "snapshots_inventory.json"]

    for temp_file in temp_files:
        if Path(temp_file).exists():
            try:
                Path(temp_file).unlink()
                print_info(f"Cleaned up temporary file: {temp_file}")
            except Exception as e:
                print_warning(f"Failed to clean up {temp_file}: {e}")

    # Clean up settings directory
    settings_dir = Path("settings")
    if settings_dir.exists():
        try:
            shutil.rmtree(settings_dir)
            print_info("Cleaned up settings directory")
        except Exception as e:
            print_warning(f"Failed to clean up settings directory: {e}")
    
    # Clean up any .gz files created during 403 retry
    logs_dir = Path("logs")
    if logs_dir.exists():
        for gz_file in logs_dir.rglob("*.jsonl.gz"):
            try:
                gz_file.unlink()
                print_info(f"Cleaned up compressed file: {gz_file}")
            except Exception as e:
                print_warning(f"Failed to clean up {gz_file}: {e}")

def main():
    """Main submission function."""
    # Check for --dry-run flag
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if dry_run:
        print("📤 Claude Code A/B Testing Submission (DRY RUN)")
        print("=" * 50)
        print_info("DRY RUN MODE - No files will be uploaded")
    else:
        print("📤 Claude Code A/B Testing Submission")
        print("=" * 50)

    try:
        # Download sprint configuration
        print_info("Loading sprint configuration...")
        sprint_config = download_sprint_config()
        if not sprint_config:
            print_error("Failed to load sprint configuration")
        
        sprint_folder = sprint_config.get("submission", {}).get("sprint_folder")
        if not sprint_folder:
            print_error("Invalid sprint configuration: missing sprint_folder")
        
        # Read manifest
        print_info("Reading experiment manifest...")
        manifest = read_manifest()
        
        expert_name = manifest["expert_name"]
        task_id = manifest["task_id"]
        
        print_info(f"Expert: {expert_name}")
        print_info(f"Task ID: {task_id}")

        # Take end snapshots before validation
        print_info("Taking end snapshots...")
        take_end_snapshots()

        # Merge multiple sessions if needed
        print_info("Checking for multiple sessions to merge...")
        import subprocess
        merge_script = Path(__file__).parent / "merge_sessions.py"
        if merge_script.exists():
            result = subprocess.run(
                [sys.executable, str(merge_script), "."],
                capture_output=False
            )
            if result.returncode != 0:
                print_warning("Session merge encountered issues, continuing anyway...")
        else:
            print_warning(f"merge_sessions.py not found at {merge_script}")

        # Validate experiment files
        print_info("Validating experiment files...")
        validate_experiment_files()
        
        # Capture Claude Code settings for cross-verification
        print_info("Capturing Claude Code settings...")
        if not capture_settings_for_upload():
            print_error("Failed to capture mandatory settings files — cannot submit")

        # Generate HTML transcript viewers before upload
        print_info("Generating HTML transcript viewers...")
        generate_html_viewers()

        # Get list of files to upload
        print_info("Preparing file list for upload...")
        upload_files = get_file_list_for_upload()
        
        if not upload_files:
            print_error("No files found to upload")
        
        print_info(f"Found {len(upload_files)} files to upload")
        
        # Determine attempt version based on last successful submission
        last_version = manifest.get("last_submission_version")
        if last_version is None:
            # Never submitted before - start at version 0
            attempt_version = 0
            print_info("First submission attempt - using version 0")
        else:
            # Previously submitted - start 1 higher than last successful
            attempt_version = last_version + 1
            print_info(f"Last submission was version {last_version} - starting with version {attempt_version}")
        
        upload_path = get_upload_path_from_version(sprint_folder, task_id, attempt_version)
        
        # Confirm upload
        print(f"\n📋 Upload Summary:")
        print(f"  Expert: {expert_name}")
        print(f"  Task ID: {task_id}")
        print(f"  Files to upload: {len(upload_files)}")
        print(f"  Attempt version: {attempt_version}")
        if last_version is not None:
            print(f"  Last submission version: {last_version}")
        
        # In dry-run mode, skip upload
        if dry_run:
            print("\n" + "=" * 50)
            print_success("DRY RUN VALIDATION COMPLETE")
            print("=" * 50)
            print_info("All validation checks passed!")
            print_info(f"Files that would be uploaded: {len(upload_files)}")
            for f in upload_files:
                print(f"  - {f}")
            print("\nRun without --dry-run to actually upload.")
            cleanup_temp_files()
            sys.exit(0)

        confirm = input(f"\nProceed with upload? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("❌ Upload cancelled by user")
            sys.exit(0)

        # Save version to manifest BEFORE uploading
        # This ensures each upload attempt gets a fresh folder, avoiding partial upload issues
        print_info(f"Saving version {attempt_version} to manifest before upload...")
        if not update_manifest_version("manifest.json", attempt_version):
            print_warning("Failed to update manifest with last_submission_version")
        
        # Re-read manifest and regenerate file list to include updated version
        manifest = read_manifest()
        upload_files = get_file_list_for_upload()

        # Upload with retry logic (max 5 attempts)
        max_attempts = 5
        upload_successful = False
        final_upload_path = None
        
        for attempt in range(max_attempts):
            # Calculate upload path for this attempt
            upload_path = get_upload_path_from_version(sprint_folder, task_id, attempt_version)
            
            if attempt == 0:
                print_info(f"Starting upload (attempt {attempt + 1}/{max_attempts})...")
            else:
                print_info(f"Retrying upload with version {attempt_version} (attempt {attempt + 1}/{max_attempts})...")
            
            # Attempt upload
            success, had_conflict_errors, uploaded_count = upload_experiment_data(upload_path, upload_path, upload_files, manifest)
            
            if success:
                # All files uploaded successfully
                print_success("Upload successful!")
                upload_successful = True
                final_upload_path = upload_path
                break
            elif attempt < max_attempts - 1:
                # Any failure with attempts left - increment version and retry
                # This ensures each attempt gets a fresh folder, avoiding partial upload issues
                print_warning(f"Upload failed at version {attempt_version}. Incrementing to version {attempt_version + 1} for retry...")
                
                # Increment attempt_version for next retry
                attempt_version += 1
                
                # Update manifest with new version before retrying
                if not update_manifest_version("manifest.json", attempt_version):
                    print_warning("Failed to update manifest with last_submission_version")
                
                # Recreate file list (to include updated manifest)
                upload_files = get_file_list_for_upload()
            else:
                # Final attempt failed - stop trying
                print_error(f"Upload failed after {max_attempts} attempts")
                break
        
        if not upload_successful:
            # Clean up temporary files before exiting
            cleanup_temp_files()
            print_error("Upload failed after all attempts")
        
        # Create submission summary
        manifest = read_manifest()  # Re-read to get final version
        create_submission_summary(manifest, final_upload_path, upload_files)
        
        # Clean up temporary files after successful upload
        cleanup_temp_files()
        
        # Success message
        print("\n" + "=" * 50)
        print_success("Submission completed successfully!")
        print(f"\n📊 Your experiment data has been uploaded!")
        print(f"   Files: {len(upload_files)} files uploaded")
        final_saved_version = manifest.get('last_submission_version')
        if final_saved_version is not None:
            print(f"   Submission version: {final_saved_version}")
        print("\n🎉 Thank you for your contribution!")
        
    except KeyboardInterrupt:
        print("\n❌ Submission cancelled by user")
        cleanup_temp_files()
        sys.exit(1)
    except Exception as e:
        cleanup_temp_files()
        print_error(f"Unexpected error during submission: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
