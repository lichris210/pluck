#!/bin/bash
# run_phase1.sh
# Bash equivalent for WSL/Mac/Linux. Stops on first failure.
# Usage: bash run_phase1.sh [start_at]
# Example: bash run_phase1.sh 3   (skips prompts 1 and 2)

set -e
START_AT="${1:-1}"

for f in "$(dirname "$0")"/prompt_*.md; do
    num=$(basename "$f" | sed -E 's/^prompt_0*([0-9]+)_.*/\1/')
    if [ "$num" -lt "$START_AT" ]; then
        echo "Skipping $(basename "$f")"
        continue
    fi
    echo ""
    echo "=== Running $(basename "$f") ==="
    echo ""
    claude --dangerously-skip-permissions -p "$(cat "$f")" || {
        echo ""
        echo "FAILED on $(basename "$f")"
        echo "Resume with: bash run_phase1.sh $num"
        exit 1
    }
    echo "Completed $(basename "$f")"
done

echo ""
echo "All prompts completed."
