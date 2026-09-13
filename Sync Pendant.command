#!/bin/bash
# Double-click this file in Finder to sync the Pendant and update today's transcript.
set -e
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

if [ -z "$PENDANT_ADDRESS" ]; then
    echo "PENDANT_ADDRESS is not set."
    echo "Run 'python3 -m pendant.cli scan' once to find your Pendant's address,"
    echo "then add this line to your ~/.zshrc (or ~/.bash_profile):"
    echo "  export PENDANT_ADDRESS=\"<address-from-scan>\""
    read -n 1 -s -r -p "Press any key to close..."
    exit 1
fi

echo "Syncing Pendant..."
python3 -m pendant.cli sync

TODAY=$(date +%Y-%m-%d)
echo ""
echo "Updating transcript for $TODAY..."
python3 -m pendant.cli transcribe "$TODAY" || echo "(No new recordings to transcribe today, or transcription failed - see log above.)"

echo ""
echo "Done. Check data/transcripts/$TODAY.md"
read -n 1 -s -r -p "Press any key to close..."
