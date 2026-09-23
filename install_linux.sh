#!/usr/bin/env bash
# Sets up the app on Linux: conda (Miniforge) if missing, the discobox_env
# environment, and a desktop icon that runs start.sh.
#
#   bash install_linux.sh                      # folder mode only
#   bash install_linux.sh <VimbaX SDK path>    # and the camera, for live runs
#
# With the path of the Vimba X SDK (e.g. ../VimbaX_Setup-2025-1-Linux64, as for the
# Discobox app's setup-python-env.sh), vmbpy is installed from it and start.sh
# points Vimba X at its cameras. For the fan and LEDs the user must be in the
# dialout group: sudo adduser $USER dialout, then log in again.
#
# Safe to run again: it updates the environment and rewrites the icon.
set -e
cd "$(dirname "$(readlink -f "$0")")"
APP_DIR=$(pwd)

# 1. conda
for conda in "$CONDA_EXE" "$(command -v conda)" \
             ~/miniforge3/bin/conda ~/miniconda3/bin/conda ~/anaconda3/bin/conda; do
    [ -x "$conda" ] && break
done
if [ ! -x "$conda" ]; then
    echo "conda not found - installing Miniforge into ~/miniforge3"
    installer=$(mktemp --suffix=.sh)
    curl -fsSL -o "$installer" \
        "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
    bash "$installer" -b -p ~/miniforge3
    rm -f "$installer"
    conda=~/miniforge3/bin/conda
fi
echo "Using conda: $conda"

# 2. environment
if "$conda" env list | grep -q "^discobox_env "; then
    "$conda" env update -n discobox_env -f discobox_env.yaml --prune
else
    "$conda" env create -f discobox_env.yaml
fi

# 2b. the camera: vmbpy from the Vimba X SDK, and where its transport layers are
if [ -n "$1" ]; then
    sdk=${1%/}
    [ -d "$sdk" ] || { echo "\"$sdk\" is not a folder"; exit 1; }
    wheel=$(find "$sdk" -path "*/api/python/*" -name "vmbpy-*.whl" | head -n 1)
    [ -n "$wheel" ] || { echo "No vmbpy wheel found in $sdk"; exit 1; }
    "$conda" run -n discobox_env pip install "$wheel"
    echo "path=$(cd "$sdk" && pwd)" > vimbax.config
    echo "vmbpy installed from $wheel"
fi

# 3. desktop icon (app menu + desktop)
escaped=$(printf '%s' "$APP_DIR" | sed 's/[\\"`$]/\\&/g')
entry=$(cat <<EOF
[Desktop Entry]
Type=Application
Name=Varroa discobox
Comment=Detect varroa mites and score their movement
Exec=bash "$escaped/start.sh"
Path=$APP_DIR
Icon=$APP_DIR/web/static/icon.svg
Terminal=false
Categories=Science;
Actions=stop;

[Desktop Action stop]
Name=Stop the app
Exec=bash "$escaped/start.sh" stop
EOF
)
mkdir -p ~/.local/share/applications
printf '%s\n' "$entry" > ~/.local/share/applications/varroa-discobox.desktop

desktop=$(xdg-user-dir DESKTOP 2>/dev/null || echo ~/Desktop)
if [ -d "$desktop" ]; then
    launcher="$desktop/varroa-discobox.desktop"
    printf '%s\n' "$entry" > "$launcher"
    chmod +x "$launcher"
    # GNOME only launches desktop files marked trusted.
    gio set "$launcher" metadata::trusted true 2>/dev/null || true
    echo "Icon added to $desktop"
fi
chmod +x start.sh
echo "Done. Start the app from the desktop icon, the app menu, or ./start.sh"
