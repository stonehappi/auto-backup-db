#!/bin/bash

R2_BUCKET="lms-wh"
R2_PREFIX="warehouse_exports"
CSV_DIR="/home/sca/document/google-cloud/export-to-tables/warehouse_exports"

# Check wrangler is available
if ! command -v wrangler &> /dev/null; then
    echo "Error: wrangler not found. Install it with: npm install -g wrangler"
    exit 1
fi

CSV_FILES=("$CSV_DIR"/*.csv)
if [[ ! -e "${CSV_FILES[0]}" ]]; then
    echo "No CSV files found in $CSV_DIR"
    exit 1
fi

echo "Uploading ${#CSV_FILES[@]} CSV file(s) to r2://$R2_BUCKET/$R2_PREFIX/ ..."

for FILE in "${CSV_FILES[@]}"; do
    FILENAME=$(basename "$FILE")
    echo "  Uploading $FILENAME ..."
    wrangler r2 object put "$R2_BUCKET/$R2_PREFIX/$FILENAME" \
        --file "$FILE" \
        --content-type "text/csv" \
        --remote
done

echo "Upload complete."
# remove folder
rm -rf "$CSV_DIR"