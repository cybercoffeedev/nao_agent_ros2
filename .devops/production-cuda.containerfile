# Production CUDA image (GPU inference for llama + whisper).
# Same layout as production.containerfile, but on NVIDIA CUDA images with
# GGML_CUDA enabled at build time. Host needs nvidia-container-toolkit;
# without it the container falls back to CPU (slow) or fails on device
# request, depending on the runtime.

# Stage 1: libqi wheel (identical to the CPU image).
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

# Stage 2: CUDA devel + ROS Jazzy + workspace build (also the runtime;
# slimming the runtime image is a follow-up, not a blocker).
FROM nvidia/cuda:12.6.3-cudnn-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=jazzy \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

# ROS 2 Jazzy apt source (no prebuilt ROS+CUDA image exists).
RUN apt-get update && apt-get install -y curl gnupg lsb-release \
    && curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(lsb_release -cs) main" \
        > /etc/apt/sources.list.d/ros2.list \
    && apt-get update && apt-get install -y \
    ros-jazzy-ros-base \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-vcstool \
    build-essential \
    cmake \
    git \
    python3-pip \
    portaudio19-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && echo "source /opt/ros/jazzy/setup.bash" >> /root/.bashrc

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

# GPU layer counts (single source stays config/params.yaml + whisper.yaml;
# baked at build time so stock bringup needs no extra override file).
ARG LLAMA_GPU_LAYERS=99
ARG WHISPER_GPU=true
RUN . /opt/ros/jazzy/setup.sh \
    && colcon build --cmake-args -DGGML_CUDA=ON \
    && sed -i "s/n_gpu_layers: 0/n_gpu_layers: ${LLAMA_GPU_LAYERS}/" \
        /ws/install/nao_agent/share/nao_agent/config/params.yaml \
    && sed -i "s/enabled: false/enabled: ${WHISPER_GPU}/" \
        /ws/install/nao_agent/share/nao_agent/config/whisper.yaml \
    && grep -q "n_gpu_layers: ${LLAMA_GPU_LAYERS}" \
        /ws/install/nao_agent/share/nao_agent/config/params.yaml \
    && grep -q "enabled: ${WHISPER_GPU}" \
        /ws/install/nao_agent/share/nao_agent/config/whisper.yaml

# Model/ROS caches (backed by named volumes in compose, no redownloads).
RUN mkdir -p /root/.cache/huggingface /root/.cache/whisper /root/.ros/log

COPY .devops/ros_entrypoint.sh /opt/nao_agent/entrypoint.sh
ENTRYPOINT ["/opt/nao_agent/entrypoint.sh"]
