#!/bin/bash
# Production entrypoint: source the stack, then run the compose command.
set -e
source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash
exec "$@"
