#!/usr/bin/env bash

# AgentsLoop CLI Installer
# This script installs AgentsLoop CLI in an isolated environment.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting AgentsLoop CLI installation...${NC}"

# Configuration
PACKAGE_SPEC="${AGENTSLOOP_PACKAGE_SPEC:-git+https://github.com/Thomas97460/AgentsLoop-CLI.git}"
INSTALL_DIR="${AGENTSLOOP_INSTALL_DIR:-$HOME/.local/share/agentsloop-cli}"
BIN_DIR="${AGENTSLOOP_BIN_DIR:-$HOME/.local/bin}"

# 1. Check for uv (recommended)
if command -v uv >/dev/null 2>&1; then
    echo -e "${GREEN}Found 'uv'. Installing using 'uv tool'...${NC}"
    uv tool install "$PACKAGE_SPEC" --force
    echo -e "${GREEN}Installation successful!${NC}"
    exit 0
fi

# 2. Fallback to standard python3 + venv
echo -e "Note: 'uv' not found. Falling back to standard Python installation."

PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo -e "${RED}Error: python3 is required but was not found.${NC}"
    exit 1
fi

# Check Python version
if ! "$PYTHON_BIN" -c 'import sys; exit(0 if sys.version_info >= (3, 12) else 1)'; then
    echo -e "${RED}Error: Python 3.12 or newer is required.${NC}"
    exit 1
fi

echo -e "Installing into ${INSTALL_DIR}..."

# Create virtual environment
"$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip --quiet
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade "$PACKAGE_SPEC" --quiet

# Create shim
mkdir -p "$BIN_DIR"
cat >"$BIN_DIR/agentsloop" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_DIR/venv/bin/agentsloop" "\$@"
EOF
chmod +x "$BIN_DIR/agentsloop"

echo -e "${GREEN}AgentsLoop CLI installed successfully at $BIN_DIR/agentsloop${NC}"

# Check if BIN_DIR is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "${BLUE}Notice: $BIN_DIR is not in your PATH.${NC}"
    echo -e "You might want to add it to your shell configuration (e.g., .bashrc or .zshrc):"
    echo -e "  export PATH=\"$BIN_DIR:\$PATH\""
fi

echo -e "${GREEN}Done!${NC}"
