#!/bin/bash

PID_FILE="/home/sca/document/google-cloud/proxy.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    kill "$PID" && rm "$PID_FILE"
    echo "Cloud SQL Proxy (PID $PID) has been stopped."
else
    echo "Proxy PID file not found. Is it running?"
fi