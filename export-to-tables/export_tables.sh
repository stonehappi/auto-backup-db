#!/bin/bash

# Configuration
BASE_DIR="/home/sca/document/google-cloud"
OUTPUT_DIR="$BASE_DIR/export-to-tables/csv_exports"
VENV_DIR="$BASE_DIR/export-to-tables/.venv"


# Ensure export directory exists
mkdir -p "$OUTPUT_DIR"

# Check for required dependencies
for cmd in jq python3; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' not found. Please install it and try again."
        exit 1
    fi
done

# Setup Virtual Environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || { echo "Error: Failed to create venv. Install python3-venv (e.g., sudo apt install python3-venv)"; exit 1; }
fi

# Install dependencies inside the virtual environment
echo "Ensuring Python dependencies are installed..."
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q pandas sqlalchemy psycopg2-binary


# 2. Export tables listed in tables.json
if [ -f "$BASE_DIR/export-to-tables/export_to_csv.py" ]; then
    echo "Processing exports..."
    "$VENV_DIR/bin/python3" "$BASE_DIR/export-to-tables/export_to_csv.py"
else
    echo "Error: Python export script not found."
fi