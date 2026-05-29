BASE_DIR="/home/sca/document/google-cloud"

# 1. Start the Cloud SQL Proxy
echo "Starting Cloud SQL Proxy..."
bash "$BASE_DIR/start.sh"

# Wait for the proxy to initialize
sleep 5

# 2. Clone to postgress
bash "$BASE_DIR/clone-to-postgres/sync_cloud_to_local.sh"

# 3. Stop the Cloud SQL Proxy
echo "Stopping Cloud SQL Proxy..."
bash "$BASE_DIR/stop.sh"

# 4. ETL warehourse
bash "$BASE_DIR/export-to-tables/export_tables.sh"

# 5. Upload to warehourse
bash "$BASE_DIR/export-to-tables/upload.sh"


