#!/usr/bin/env sh
set -eu

PACKAGE_SPEC="${AGENTSLOOP_PACKAGE_SPEC:-git+https://github.com/Thomas97460/AgentsLoop-CLI.git}"
INSTALL_DIR="${AGENTSLOOP_INSTALL_DIR:-$HOME/.local/share/agentsloop-cli}"
BIN_DIR="${AGENTSLOOP_BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="${PYTHON:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "python3 is required but was not found." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)'; then
  echo "Python 3.12 or newer is required." >&2
  exit 1
fi

"$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/venv/bin/python" -m pip install --upgrade "$PACKAGE_SPEC"

mkdir -p "$BIN_DIR"
cat >"$BIN_DIR/agentsloop" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_DIR/venv/bin/agentsloop" "\$@"
EOF
chmod +x "$BIN_DIR/agentsloop"

echo "AgentsLoop CLI installed at $BIN_DIR/agentsloop"
echo "Add $BIN_DIR to PATH if the agentsloop command is not found."
