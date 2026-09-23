#!/usr/bin/env bash
# Linux counterpart of start.bat: starts the server and opens the browser.
# Close this window (or press Ctrl+C) to stop the app.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
URL=http://127.0.0.1:8000

server_up() { (echo > /dev/tcp/127.0.0.1/8000) 2>/dev/null; }

# Already running (e.g. icon double-clicked twice): just show the page.
if server_up; then
    xdg-open "$URL" >/dev/null 2>&1
    exit 0
fi

# A desktop launcher does not read ~/.bashrc, so find conda ourselves.
for conda in "$CONDA_EXE" "$(command -v conda)" \
             ~/miniforge3/bin/conda ~/miniconda3/bin/conda ~/anaconda3/bin/conda; do
    [ -x "$conda" ] && break
done
if [ ! -x "$conda" ]; then
    echo "conda not found - run install_linux.sh first."
    read -rp "Press Enter to close."
    exit 1
fi
source "$("$conda" info --base)/etc/profile.d/conda.sh"
conda activate discobox_env || { read -rp "Press Enter to close."; exit 1; }

echo "Varroa discobox - keep this window open while you use the app."
( for _ in $(seq 60); do server_up && { xdg-open "$URL" >/dev/null 2>&1; break; }; sleep 0.5; done ) &
python -m uvicorn web.server:app --host 127.0.0.1 --port 8000
read -rp "Server stopped. Press Enter to close."
