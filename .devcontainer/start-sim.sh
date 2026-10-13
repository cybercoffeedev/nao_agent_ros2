#!/bin/bash
# Autostart the naoqi-bin simulator with NAO V6 identity.
# Wired as postStartCommand: runs on every container start, exits promptly
# while the sim stays behind. Safe to re-run (open port = seed only).
set -e

export LD_LIBRARY_PATH=/opt/naoqi_tools/lib
BIN=/opt/naoqi_tools/bin/naoqi-bin
QICLI=/opt/naoqi_tools/bin/qicli
LOG=/tmp/naoqi-bin.log
MODEL_PREF=/opt/naoqi_tools/etc/naoqi/ALRobotModel.xml

# The image ships ALRobotModel.xml pointing at the Pepper model
# (JULIETTEY20B2C.xml), which makes Choregraphe open a Pepper.
# Pin the NAO V6 (H25) model instead; idempotent across restarts.
if [ -f "$MODEL_PREF" ]; then
    sed -i 's|value="[^"]*\.xml"|value="NAOH25V60.xml"|' "$MODEL_PREF"
fi

port_open() { (</dev/tcp/127.0.0.1/9559) 2>/dev/null; }

if ! port_open; then
    if pgrep -x naoqi-bin >/dev/null; then
        echo "naoqi-bin process exists but port closed, waiting for it..."
        for _ in $(seq 1 30); do
            port_open && break
            sleep 1
        done
    fi
fi

if ! port_open; then
    echo "starting naoqi-bin..."
    setsid nohup "$BIN" < /dev/null > "$LOG" 2>&1 &
    for _ in $(seq 1 30); do
        port_open && break
        sleep 1
    done
    port_open || { echo "naoqi-bin did not open 9559, see $LOG"; exit 1; }
fi

# The port opens before services register; the insert itself is the probe
# (idempotent, retry until ALMemory answers).
seed_key() {
    for _ in $(seq 1 60); do
        if "$QICLI" call ALMemory.insertData "$1" "$2" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

seed_key "RobotConfig/System/Version" "2.8.7" \
    || { echo "ALMemory never appeared"; exit 1; }
seed_key "RobotConfig/Body/BaseVersion" "V6"
seed_key "RobotConfig/Body/Type" "nao"
echo "sim ready with NAO V6 identity (log: $LOG)"
