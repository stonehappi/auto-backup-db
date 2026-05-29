#!/bin/bash

# Load configuration from .env
ENV_FILE="$(dirname "$0")/../.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "Error: .env file not found at $ENV_FILE"
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BASE_DIR/cloud_sql_export_$TIMESTAMP.sql"

# Check for required dependencies
for cmd in pg_dump docker wrangler; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "Error: Required command '$cmd' not found. Please install it."
        exit 1
    fi
done


# 2. Export the database to a SQL file
echo "Exporting database '$DB_NAME' from Cloud SQL..."
# --no-owner and --no-privileges are recommended to prevent errors when roles don't match exactly
PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    --no-owner --no-privileges \
    "$DB_NAME" > "$BACKUP_FILE"

# 4. Restore to Local Docker PostgreSQL
echo "Restoring to Docker container '$LOCAL_CONTAINER_NAME'..."

# Create the cloudsqlsuperuser role if it doesn't exist
echo "Delete old database and role if they exist..."
docker exec -i "$LOCAL_CONTAINER_NAME" psql -U "$LOCAL_DB_USER" -c "DROP DATABASE IF EXISTS \"$LOCAL_DB_NAME\";"

# Create the local database
docker exec -i "$LOCAL_CONTAINER_NAME" psql -U "$LOCAL_DB_USER" -c "CREATE DATABASE \"$LOCAL_DB_NAME\";"

# Perform the restore by piping the SQL file into the container's psql
echo "Restoring from $BACKUP_FILE..."
docker exec -i "$LOCAL_CONTAINER_NAME" psql -U "$LOCAL_DB_USER" -d "$LOCAL_DB_NAME" < "$BACKUP_FILE"

if [ $? -eq 0 ]; then
    echo "Successfully synced Cloud SQL to local Docker instance."

    # 5. Upload SQL backup to R2 before deleting
    SQL_FILENAME="database.sql"
    echo "Uploading $SQL_FILENAME to r2://$R2_BUCKET/$R2_PREFIX/ ..."
    wrangler r2 object put "$R2_BUCKET/$R2_PREFIX/$SQL_FILENAME" \
        --file "$BACKUP_FILE" \
        --content-type "application/sql" \
        --remote

    if [ $? -eq 0 ]; then
        echo "Upload successful. Deleting local backup..."
        rm "$BACKUP_FILE"
    else
        echo "Upload to R2 failed. Local backup kept at: $BACKUP_FILE"
    fi
else
    echo "Restore failed. Check if the container is running and the credentials are correct."
fi