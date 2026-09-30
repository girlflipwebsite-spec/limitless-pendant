#!/bin/bash
# Double-click this file in Finder to open the Pendant web interface.
cd "$(dirname "$0")"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python3 -m pendant.cli gui
