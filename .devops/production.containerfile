# Production image for nao_agent_ros2 (phase 1: build + runtime in one
# app stage; slimming the runtime is a follow-up, not a blocker).
# Sibling sources come from dependencies.repos (pinned there), so the
# build context is this repo alone. Model weights are NOT baked: the
# first boot downloads them into named volumes (needs net at runtime).

# Stage 1: self-contained libqi-python wheel (same recipe as dev image).
FROM docker.io/library/python:3.12-slim AS qi-builder

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libpython3-dev \
    patchelf \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip "conan>=2.0.0,<3.0.0" auditwheel
RUN conan profile detect --force

WORKDIR /tmp
RUN git clone --depth 1 --branch "qi-framework-v4.0.5" \
    https://github.com/aldebaran/libqi.git /tmp/libqi
RUN conan export /tmp/libqi
RUN git clone --depth 1 \
    https://github.com/aldebaran/libqi-python.git \
    /tmp/libqi-python

WORKDIR /tmp/libqi-python
RUN conan install . --build=missing -c tools.build:skip_test=true
RUN python -m build \
    --config-setting cmake.define.CMAKE_TOOLCHAIN_FILE=${PWD}/build/linux-x86_64-gcc-release/generators/conan_toolchain.cmake
RUN auditwheel repair --strip --plat auto dist/qi-*.whl

# Stage 2: workspace build (also the runtime: apt/build tools stay so no
# shared library goes missing on first boot without robot access).
FROM docker.io/osrf/ros:jazzy-ros-base

ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=jazzy

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    python3-pip \
    python3-vcstool \
    python3-rosdep \
    portaudio19-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=qi-builder /tmp/libqi-python/wheelhouse /tmp/wheelhouse
RUN pip install --no-cache-dir --break-system-packages /tmp/wheelhouse/qi-*.whl \
    && rm -rf /tmp/wheelhouse \
    && python3 -c "import qi; print('libqi ok')"

WORKDIR /ws
COPY dependencies.repos /ws/dependencies.repos
COPY . /ws/src/nao_agent_ros2
RUN cd /ws && vcs import src < dependencies.repos

RUN apt-get update \
    && rosdep init 2>/dev/null || true \
    && rosdep update \
    && rosdep install --from-paths src --ignore-src -r -y --rosdistro jazzy \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN . /opt/ros/jazzy/setup.sh && colcon build

# Model/ROS caches (backed by named volumes in compose, no redownloads).
RUN mkdir -p /root/.cache/huggingface /root/.cache/whisper /root/.ros/log

COPY .devops/ros_entrypoint.sh /opt/nao_agent/entrypoint.sh
ENTRYPOINT ["/opt/nao_agent/entrypoint.sh"]
