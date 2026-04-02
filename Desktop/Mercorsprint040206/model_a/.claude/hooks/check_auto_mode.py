#!/usr/bin/env python3
"""
PreToolUse hook to enforce launching via claude-dev.

Checks for CLAUDE_DEV_LAUNCHER env var OR .claude_dev_active marker file.
The marker file is created by claude-dev on first launch, allowing subsequent
'claude --continue' / 'claude --resume' to work without the wrapper.
"""
import json
import os
import sys


def main():
    # Consume stdin (required by hook protocol)
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    launcher_active = (
        os.environ.get("CLAUDE_DEV_LAUNCHER")
        or os.path.isfile(os.path.join(os.getcwd(), ".claude_dev_active"))
    )

    if not launcher_active:
        result = {
            "decision": "block",
            "reason": "Please exit and use './claude-dev' to start Claude Code instead of 'claude'."
        }
        print(json.dumps(result))
        sys.exit(0)


if __name__ == "__main__":
    main()
