#!/bin/bash
# Docker entrypoint script for QE Dashboard Backend
# Copies default data files AND directories to mounted volume if they don't exist
# Runs as root initially, then drops to appuser

set -e

DATA_DIR="/app/data"
DEFAULTS_DIR="/app/data-defaults"

echo "Initializing data directory..."

# Ensure data directory exists
mkdir -p "$DATA_DIR"

# Copy default files and directories if they don't exist in the volume
if [ -d "$DEFAULTS_DIR" ]; then
    for item in "$DEFAULTS_DIR"/*; do
        name=$(basename "$item")
        if [ -f "$item" ]; then
            # Copy file if it doesn't exist
            if [ ! -f "$DATA_DIR/$name" ]; then
                echo "Copying default file: $name"
                cp "$item" "$DATA_DIR/$name"
            fi
        elif [ -d "$item" ]; then
            # Copy directory if it doesn't exist
            if [ ! -d "$DATA_DIR/$name" ]; then
                echo "Copying default directory: $name/"
                cp -r "$item" "$DATA_DIR/$name"
            fi
        fi
    done
fi

# Fix ownership for appuser (UID 1001)
chown -R 1001:1001 "$DATA_DIR"

echo "Data directory ready. Starting application as appuser..."

# Drop privileges and run the main command as appuser
exec gosu appuser "$@"
