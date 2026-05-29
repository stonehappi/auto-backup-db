#!/bin/bash

BASE_DIR="/home/sca/document/google-cloud"
export GOOGLE_APPLICATION_CREDENTIALS="$BASE_DIR/desk-442207-4fed3b1d9d20.json"
./cloud-sql-proxy --port 5433 event-hub-807bc:asia-southeast1:wedding-hub-auth > "$BASE_DIR/proxy.log" 2>&1 &
echo $! > "$BASE_DIR/proxy.pid"