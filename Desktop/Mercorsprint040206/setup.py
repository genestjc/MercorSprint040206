#!/usr/bin/env python3
"""
Claude Code A/B Testing Setup Script (Cross-Platform)
Initializes experiment environment with model assignments and downloads required files.
Works on Windows, macOS, and Linux.
"""
import os
import sys
import json
import subprocess
import requests
import shutil
import random
import platform
from datetime import datetime, timezone
from pathlib import Path

# Check Python version first
if sys.version_info < (3, 7):
    print("[ERROR] Python 3.7 or higher is required", file=sys.stderr)
    print(f"[ERROR] Current version: {sys.version}", file=sys.stderr)
    sys.exit(1)

# Detect platform
IS_WINDOWS = platform.system() == 'Windows'

# Supabase configuration
SUPABASE_URL = "https://sdippjgffrptdvlmlurv.supabase.co"
ANON_KEY = "sb_publishable_ReTMY8aH1JgV3pPiOnXKAA_ZVcYIimL"
BUCKET_NAME = "code-preferences-setup-files-v2"

def print_error(message):
    """Print error message and exit."""
    prefix = "[ERROR]" if IS_WINDOWS else "❌ ERROR:"
    print(f"{prefix} {message}", file=sys.stderr)
    sys.exit(1)

def print_success(message):
    """Print success message."""
    prefix = "[OK]" if IS_WINDOWS else "✅"
    print(f"{prefix} {message}")

def print_info(message):
    """Print info message."""
    prefix = "[INFO]" if IS_WINDOWS else "ℹ️ "
    print(f"{prefix} {message}")

def validate_input(prompt, validator=None, error_msg="Invalid input"):
    """Get and validate user input."""
    while True:
        try:
            value = input(f"{prompt}: ").strip()
            if not value:
                prefix = "[ERROR]" if IS_WINDOWS else "❌"
                print(f"{prefix} {error_msg}: Input cannot be empty")
                continue
            if validator and not validator(value):
                prefix = "[ERROR]" if IS_WINDOWS else "❌"
                print(f"{prefix} {error_msg}")
                continue
            return value
        except KeyboardInterrupt:
            prefix = "[CANCELLED]" if IS_WINDOWS else "❌"
            print(f"\n{prefix} Setup cancelled by user")
            sys.exit(1)

def validate_repo_url(url):
    """Validate repository URL format - only SSH GitHub repos supported."""
    if not url:
        return False
    # Only support SSH GitHub URLs
    return url.startswith('git@github.com:') and url.endswith('.git')


def download_sprint_config():
    """Download sprint configuration from Supabase."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/config/sprint_config.json"
    headers = {
        "apikey": ANON_KEY,
        "apikey": ANON_KEY
    }
    
    try:
        print_info("Downloading sprint configuration...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        config = response.json()
        print_success("Sprint configuration loaded")
        return config
        
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to download sprint configuration: {e}")
        return None
    except json.JSONDecodeError as e:
        print_error(f"Failed to parse sprint configuration: {e}")
        return None

def download_file_from_supabase(file_path, local_path):
    """Download a file from Supabase storage."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{file_path}"
    headers = {
        "apikey": ANON_KEY,
        "apikey": ANON_KEY
    }
    
    try:
        print_info(f"Downloading {file_path}...")
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Ensure directory exists (only if there's a directory component)
        local_dir = os.path.dirname(local_path)
        if local_dir:  # Only create directory if path has a directory component
            os.makedirs(local_dir, exist_ok=True)
        
        with open(local_path, 'wb') as f:
            f.write(response.content)
        
        print_success(f"Downloaded {file_path}")
        return True
        
    except requests.exceptions.RequestException as e:
        print_error(f"Failed to download {file_path}: {e}")
        return False

def clone_repository(repo_url, target_dir):
    """Clone repository to target directory."""
    try:
        print_info(f"Cloning repository to {target_dir}...")
        result = subprocess.run(
            ['git', 'clone', repo_url, target_dir],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print_error(f"Git clone failed: {result.stderr}")
            return False
            
        print_success(f"Repository cloned to {target_dir}")
        return True
        
    except Exception as e:
        print_error(f"Failed to clone repository: {e}")
        return False

def download_claude_directory():
    """Download the complete .claude directory from Supabase (cross-platform)."""
    claude_files = [
        "claude/settings.local.json",
        "claude/hooks/claude_code_capture_utils.py",
        "claude/hooks/capture_session_event.py",
        "claude/hooks/check_auto_mode.py",
        "claude/hooks/process_transcript.py"
    ]
    
    temp_claude_dir = Path("temp_claude")
    temp_claude_dir.mkdir(exist_ok=True)
    
    try:
        for file_path in claude_files:
            local_path = temp_claude_dir / file_path.replace("claude/", "")
            if not download_file_from_supabase(file_path, str(local_path)):
                return False
        
        # Make hook scripts executable (Unix/Mac only)
        if not IS_WINDOWS:
            hooks_dir = temp_claude_dir / "hooks"
            if hooks_dir.exists():
                for script in hooks_dir.glob("*.py"):
                    os.chmod(script, 0o755)
        
        return True
        
    except Exception as e:
        print_error(f"Failed to download .claude directory: {e}")
        return False

def install_claude_directory(target_repo_dir, code_name, anthropic_base_url, litellm_master_key, task_id="", expert_name="", always_thinking_enabled=False, auto_mode_enabled=False, use_code_names=True):
    """Install .claude directory in target repository with configuration."""
    try:
        claude_target = Path(target_repo_dir) / ".claude"
        temp_claude = Path("temp_claude")

        # Copy .claude directory
        if claude_target.exists():
            shutil.rmtree(claude_target)
        shutil.copytree(temp_claude, claude_target)

        # Update settings.local.json with code name and credentials
        settings_file = claude_target / "settings.local.json"
        if settings_file.exists():
            with open(settings_file, 'r') as f:
                settings = json.load(f)

            # Replace placeholders
            settings["model"] = code_name

            # Enforce thinking mode if configured in sprint_config
            if always_thinking_enabled:
                settings["alwaysThinkingEnabled"] = True

            # Enforce auto mode if configured in sprint_config
            if auto_mode_enabled:
                if "permissions" not in settings:
                    settings["permissions"] = {}
                settings["permissions"]["defaultMode"] = "auto"

            # Only set proxy env vars when using code names (LiteLLM proxy)
            if use_code_names:
                if "env" not in settings:
                    settings["env"] = {}

                settings["env"]["ANTHROPIC_AUTH_TOKEN"] = litellm_master_key
                settings["env"]["ANTHROPIC_BASE_URL"] = anthropic_base_url

                # Pass task_id and expert_name as a single custom header so the LiteLLM proxy can tag metrics
                # ANTHROPIC_CUSTOM_HEADERS only supports one header, so we encode both values in one
                meta_parts = []
                if task_id:
                    meta_parts.append(f"task_id={task_id}")
                if expert_name:
                    meta_parts.append(f"expert_name={expert_name}")
                if meta_parts:
                    settings["env"]["ANTHROPIC_CUSTOM_HEADERS"] = f"X-Session-Meta: {';'.join(meta_parts)}"
            else:
                # Remove placeholder env vars so they don't conflict with /login auth
                settings.pop("env", None)
            
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
        
        # Note: We don't modify .gitignore since we exclude .claude/ from git operations anyway
        
        print_success(f"Installed .claude directory in {target_repo_dir}")
        return True
        
    except Exception as e:
        print_error(f"Failed to install .claude directory: {e}")
        return False

def download_submit_script():
    """Download the submit script and dependencies from Supabase."""
    # Download submit.py
    success = download_file_from_supabase("submit.py", "submit.py")
    if not success:
        return False

    # Download snapshot_utils.py (required by submit.py)
    if not download_file_from_supabase("snapshot_utils.py", "snapshot_utils.py"):
        return False

    # Download merge_sessions.py (called by submit.py)
    if not download_file_from_supabase("merge_sessions.py", "merge_sessions.py"):
        return False

    # Download backfill_session_summary.py (required by submit.py)
    if not download_file_from_supabase("backfill_session_summary.py", "backfill_session_summary.py"):
        return False

    # Download claude-dev launcher script (platform-specific)
    if IS_WINDOWS:
        if not download_file_from_supabase("claude-dev.ps1", "claude-dev.ps1"):
            return False
    else:
        if not download_file_from_supabase("claude-dev", "claude-dev"):
            return False

    # Make scripts executable (Unix/Mac only)
    if not IS_WINDOWS:
        os.chmod("submit.py", 0o755)
        os.chmod("merge_sessions.py", 0o755)
        os.chmod("claude-dev", 0o755)

    return True

def create_manifest(expert_name, task_id, repo_url, assignments, code_names, setup_duration, base_commit_sha=None):
    """Create manifest.json file."""
    manifest = {
        "expert_name": expert_name,
        "task_id": task_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo_url": repo_url,
        "base_commit": base_commit_sha,
        "assignments": assignments,
        "code_names": code_names,
        "setup_verified": True,
        "experiment_metadata": {
            "setup_script_version": "2.1.0-v2",
            "platform": platform.system(),
            "claude_version_downloaded": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "setup_duration_seconds": round(setup_duration, 2)
        }
    }
    
    try:
        with open("manifest.json", 'w') as f:
            json.dump(manifest, f, indent=2)
        print_success("Created manifest.json")
        return True
    except Exception as e:
        print_error(f"Failed to create manifest.json: {e}")
        return False

def verify_setup():
    """Verify that all required files and directories exist."""
    required_items = [
        ("manifest.json", "file"),
        ("submit.py", "file"),
        ("model_a", "dir"),
        ("model_b", "dir"),
        ("model_a/.claude", "dir"),
        ("model_b/.claude", "dir"),
        ("model_a/.claude/settings.local.json", "file"),
        ("model_b/.claude/settings.local.json", "file")
    ]
    
    missing_items = []
    for item, item_type in required_items:
        path = Path(item)
        if item_type == "file" and not path.is_file():
            missing_items.append(f"File: {item}")
        elif item_type == "dir" and not path.is_dir():
            missing_items.append(f"Directory: {item}")
    
    if missing_items:
        print_error(f"Setup verification failed. Missing items:\n" + "\n".join(f"  - {item}" for item in missing_items))
        return False
    
    print_success("Setup verification passed - all required files and directories exist")
    return True

def cleanup_temp_files():
    """Clean up temporary files."""
    temp_claude = Path("temp_claude")
    if temp_claude.exists():
        shutil.rmtree(temp_claude)

def ensure_start_snapshots():
    """Create start snapshots for model_a and model_b if they don't exist."""
    # Lazy import - snapshot_utils.py is downloaded by download_submit_script()
    from snapshot_utils import create_repository_snapshot_zip

    snapshots_dir = Path("snapshots")
    snapshots_dir.mkdir(exist_ok=True)

    for model in ["model_a", "model_b"]:
        model_dir = Path(model)
        snapshot_file = snapshots_dir / f"{model}_start.zip"

        if not snapshot_file.exists() and model_dir.exists():
            print_info(f"Creating start snapshot for {model}...")
            if create_repository_snapshot_zip(str(model_dir), str(snapshot_file)):
                print_success(f"Created {snapshot_file}")
            else:
                print_info(f"Warning: Could not create start snapshot for {model}")

def get_model_assignments(static_model, chosen_model, model_code_name_mapping, use_code_names=True):
    """Get model assignments with random positioning and code name assignment."""
    # Randomly decide which model goes in model_a vs model_b
    static_position = random.choice(["model_a", "model_b"])
    chosen_position = "model_b" if static_position == "model_a" else "model_a"

    assignments = {
        static_position: static_model,
        chosen_position: chosen_model
    }

    # Pick random code names for each model, or use real model names directly
    if use_code_names:
        static_code_name = random.choice(model_code_name_mapping.get(static_model, [static_model]))
        chosen_code_name = random.choice(model_code_name_mapping.get(chosen_model, [chosen_model]))
    else:
        static_code_name = static_model
        chosen_code_name = chosen_model

    code_names = {
        static_position: static_code_name,
        chosen_position: chosen_code_name
    }

    return assignments, code_names

def main():
    """Main setup function."""
    start_time = datetime.now()
    
    platform_name = "Windows" if IS_WINDOWS else platform.system()
    title = f"Claude Code A/B Testing Setup ({platform_name})" if IS_WINDOWS else "🚀 Claude Code A/B Testing Setup"
    print(title)
    print("=" * 50)
    
    try:
        # Load sprint configuration from Supabase
        sprint_config = download_sprint_config()
        if not sprint_config:
            print_error("Failed to load sprint configuration")
        
        model_config = sprint_config.get("model_config", {})
        model_code_name_mapping = sprint_config.get("model_code_name_mapping", {})
        anthropic_base_url = sprint_config.get("anthropic_base_url")
        litellm_master_key = sprint_config.get("litellm_master_key")

        # Pick a matchup: new multi-matchup format or legacy static/pool
        matchups = model_config.get("matchups")
        if matchups:
            matchup_idx = random.randrange(len(matchups))
            matchup = matchups[matchup_idx]
            static_base_model = matchup["base"]
            chosen_random_model = matchup["random"]
            print_info(f"Selected matchup {matchup_idx + 1}/{len(matchups)}: {static_base_model} vs {chosen_random_model}")
        else:
            static_base_model = model_config.get("static_base_model")
            random_model_pool = model_config.get("random_model_pool")
            if not static_base_model or not random_model_pool:
                print_error("Invalid sprint configuration: missing model configuration")
            chosen_random_model = random.choice(random_model_pool)

        always_thinking_enabled = sprint_config.get("always_thinking_enabled", False)
        auto_mode_enabled = sprint_config.get("auto_mode_enabled", False)
        use_code_names = sprint_config.get("use_code_names", True)

        if use_code_names and (not anthropic_base_url or not litellm_master_key):
            print_error("Invalid sprint configuration: missing authentication settings")

        # Get user inputs
        expert_name = validate_input(
            "Enter your name (expert name)",
            lambda x: len(x.strip()) >= 2,
            "Name must be at least 2 characters"
        )
        
        task_id = validate_input(
            "Enter unique task ID (e.g., TASK_001)",
            lambda x: len(x.strip()) >= 4 and not ' ' in x and x.startswith('TASK_'),
            "Task ID must start with 'TASK_' prefix, be at least 4 characters, and contain no spaces"
        )
        
        repo_url = validate_input(
            "Enter repository SSH URL (git@github.com:user/repo.git)",
            validate_repo_url,
            "Invalid repository URL format. Must be SSH format: git@github.com:user/repo.git"
        )
        
        # Get model assignments with random positioning and code names
        assignments, code_names = get_model_assignments(
            static_base_model, chosen_random_model, model_code_name_mapping, use_code_names
        )
        
        # Create directories
        print_info("Creating model directories...")
        os.makedirs("model_a", exist_ok=True)
        os.makedirs("model_b", exist_ok=True)
        
        # Clone repositories
        if not clone_repository(repo_url, "model_a"):
            print_error("Failed to clone repository to model_a")
        
        if not clone_repository(repo_url, "model_b"):
            print_error("Failed to clone repository to model_b")

        # Capture base commit SHA (initial repository state) — same for both clones
        base_commit_sha = None
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True, text=True, cwd="model_a"
            )
            if result.returncode == 0:
                base_commit_sha = result.stdout.strip()
                print_success(f"Captured base commit: {base_commit_sha[:8]}")
        except Exception as e:
            print_warning(f"Failed to capture base commit SHA: {e}")

        # Download .claude directory
        print_info("Downloading Claude Code configuration...")
        if not download_claude_directory():
            print_error("Failed to download .claude directory")
        
        # Install .claude in both repositories with code names and credentials
        if not install_claude_directory("model_a", code_names["model_a"], anthropic_base_url, litellm_master_key, task_id, expert_name, always_thinking_enabled, auto_mode_enabled, use_code_names):
            print_error("Failed to install .claude in model_a")

        if not install_claude_directory("model_b", code_names["model_b"], anthropic_base_url, litellm_master_key, task_id, expert_name, always_thinking_enabled, auto_mode_enabled, use_code_names):
            print_error("Failed to install .claude in model_b")
        
        # Download submit script (also downloads snapshot_utils.py)
        print_info("Downloading submit script...")
        if not download_submit_script():
            print_error("Failed to download submit script")

        # Copy claude-dev launcher into each model directory
        if IS_WINDOWS:
            launcher = "claude-dev.ps1"
        else:
            launcher = "claude-dev"
        for model_dir in ["model_a", "model_b"]:
            dest = os.path.join(model_dir, launcher)
            shutil.copy2(launcher, dest)
            if not IS_WINDOWS:
                os.chmod(dest, 0o755)
        # Remove launcher from root dir (only needed inside model dirs)
        if os.path.exists(launcher):
            os.remove(launcher)
        print_success("Installed claude-dev launcher in model directories")

        # Create start snapshots (fail-safe for old init)
        ensure_start_snapshots()

        # Create manifest
        setup_duration = (datetime.now() - start_time).total_seconds()
        if not create_manifest(expert_name, task_id, repo_url, assignments, code_names, setup_duration, base_commit_sha):
            print_error("Failed to create manifest")
        
        # Verify setup
        if not verify_setup():
            print_error("Setup verification failed")
        
        # Cleanup
        cleanup_temp_files()
        
        # Platform-specific success message
        print("\n" + "=" * 50)
        print_success("Setup completed successfully!")
        
        if IS_WINDOWS:
            # Windows instructions
            print("\nNext steps:")
            print("1. Open two PowerShell windows")
            print("2. In window 1: cd model_a; .\\claude-dev.ps1")
            print("3. In window 2: cd model_b; .\\claude-dev.ps1")
            print("4. Work on your task with both models")
            print("5. When done: python submit.py")
            print("\nHappy coding!")
        else:
            # Unix/Mac instructions
            print("\n📋 Next steps:")
            print("1. Open two terminal windows")
            print("2. In terminal 1: cd model_a && ./claude-dev")
            print("3. In terminal 2: cd model_b && ./claude-dev")
            print("4. Work on your task with both models")
            print("5. When done: ./submit.py")
            print("\n🎯 Happy coding!")
        
    except KeyboardInterrupt:
        prefix = "[CANCELLED]" if IS_WINDOWS else "❌"
        print(f"\n{prefix} Setup cancelled by user")
        cleanup_temp_files()
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error during setup: {e}")
        cleanup_temp_files()
        sys.exit(1)

if __name__ == "__main__":
    main()

