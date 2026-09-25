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
    # Also a server started by hand or from another copy of the app.
    pkill -f "uvicorn web.server:app"
    rm -f "$PID_FILE"
    exit 0
fi

# Get the newest version from GitHub before starting. Offline, or if the pull
# fails, the current version starts; the reason is in update.log.
if [ -z "$DISCOBOX_UPDATED" ] && [ -d .git ] && command -v git >/dev/null; then
    old=$(git rev-parse HEAD)
    # chmod +x must not count as a local change, or git refuses to pull.
    git config core.fileMode false
    if GIT_TERMINAL_PROMPT=0 timeout 30 git pull --ff-only > update.log 2>&1; then
        new=$(git rev-parse HEAD)
        if [ "$old" != "$new" ]; then
            git diff --quiet "$old" "$new" -- discobox_env.yaml || env_changed=1
            # This script may have changed under us: run the new one.
            DISCOBOX_UPDATED=1 DISCOBOX_ENV_CHANGED=$env_changed exec bash "$0" "$@"
        fi
    else
        notify-send "Varroa discobox" "Could not update, starting the current version (see update.log)." 2>/dev/null
    fi
fi

# Folder, commit and "live run going" (1/0) of the server on port 8000, one per line.
running_version() {
    exec 3<>/dev/tcp/127.0.0.1/8000 || return
    printf 'GET /api/version HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n' >&3
    timeout 5 cat <&3 | tr -d '\r' | sed '1,/^$/d'
    exec 3<&-
}

# A server is already running (e.g. icon double-clicked twice). If it runs this
# folder's current code, just show the page. One from another folder or an older
# version (e.g. started by hand, which never stops by itself) would keep serving
# old code, so it is replaced - unless a live test run is going on it.
if server_up; then
    mapfile -t running < <(running_version)
    if [ "${running[0]}" = "$(pwd -P)" ] && [ "${running[1]}" = "$(git rev-parse HEAD 2>/dev/null)" ]; then
        xdg-open "$URL" >/dev/null 2>&1
        exit 0
    fi
    if [ "${running[2]}" = 1 ]; then
        notify-send "Varroa discobox" "A test run is going on an older version. Start the app again once it has ended to update." 2>/dev/null
        xdg-open "$URL" >/dev/null 2>&1
        exit 0
    fi
    echo "Stopping the server running other code: ${running[0]:-an older version}" >> update.log
    pkill -f "uvicorn web.server:app"
    for _ in $(seq 20); do server_up || break; sleep 0.5; done
    server_up && pkill -9 -f "uvicorn web.server:app" && sleep 1
    server_up && fail "Port 8000 is used by another program - close it and start again."
    rm -f "$PID_FILE"
fi

# A desktop launcher does not read ~/.bashrc, so find conda ourselves.
for conda in "$CONDA_EXE" "$(command -v conda)" \
             ~/miniforge3/bin/conda ~/miniconda3/bin/conda ~/anaconda3/bin/conda; do
    [ -x "$conda" ] && break
done
[ -x "$conda" ] || fail "conda not found - run install_linux.sh first."
if [ -n "$DISCOBOX_ENV_CHANGED" ]; then
    notify-send "Varroa discobox" "Updating the Python environment, this can take a few minutes." 2>/dev/null
    "$conda" env update -n discobox_env -f discobox_env.yaml >> update.log 2>&1
fi
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
