#!/usr/bin/env python3
"""
Process raw transcript to extract all messages and generate summaries.
Handles both incremental (Stop event) and final (SessionEnd) processing.
Cross-platform support for Windows, macOS, and Linux.
"""
import json
import sys
import os
import shutil
import subprocess
import html as html_mod
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from claude_code_capture_utils import get_log_file_path, add_ab_metadata, detect_model_lane, get_experiment_root

def read_and_process_raw_transcript(transcript_path, strip_model_names=True):
    """
    Read raw transcript, deduplicate streaming duplicates, and return all events.

    Deduplication: assistant messages with the same message.id are deduplicated
    (last occurrence wins, since streaming sends partial then complete). All other
    event types (user, system, progress, etc.) are kept as-is with no filtering.

    If strip_model_names is True, the 'model' field is removed from assistant
    messages to maintain expert blinding.

    Also extracts thinking blocks as separate entries for analytics.
    """
    if not os.path.exists(transcript_path):
        return []

    # First pass: collect all events, track assistant message IDs for dedup
    raw_events = []
    # Track last occurrence index of each assistant message ID
    assistant_last_index = {}
    # Track thinking blocks by parent message ID
    thinking_blocks = {}

    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    idx = len(raw_events)
                    raw_events.append(event)

                    event_type = event.get('type')

                    if event_type == 'assistant':
                        message = event.get('message', {})
                        msg_id = message.get('id')
                        if msg_id:
                            # Track last occurrence for dedup
                            assistant_last_index[msg_id] = idx

                            # Extract thinking blocks
                            content = message.get('content', [])
                            if isinstance(content, list):
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'thinking':
                                        thinking_blocks[msg_id] = {
                                            'type': 'assistant_thinking',
                                            'timestamp': event.get('timestamp'),
                                            'message_id': msg_id,
                                            'thinking_content': item.get('thinking', ''),
                                            'session_id': event.get('sessionId'),
                                            'cwd': event.get('cwd')
                                        }

                except json.JSONDecodeError:
                    continue

    except Exception as e:
        print(f"[ERROR] Reading raw transcript: {e}", file=sys.stderr)
        return []

    # Second pass: build deduplicated list
    # For assistant messages, only keep the last occurrence of each message ID
    # For all other event types, keep everything
    seen_assistant_ids = set()
    # Build set of indices that are duplicate assistant messages (not the last one)
    duplicate_indices = set()
    for msg_id, last_idx in assistant_last_index.items():
        for i, ev in enumerate(raw_events):
            if i == last_idx:
                continue
            if ev.get('type') == 'assistant':
                ev_msg_id = ev.get('message', {}).get('id')
                if ev_msg_id == msg_id:
                    duplicate_indices.add(i)

    all_events = []
    for i, event in enumerate(raw_events):
        if i in duplicate_indices:
            continue

        event_type = event.get('type')

        # Strip model names from assistant messages for blinding
        if strip_model_names and event_type == 'assistant':
            message = event.get('message', {})
            if 'model' in message:
                event = json.loads(json.dumps(event))  # deep copy
                del event['message']['model']

        # Insert thinking block before its parent assistant message
        if event_type == 'assistant':
            msg_id = event.get('message', {}).get('id')
            if msg_id in thinking_blocks and msg_id not in seen_assistant_ids:
                all_events.append(thinking_blocks[msg_id])
            if msg_id:
                seen_assistant_ids.add(msg_id)

        all_events.append(event)

    return all_events

def aggregate_token_usage(messages):
    """Aggregate token usage from all assistant messages.
    Note: assistant_thinking entries are explicitly excluded to avoid double-counting.
    """
    total_usage = {
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'total_cache_creation_tokens': 0,
        'total_cache_read_tokens': 0,
        'total_ephemeral_5m_tokens': 0,
        'total_ephemeral_1h_tokens': 0,
        'service_tier': None
    }
    
    for msg_data in messages:
        # Only count tokens from 'assistant' type, NOT 'assistant_thinking'
        # Thinking tokens are already included in the parent assistant message's output_tokens
        if msg_data['type'] == 'assistant':
            message = msg_data['message']
            usage = message.get('usage', {})
            
            if usage:
                total_usage['total_input_tokens'] += usage.get('input_tokens', 0)
                total_usage['total_output_tokens'] += usage.get('output_tokens', 0)
                total_usage['total_cache_creation_tokens'] += usage.get('cache_creation_input_tokens', 0)
                total_usage['total_cache_read_tokens'] += usage.get('cache_read_input_tokens', 0)
                
                cache_creation = usage.get('cache_creation', {})
                total_usage['total_ephemeral_5m_tokens'] += cache_creation.get('ephemeral_5m_input_tokens', 0)
                total_usage['total_ephemeral_1h_tokens'] += cache_creation.get('ephemeral_1h_input_tokens', 0)
                
                if usage.get('service_tier'):
                    total_usage['service_tier'] = usage.get('service_tier')
    
    # Add calculated total
    total_usage['total_actual_input_tokens'] = (
        total_usage['total_input_tokens'] + 
        total_usage['total_cache_creation_tokens'] + 
        total_usage['total_cache_read_tokens']
    )
    
    return total_usage

def analyze_tool_calls(messages):
    """Extract tool call metrics from messages."""
    tool_calls = defaultdict(int)
    tool_results = defaultdict(int)
    
    for msg_data in messages:
        # Skip entries without 'message' key (e.g., assistant_thinking)
        if 'message' not in msg_data:
            continue
        message = msg_data['message']
        content = message.get('content', [])
        
        if not isinstance(content, list):
            continue
        
        for item in content:
            if not isinstance(item, dict):
                continue
            
            if item.get('type') == 'tool_use':
                tool_name = item.get('name', 'unknown')
                tool_calls[tool_name] += 1
            
            elif item.get('type') == 'tool_result':
                # Try to infer tool name from context (simplified)
                tool_results['total'] += 1
    
    return {
        'tool_calls_by_type': dict(tool_calls),
        'total_tool_calls': sum(tool_calls.values()),
        'total_tool_results': tool_results.get('total', 0)
    }

def analyze_thinking_usage(messages, transcript_path):
    """Analyze thinking mode usage in messages."""
    thinking_stats = {
        'thinking_enabled_turns': 0,
        'thinking_disabled_turns': 0,
        'assistant_with_thinking_blocks': 0,
        'thinking_levels': defaultdict(int)
    }
    
    # Track which turns had thinking enabled (from user thinkingMetadata)
    for msg_data in messages:
        if msg_data['type'] == 'user' and 'thinkingMetadata' in msg_data:
            metadata = msg_data['thinkingMetadata']
            if not metadata.get('disabled', True):
                thinking_stats['thinking_enabled_turns'] += 1
                level = metadata.get('level', 'none')
                thinking_stats['thinking_levels'][level] += 1
            else:
                thinking_stats['thinking_disabled_turns'] += 1
    
    # Count assistant messages with thinking blocks
    # Check ALL occurrences in raw transcript (not just final deduplicated state)
    assistant_msg_ids_with_thinking = set()
    
    try:
        if os.path.exists(transcript_path):
            with open(transcript_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if event.get('type') == 'assistant':
                            message = event.get('message', {})
                            msg_id = message.get('id')
                            content = message.get('content', [])
                            
                            if msg_id and isinstance(content, list):
                                # Check if this occurrence has thinking
                                has_thinking = any(
                                    isinstance(item, dict) and item.get('type') == 'thinking'
                                    for item in content
                                )
                                if has_thinking:
                                    assistant_msg_ids_with_thinking.add(msg_id)
                    except:
                        continue
    except Exception:
        pass
    
    thinking_stats['assistant_with_thinking_blocks'] = len(assistant_msg_ids_with_thinking)
    
    return {
        'thinking_enabled_turns': thinking_stats['thinking_enabled_turns'],
        'thinking_disabled_turns': thinking_stats['thinking_disabled_turns'],
        'assistant_with_thinking_blocks': thinking_stats['assistant_with_thinking_blocks'],
        'thinking_levels': dict(thinking_stats['thinking_levels'])
    }

def calculate_git_metrics(cwd, base_commit):
    """Calculate git metrics from diff."""
    try:
        original_cwd = os.getcwd()
        os.chdir(cwd)
        
        if not base_commit:
            os.chdir(original_cwd)
            return {}
        
        # Add untracked files
        excluded_patterns = ['.claude/', '__pycache__/', 'node_modules/', '.mypy_cache/', 
                           '.pytest_cache/', '.DS_Store', '.vscode/', '.idea/']
        
        untracked_result = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            capture_output=True, text=True, timeout=30
        )
        
        if untracked_result.returncode == 0 and untracked_result.stdout.strip():
            untracked_files = [
                f.strip() for f in untracked_result.stdout.strip().split('\n')
                if f.strip() and not any(pattern in f for pattern in excluded_patterns)
            ]
            
            for file in untracked_files:
                subprocess.run(['git', 'add', '-N', file], capture_output=True, timeout=5)
        
        # Calculate numstat
        result = subprocess.run(
            ['git', 'diff', '--numstat', base_commit, '--', '.', 
             ':!.claude', ':!**/.mypy_cache', ':!**/__pycache__', ':!**/.pytest_cache',
             ':!**/.DS_Store', ':!**/node_modules', ':!**/.vscode', ':!**/.idea'],
            capture_output=True, text=True, timeout=30
        )
        
        os.chdir(original_cwd)
        
        if result.returncode != 0:
            return {}
        
        lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
        files_changed = 0
        total_lines_changed = 0
        
        for line in lines:
            if line.strip():
                parts = line.split('\t')
                if len(parts) >= 3:
                    try:
                        added = int(parts[0]) if parts[0] != '-' else 0
                        removed = int(parts[1]) if parts[1] != '-' else 0
                        files_changed += 1
                        total_lines_changed += added + removed
                    except ValueError:
                        continue
        
        return {
            "files_changed_count": files_changed,
            "lines_of_code_changed_count": total_lines_changed
        }
        
    except Exception as e:
        print(f"Warning: Could not calculate git metrics: {e}", file=sys.stderr)
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        return {}

def copy_raw_transcript(transcript_path, session_id, cwd):
    """Copy raw transcript to logs folder."""
    try:
        source_path = Path(transcript_path)
        if not source_path.exists():
            print(f"Warning: Raw transcript not found at {source_path}", file=sys.stderr)
            return False
        
        model_lane = detect_model_lane(cwd)
        experiment_root = get_experiment_root(cwd)
        
        if model_lane and experiment_root:
            logs_dir = Path(experiment_root) / "logs" / model_lane
            logs_dir.mkdir(parents=True, exist_ok=True)
            dest_path = logs_dir / f"session_{session_id}_raw.jsonl"
        else:
            project_dir = os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())
            logs_dir = Path(project_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)
            dest_path = logs_dir / f"session_{session_id}_raw.jsonl"
        
        shutil.copy2(source_path, dest_path)
        print(f"[OK] Copied raw transcript to {dest_path}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Copying raw transcript: {e}", file=sys.stderr)
        return False

def get_base_commit_from_log(log_file):
    """Extract base commit from session_start event."""
    try:
        if not os.path.exists(log_file):
            return None
        
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                        if event.get('type') == 'session_start':
                            git_metadata = event.get('git_metadata', {})
                            return git_metadata.get('base_commit')
                    except json.JSONDecodeError:
                        continue
        return None
    except Exception:
        return None

def generate_html_viewer(log_file, html_output_path):
    """Generate a clean HTML viewer from the deduplicated JSONL transcript."""
    events = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _parse_ts(ts):
        if not ts:
            return ""
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.strftime("%H:%M:%S")
        except Exception:
            return ""

    def _render_tool_result(content):
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
    tool_results_map = {}
    for ev in events:
        if ev.get("type") == "user":
            content = ev.get("message", {}).get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        if tid:
                            tool_results_map[tid] = block

    total = len(events)
    turn_count = 0

    page = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Transcript Viewer</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f1a; color: #d4d4d8; max-width: 960px; margin: 0 auto; padding: 20px 24px; line-height: 1.5; }}
h1 {{ color: #fff; font-size: 20px; margin-bottom: 4px; }}
.meta {{ color: #71717a; font-size: 13px; margin-bottom: 28px; }}
.search-bar {{ position: sticky; top: 0; z-index: 100; background: #0f0f1a; padding: 12px 0; border-bottom: 1px solid #27272a; margin-bottom: 16px; }}
.search-bar input {{ width: 100%; padding: 10px 14px; font-size: 14px; background: #1e1e2e; color: #e0e0e0; border: 1px solid #3f3f46; border-radius: 6px; outline: none; }}
.search-bar input:focus {{ border-color: #8b5cf6; }}
.search-info {{ color: #71717a; font-size: 12px; margin-top: 6px; }}
mark {{ background: #854d0e; color: #fef3c7; padding: 1px 2px; border-radius: 2px; }}
mark.current {{ background: #a21caf; color: #fae8ff; }}
.turn-divider {{ border-top: 1px solid #27272a; margin: 28px 0 16px 0; }}
.event {{ margin-bottom: 12px; border-radius: 8px; padding: 14px 18px; }}
.user-msg {{ background: #172033; border-left: 3px solid #3b82f6; }}
.assistant-msg {{ background: #1a1525; border-left: 3px solid #8b5cf6; }}
.system-msg {{ background: #1f1215; border-left: 3px solid #ef4444; font-size: 13px; }}
.event-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
.role {{ font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px; }}
.role-user {{ color: #60a5fa; }}
.role-assistant {{ color: #a78bfa; }}
.role-system {{ color: #f87171; }}
.timestamp {{ color: #52525b; font-size: 11px; font-family: monospace; }}
.text-content {{ white-space: pre-wrap; font-size: 14px; line-height: 1.7; word-wrap: break-word; }}
details {{ margin: 8px 0; }}
details summary {{ cursor: pointer; font-size: 13px; font-weight: 500; padding: 4px 0; }}
.thinking {{ background: #1e1e2e; border-radius: 6px; padding: 12px 16px; margin: 8px 0; }}
.thinking summary {{ color: #7c3aed; }}
.thinking .text-content {{ color: #a1a1aa; font-size: 13px; }}
.tool-block {{ background: #111827; border: 1px solid #1e293b; border-radius: 8px; margin: 10px 0; overflow: hidden; }}
.tool-header {{ background: #1e293b; padding: 8px 14px; }}
.tool-name {{ color: #38bdf8; font-weight: 600; font-size: 13px; font-family: monospace; }}
.tool-input {{ padding: 10px 14px; font-family: monospace; font-size: 12px; color: #a1a1aa; white-space: pre-wrap; word-wrap: break-word; }}
.tool-input summary {{ color: #64748b; }}
.tool-result {{ background: #0d1f0d; border-top: 1px solid #1e293b; padding: 10px 14px; font-family: monospace; font-size: 12px; color: #86efac; white-space: pre-wrap; word-wrap: break-word; max-height: 600px; overflow-y: auto; }}
.tool-result summary {{ color: #4ade80; }}
.tool-result-error {{ background: #1f0d0d; color: #fca5a5; }}
</style>
</head>
<body>
<script>
let matches=[];let currentMatch=-1;
function doSearch(){{const q=document.getElementById('searchInput').value.trim().toLowerCase();const info=document.getElementById('searchInfo');document.querySelectorAll('mark').forEach(m=>{{const p=m.parentNode;p.replaceChild(document.createTextNode(m.textContent),m);p.normalize()}});matches=[];currentMatch=-1;if(!q||q.length<2){{info.textContent='';return}}document.querySelectorAll('details').forEach(d=>{{if(d.textContent.toLowerCase().includes(q))d.open=true}});const walker=document.createTreeWalker(document.querySelector('.transcript-content'),NodeFilter.SHOW_TEXT,null,false);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);for(const node of nodes){{const t=node.textContent;const l=t.toLowerCase();if(!l.includes(q))continue;const frag=document.createDocumentFragment();let last=0;let idx=l.indexOf(q);while(idx!==-1){{frag.appendChild(document.createTextNode(t.slice(last,idx)));const mk=document.createElement('mark');mk.textContent=t.slice(idx,idx+q.length);frag.appendChild(mk);matches.push(mk);last=idx+q.length;idx=l.indexOf(q,last)}}frag.appendChild(document.createTextNode(t.slice(last)));node.parentNode.replaceChild(frag,node)}}if(matches.length>0){{currentMatch=0;matches[0].classList.add('current');matches[0].scrollIntoView({{behavior:'smooth',block:'center'}});info.textContent=`1 of ${{matches.length}} matches`}}else{{info.textContent='No matches'}}}}
function nextMatch(d){{if(!matches.length)return;matches[currentMatch].classList.remove('current');currentMatch=(currentMatch+d+matches.length)%matches.length;matches[currentMatch].classList.add('current');matches[currentMatch].scrollIntoView({{behavior:'smooth',block:'center'}});document.getElementById('searchInfo').textContent=`${{currentMatch+1}} of ${{matches.length}}`}}
document.addEventListener('keydown',function(e){{if(e.key==='Enter'&&document.activeElement.id==='searchInput'){{e.preventDefault();nextMatch(e.shiftKey?-1:1)}}if((e.ctrlKey||e.metaKey)&&e.key==='f'){{e.preventDefault();document.getElementById('searchInput').focus()}}}});
</script>
<div class="search-bar">
<input type="text" id="searchInput" placeholder="Search transcript... (Ctrl+F)" oninput="doSearch()">
<div class="search-info" id="searchInfo"></div>
</div>
<h1>Session Transcript</h1>
<div class="meta">{total} events</div>
<div class="transcript-content">
"""

    for ev in events:
        ev_type = ev.get("type", "")
        ts = _parse_ts(ev.get("timestamp"))

        if ev_type == "user":
            msg = ev.get("message", {})
            content = msg.get("content", "")
            text_parts = []
            has_only_tool_results = True

            if isinstance(content, str):
                if content.strip():
                    text_parts.append(content.strip())
                    has_only_tool_results = False
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            t = block.get("text", "").strip()
                            if t:
                                text_parts.append(t)
                                has_only_tool_results = False

            if has_only_tool_results and not text_parts:
                continue
            if text_parts:
                combined = "\n\n".join(text_parts)
                if combined.startswith("<command-"):
                    continue
                turn_count += 1
                page += '<div class="turn-divider"></div>\n'
                page += f'<div class="event user-msg"><div class="event-header"><span class="role role-user">User (Turn {turn_count})</span><span class="timestamp">{ts}</span></div>'
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
                    if tool_id in tool_results_map:
                        tr = tool_results_map[tool_id]
                        is_error = tr.get("is_error", False)
                        tr_content = _render_tool_result(tr.get("content", ""))
                        err_cls = " tool-result-error" if is_error else ""
                        blocks += f'<details open class="tool-result{err_cls}"><summary>Result{" (error)" if is_error else ""}</summary>{tr_content}</details>\n'
                    blocks += '</div>\n'
            if blocks:
                page += f'<div class="event assistant-msg"><div class="event-header"><span class="role role-assistant">Assistant</span><span class="timestamp">{ts}</span></div>{blocks}</div>\n'

        elif ev_type == "system":
            subtype = ev.get("subtype", "")
            content = ev.get("content", "")
            if content:
                meta = ev.get("compactMetadata", {})
                extra = ""
                if meta.get("preTokens"):
                    extra = f' (pre-compact tokens: {meta["preTokens"]:,})'
                page += f'<div class="event system-msg"><div class="event-header"><span class="role role-system">System: {html_mod.escape(subtype)}</span><span class="timestamp">{ts}</span></div>'
                page += f'<div class="text-content">{html_mod.escape(str(content))}{extra}</div></div>\n'

    page += "</div>\n</body></html>"

    with open(html_output_path, "w", encoding="utf-8") as f:
        f.write(page)

    print(f"[OK] Generated HTML viewer: {html_output_path} ({turn_count} turns)")


def main():
    try:
        if len(sys.argv) < 2:
            print("Usage: process_transcript.py [incremental|final]", file=sys.stderr)
            sys.exit(1)
        
        mode = sys.argv[1].lower()
        if mode not in ["incremental", "final"]:
            print("Mode must be 'incremental' or 'final'", file=sys.stderr)
            sys.exit(1)
        
        input_data = json.load(sys.stdin)
        
        session_id = input_data.get("session_id", "unknown")
        transcript_path = input_data.get("transcript_path", "")
        cwd = input_data.get("cwd", "")
        
        log_file = get_log_file_path(session_id, cwd)
        
        if mode == "incremental":
            # Stop event: incremental processing (fault tolerance)
            # Copy raw transcript on every incremental pass (overwrite) so we always have
            # the latest version even if the final/SessionEnd hook never fires
            copy_raw_transcript(transcript_path, session_id, cwd)

            # Read raw transcript, deduplicate streaming assistant messages, strip model names
            events = read_and_process_raw_transcript(transcript_path)

            if not events:
                return

            # Track what we've already written to avoid re-appending
            # Use uuid where available, fall back to type+timestamp as composite key
            existing_keys = set()

            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            event = json.loads(line)
                            key = event.get('uuid') or f"{event.get('type')}:{event.get('timestamp','')}"
                            existing_keys.add(key)
                        except:
                            continue

            # Append all new events
            new_count = 0
            with open(log_file, "a", encoding="utf-8") as f:
                for event in events:
                    uuid = event.get('uuid')
                    ts = event.get('timestamp', '')
                    # Events with uuid or timestamp can be dedup'd
                    if uuid or ts:
                        key = uuid or f"{event.get('type')}:{ts}"
                        if key in existing_keys:
                            continue
                        existing_keys.add(key)
                    # Events with neither (e.g. last-prompt) always append
                    log_entry = add_ab_metadata(event.copy(), cwd)
                    f.write(json.dumps(log_entry) + "\n")
                    new_count += 1

            if new_count > 0:
                print(f"[OK] Processed {new_count} new events (total: {len(events)} deduplicated)")
                
        elif mode == "final":
            # SessionEnd: complete processing + summary
            
            # Step 1: Copy raw transcript
            copy_raw_transcript(transcript_path, session_id, cwd)
            
            # Step 2: Process complete raw transcript
            messages = read_and_process_raw_transcript(transcript_path)
            
            if not messages:
                print("Warning: No messages found in raw transcript", file=sys.stderr)
                return
            
            # Step 3: REBUILD processed log in perfect chronological order
            # Read existing non-message events (session_start, etc.)
            non_message_events = []
            
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            event = json.loads(line)
                            # Keep session_start and other non-message events
                            # Exclude assistant, assistant_thinking, and user messages (they come from raw transcript)
                            if event.get('type') not in ['assistant', 'assistant_thinking', 'user']:
                                non_message_events.append(event)
                        except:
                            continue
            
            # Combine all events and sort by timestamp
            session_start = [e for e in non_message_events if e.get('type') == 'session_start']
            other_events = [e for e in non_message_events if e.get('type') != 'session_start']
            
            # Build chronological list: session_start first, then messages sorted by time
            all_events = []
            
            # Add session_start first (if exists)
            if session_start:
                all_events.extend(session_start)
            
            # Add all messages (already sorted by timestamp from read_and_process_raw_transcript)
            # Messages already include thinking blocks inserted before their parent assistant message
            for msg_data in messages:
                all_events.append(add_ab_metadata(msg_data.copy(), cwd))
            
            print(f"[OK] Rebuilding log with {len(all_events)} events in chronological order")
            
            # Step 4: Generate session summary
            usage_totals = aggregate_token_usage(messages)
            tool_metrics = analyze_tool_calls(messages)
            thinking_metrics = analyze_thinking_usage(messages, transcript_path)
            
            # Calculate duration
            timestamps = [
                datetime.fromisoformat(msg['timestamp'].replace('Z', '+00:00'))
                for msg in messages if msg.get('timestamp')
            ]
            
            total_duration = 0
            if len(timestamps) >= 2:
                duration = max(timestamps) - min(timestamps)
                total_duration = duration.total_seconds()
            
            # Count messages with proper categorization
            # Note: assistant_thinking is NOT counted as a separate message (it's part of assistant message)
            assistant_count = sum(1 for m in messages if m['type'] == 'assistant')
            thinking_count = sum(1 for m in messages if m['type'] == 'assistant_thinking')
            
            # Categorize user messages
            user_prompts = 0
            tool_results = 0
            system_messages = 0
            
            for m in messages:
                if m['type'] == 'user':
                    message_content = m['message'].get('content', '')
                    
                    # Check if it's a system/meta message
                    if m.get('isMeta'):
                        system_messages += 1
                    # Check if it's a tool result
                    elif isinstance(message_content, list):
                        has_tool_result = any(
                            isinstance(item, dict) and item.get('type') == 'tool_result'
                            for item in message_content
                        )
                        if has_tool_result:
                            tool_results += 1
                        else:
                            user_prompts += 1
                    # Check if it's an exit/system command
                    elif isinstance(message_content, str) and (
                        '<command-name>' in message_content or 
                        '<local-command-stdout>' in message_content
                    ):
                        system_messages += 1
                    # Real user prompt (string content, not system)
                    elif isinstance(message_content, str):
                        user_prompts += 1
                    else:
                        user_prompts += 1  # Default to user prompt
            
            total_user_events = user_prompts + tool_results + system_messages
            
            # Calculate actual total messages (excluding thinking blocks as they're not separate messages)
            actual_total_messages = assistant_count + total_user_events
            
            # Get git metrics
            base_commit = get_base_commit_from_log(log_file)
            git_metrics = calculate_git_metrics(cwd, base_commit) if base_commit else {}
            
            # Create session summary
            model_lane = detect_model_lane(cwd)
            
            summary = {
                "type": "session_summary",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "session_id": session_id,
                "transcript_path": transcript_path,
                "cwd": cwd,
                "summary_data": {
                    "total_duration_seconds": round(total_duration, 2),
                    "total_messages": actual_total_messages,
                    "assistant_messages": assistant_count,
                    "user_prompts": user_prompts,
                    "user_metrics": {
                        "user_prompts": user_prompts,
                        "tool_results": tool_results,
                        "system_messages": system_messages,
                        "total_user_events": total_user_events
                    },
                    "usage_totals": usage_totals,
                    "tool_metrics": tool_metrics,
                    "thinking_metrics": {
                        **thinking_metrics,
                        "assistant_thinking_blocks_captured": thinking_count
                    },
                    "git_metrics": git_metrics,
                    "files": {
                        "processed_log": f"session_{session_id}.jsonl",
                        "raw_transcript": f"session_{session_id}_raw.jsonl",
                        "git_diff": f"{model_lane}_diff.patch" if model_lane else None
                    },
                    "validation": {
                        "complete": True,
                        "unique_messages_processed": actual_total_messages,
                        "thinking_blocks_extracted": thinking_count
                    }
                }
            }
            
            summary = add_ab_metadata(summary, cwd)
            
            # Add session summary to events
            all_events.append(summary)
            
            # Step 5: Rewrite log file with all events in perfect chronological order
            # Write to temp file first, then rename (atomic)
            temp_log_file = log_file + ".tmp"
            
            with open(temp_log_file, "w", encoding="utf-8") as f:
                for event in all_events:
                    f.write(json.dumps(event) + "\n")
            
            # Atomic rename
            os.replace(temp_log_file, log_file)
            
            print(f"[OK] Rebuilt log with {len(all_events)} events in chronological order")
            print(f"[OK] Generated session summary: {actual_total_messages} messages, {assistant_count} assistant, {user_prompts} user prompts")
            if thinking_count > 0:
                print(f"[OK] Captured {thinking_count} thinking blocks (tokens already included in assistant output)")
            print(f"[OK] User breakdown: {user_prompts} prompts, {tool_results} tool results, {system_messages} system")
            print(f"[OK] Tokens: {usage_totals['total_actual_input_tokens']:,} input, {usage_totals['total_output_tokens']:,} output")

            # Note: HTML viewer generation happens in submit.py before upload
            
    except Exception as e:
        print(f"[ERROR] Processing transcript: {e}", file=sys.stderr)
        sys.exit(1)

def calculate_git_metrics(cwd, base_commit):
    """Calculate git metrics from diff."""
    try:
        original_cwd = os.getcwd()
        os.chdir(cwd)
        
        if not base_commit:
            os.chdir(original_cwd)
            return {}
        
        # Add untracked files
        excluded_patterns = ['.claude/', '__pycache__/', 'node_modules/', '.mypy_cache/', 
                           '.pytest_cache/', '.DS_Store', '.vscode/', '.idea/']
        
        untracked_result = subprocess.run(
            ['git', 'ls-files', '--others', '--exclude-standard'],
            capture_output=True, text=True, timeout=30
        )
        
        if untracked_result.returncode == 0 and untracked_result.stdout.strip():
            untracked_files = [
                f.strip() for f in untracked_result.stdout.strip().split('\n')
                if f.strip() and not any(pattern in f for pattern in excluded_patterns)
            ]
            
            for file in untracked_files:
                subprocess.run(['git', 'add', '-N', file], capture_output=True, timeout=5)
        
        # Calculate numstat
        result = subprocess.run(
            ['git', 'diff', '--numstat', base_commit, '--', '.', 
             ':!.claude', ':!**/.mypy_cache', ':!**/__pycache__', ':!**/.pytest_cache',
             ':!**/.DS_Store', ':!**/node_modules', ':!**/.vscode', ':!**/.idea'],
            capture_output=True, text=True, timeout=30
        )
        
        os.chdir(original_cwd)
        
        if result.returncode != 0:
            return {}
        
        lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
        files_changed = 0
        total_lines_changed = 0
        
        for line in lines:
            if line.strip():
                parts = line.split('\t')
                if len(parts) >= 3:
                    try:
                        added = int(parts[0]) if parts[0] != '-' else 0
                        removed = int(parts[1]) if parts[1] != '-' else 0
                        files_changed += 1
                        total_lines_changed += added + removed
                    except ValueError:
                        continue
        
        return {
            "files_changed_count": files_changed,
            "lines_of_code_changed_count": total_lines_changed
        }
        
    except Exception as e:
        print(f"Warning: Could not calculate git metrics: {e}", file=sys.stderr)
        if 'original_cwd' in locals():
            os.chdir(original_cwd)
        return {}

if __name__ == "__main__":
    main()

