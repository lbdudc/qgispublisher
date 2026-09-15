#!/usr/bin/env bash
# package.sh – Build a QGIS-marketplace-ready zip of the plugin.
#
# Usage:  bash package.sh
# Output: GISPublisher_<version>.zip

set -euo pipefail

PLUGIN_NAME="GISPublisher"
VERSION=$(grep -E "^version\s*=" metadata.txt | sed 's/.*=\s*//')
ARCHIVE="${PLUGIN_NAME}_${VERSION}.zip"
TMP_DIR=$(mktemp -d)
DEST="${TMP_DIR}/${PLUGIN_NAME}"

echo "Packaging ${PLUGIN_NAME} v${VERSION} → ${ARCHIVE}"

# Copy plugin files into a subdirectory matching the plugin name
mkdir -p "${DEST}"
rsync -a \
  --exclude='.git' \
  --exclude='.gitignore' \
  --exclude='.github' \
  --exclude='.claude' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='ui_*.py' \
  --exclude='resources_rc.py' \
  --exclude='*.zip' \
  --exclude="${ARCHIVE}" \
  --exclude='package.sh' \
  . "${DEST}/"

# Create zip
(cd "${TMP_DIR}" && zip -r "${OLDPWD}/${ARCHIVE}" "${PLUGIN_NAME}")

rm -rf "${TMP_DIR}"
echo "Done: ${ARCHIVE}"
