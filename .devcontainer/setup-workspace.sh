#!/bin/bash
# First-create workspace bootstrap for the nao_agent_ros2 dev container.
# Recreates the canonical layout next to this package:
#   /home/ws/src/{nao_agent_ros2 (bind mount),llama_ros,whisper_ros,audio_common,naoqi_driver2}
# then resolves deps and builds the full workspace (libqi wheel is baked
# into the image; here we only verify it imports).
# Safe to re-run: every step skips when already done.
set -e

WS=/home/ws
PKG_DIR=/home/ws/src/nao_agent_ros2
export PATH="$HOME/.local/bin:$PATH"

echo "==> 1/4 sibling checkouts (llama_ros, whisper_ros, audio_common, naoqi_driver2)"
# Wrapper first so later steps can use short commands. Single-target -D
# form: cannot misfire into multi-source mode.
sudo install -D -m 755 "$PKG_DIR/.devcontainer/bin/choregraphe" /usr/local/bin/choregraphe
# Named tooling volumes start root-owned; claim them so ros2dev can write.
sudo install -d -o "$(whoami)" -g "$(whoami)" \
    /home/ros2dev/.config/opencode /home/ros2dev/.local/share/opencode /home/ros2dev/.cache/opencode \
    /home/ros2dev/.cache/huggingface
# The bind mount only covers this package; the parents are daemon-created
# root-owned, so claim them before vcs/colcon write next to us.
sudo install -d -o "$(whoami)" -g "$(whoami)" "$WS" "$WS/src"
if [ -d "$WS/src/llama_ros/.git" ] && [ -d "$WS/src/whisper_ros/.git" ] \
    && [ -d "$WS/src/audio_common/.git" ] && [ -d "$WS/src/naoqi_driver2/.git" ]; then
    echo "siblings present, skipping clone"
    echo "(pinned versions; git pull inside to update, or drop the src volumes)"
else
    # PYTHONWARNINGS hides an unrelated pkg_resources deprecation from vcstool.
    PYTHONWARNINGS="ignore::DeprecationWarning" \
        vcs import "$WS/src" < "$PKG_DIR/dependencies.repos"
fi

echo "==> 2/4 rosdep dependencies"
# The base image wipes apt archives after every install (docker-clean),
# which would keep the apt-cache volume permanently empty.
sudo rm -f /etc/apt/apt.conf.d/docker-clean
echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' \
    | sudo tee /etc/apt/apt.conf.d/keep-cache > /dev/null
apt-config dump 2>/dev/null | grep -q 'Keep-Downloaded-Packages "true"' \
    || echo "WARNING: apt keep-cache not effective, downloads will repeat"
[ "$(stat -c %d /var/cache/apt)" != "$(stat -c %d /)" ] \
    || echo "WARNING: /var/cache/apt is not a persistent volume, downloads will repeat"
sudo rosdep init 2>/dev/null || true
rosdep update
sudo rosdep install --from-paths "$WS/src" --ignore-src -y

echo "==> 3/4 libqi-python wheel (motion backend, baked by the image)"
if python3 -c "import qi" 2>/dev/null; then
    echo "qi OK"
else
    echo "ERROR: libqi-python missing — rebuild the dev image, do not build by hand."
    exit 1
fi

echo "==> 4/4 colcon build (full workspace; long on first run)"
for d in build install log; do
    mount | grep -q " on $WS/$d " \
        || echo "WARNING: $WS/$d is not a persistent volume, next create will rebuild from scratch"
done
cd "$WS"
colcon build

echo "OK. Next: source install/setup.bash"
echo "Motion test: python3 -c \"import qi\" must print nothing (no error)."
