#!/usr/bin/env bash
# Linux counterpart of start.bat: starts the server in the background and
# opens the browser. Output goes to server.log.
#
#   ./start.sh         start (or just open the page if already running)
#   ./start.sh stop    stop the server
cd "$(dirname "$(readlink -f "$0")")" || exit 1
URL=http://127.0.0.1:8000
PID_FILE=server.pid

server_up() { (echo > /dev/tcp/127.0.0.1/8000) 2>/dev/null; }

# There is no terminal when started from the icon, so show errors in a popup.
fail() {
    echo "$1" >&2
    zenity --error --title="Varroa discobox" --text="$1" 2>/dev/null \
        || notify-send "Varroa discobox" "$1" 2>/dev/null
    exit 1
}

if [ "$1" = stop ]; then
    # The server may have stopped by itself and its pid been reused, so only
    # kill the pid if it is still our server.
    pid=$(cat "$PID_FILE" 2>/dev/null)
    grep -qs uvicorn "/proc/$pid/cmdline" && kill "$pid" 2>/dev/null
    rm -f "$PID_FILE"
    exit 0
fi

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
[ -x "$conda" ] || fail "conda not found - run install_linux.sh first."
source "$("$conda" info --base)/etc/profile.d/conda.sh"
conda activate discobox_env 2>/dev/null \
    || fail "The discobox_env environment is missing - run install_linux.sh first."

# The camera: tell Vimba X where its transport layers are, as run-discobox.sh does.
if [ -f vimbax.config ]; then
    source ./vimbax.config
    cti_path=$(find "${path%/}" -path "*/cti" -type d 2>/dev/null | head -n 1)
    [ -n "$cti_path" ] && export GENICAM_GENTL64_PATH=":$cti_path"
fi

# The server stops by itself once the last browser tab is closed (unless a live
# test run is still going; then once it has ended).
DISCOBOX_AUTO_STOP=1 nohup python -m uvicorn web.server:app --host 127.0.0.1 --port 8000 > server.log 2>&1 &
echo $! > "$PID_FILE"

for _ in $(seq 60); do
    if server_up; then
        xdg-open "$URL" >/dev/null 2>&1
        exit 0
    fi
    kill -0 "$(cat "$PID_FILE")" 2>/dev/null || break
    sleep 0.5
done
fail "The app did not start. Last lines of server.log:

$(tail -n 15 server.log)"
