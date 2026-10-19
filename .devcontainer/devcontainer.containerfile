# Builder stage: self-contained libqi-python wheel (auditwheel-vendored,
# no conan cache needed at runtime). Python minor MUST match the final
# image (3.12 on ROS Jazzy / Ubuntu 24.04).
FROM docker.io/library/python:3.12-slim AS builder

ARG QI_REPOSITORY="https://github.com/aldebaran/libqi.git"
ARG QI_VERSION="4.0.5"
ARG QI_PATH="/tmp/libqi"

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libpython3-dev \
    patchelf \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade \
    pip \
    "conan>=2.0.0,<3.0.0" \
    "cmake>=3.23" \
    build \
    auditwheel

RUN conan profile detect --force

WORKDIR /tmp

RUN git clone \
    --depth 1 \
    --branch "qi-framework-v${QI_VERSION}" \
    "${QI_REPOSITORY}" \
    "${QI_PATH}"

RUN conan export "${QI_PATH}" \
    --version "${QI_VERSION}"

RUN git clone \
    --depth 1 \
    https://github.com/aldebaran/libqi-python.git \
    /tmp/libqi-python

WORKDIR /tmp/libqi-python

RUN conan install . \
    --build=missing \
    -c tools.build:skip_test=true

RUN python -m build \
    --config-setting cmake.define.CMAKE_TOOLCHAIN_FILE=${PWD}/build/linux-x86_64-gcc-release/generators/conan_toolchain.cmake

RUN auditwheel repair \
    --strip \
    --plat auto \
    dist/qi-*.whl

# Dev stage: ROS + NAO tooling + agent workspace.
ARG ROS_DISTRO=jazzy
# NOTE: tag hardcoded (not ${ROS_DISTRO}) — devcontainer CLIs pre-pull the
# base image without substituting Dockerfile ARG defaults (podman).
FROM docker.io/osrf/ros:jazzy-desktop-full AS dev
# Re-declare (again): pre-FROM ARGs are invisible to RUN without this.
ARG ROS_DISTRO=jazzy
ARG USERNAME=ros2dev
ARG USER_UID=1000
ARG USER_GID=$USER_UID

# Delete user if it exists in container (e.g Ubuntu Noble: ubuntu)
RUN if id -u $USER_UID ; then userdel `id -un $USER_UID` ; fi

# Create the user
RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME \
    #
    # [Optional] Add sudo support. Omit if you don't need to install software after connecting.
    && apt-get update \
    && apt-get install -y sudo \
    && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME
RUN apt-get update && apt-get upgrade -y
RUN apt-get install -y python3-pip wget git curl python3-vcstool
ENV SHELL /bin/bash

RUN mkdir -p /opt/naoqi_tools && cd /opt/naoqi_tools && \
    wget https://community-static.aldebaran.com/resources/2.8.8/choregraphe-2.8.8-ubuntu2204-standalone.tar.gz && \
    tar -xvzf choregraphe-2.8.8-ubuntu2204-standalone.tar.gz --strip-components=1 && \
    rm choregraphe-2.8.8-ubuntu2204-standalone.tar.gz

# NOTE: v2 lives on npm (@opencode/cli), NOT on the anomalyco/opencode
# GitHub releases page (that "latest" is stuck on the v1 track).
# No version pin: the script resolves the newest v2 from
# https://opencode.ai/update/api/latest/cli/npm on every build.
# --no-modify-path: no .bashrc edits during build (HOME=/root here, but the
# runtime user is $USERNAME). Binary is moved to /usr/local/bin so it is on
# PATH for every user instead of hiding in /root/.opencode/bin.
RUN curl -fsSL https://opencode.ai/v2/install | bash -s -- --no-modify-path \
    && install -m 0755 /root/.opencode/bin/opencode /usr/local/bin/opencode \
    && opencode --version

# libqi-python wheel baked by the builder stage (self-contained).
COPY --from=builder /tmp/libqi-python/wheelhouse /tmp/wheelhouse
RUN chown -R $USERNAME:$USERNAME /tmp/wheelhouse

# [Optional] Set the default user. Omit if you want to keep the default as root.
USER $USERNAME

RUN install -d -o $USERNAME -g $USERNAME /home/$USERNAME/.config/naoqi /home/$USERNAME/.local/share/opencode
RUN pip install --no-cache-dir --user --break-system-packages /tmp/wheelhouse/qi-*.whl \
    && rm -rf /tmp/wheelhouse
RUN echo "source /opt/ros/$ROS_DISTRO/setup.bash" >> /home/$USERNAME/.bashrc
RUN echo '[ -f /home/ws/install/setup.bash ] && source /home/ws/install/setup.bash' >> /home/$USERNAME/.bashrc

CMD ["/bin/bash"]

# CUDA stage: dev plus the CUDA toolkit for GPU builds (dev-cuda
# service). Separate stage so the CPU image stays lean and its binaries
# never require CUDA runtime libs. The toolkit needs gcc-12 as the nvcc
# host compiler (its 12.0 release predates the default gcc-13); the
# workspace build passes it via -DCMAKE_CUDA_HOST_COMPILER (see
# setup-workspace.sh).
FROM dev AS cuda

# NOTE: sudo (NOPASSWD for ros2dev, see above) — this stage inherits
# USER ros2dev from dev, and there is no root shell here.
RUN sudo apt-get update && sudo apt-get install -y \
    nvidia-cuda-toolkit \
    gcc-12 \
    g++-12 \
    && sudo apt-get clean && sudo rm -rf /var/lib/apt/lists/*
