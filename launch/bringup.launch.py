"""System composition: naoqi_driver + llama_ros + whisper_ros + agent nodes."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    nao_ip = LaunchConfiguration("nao_ip")
    nao_port = LaunchConfiguration("nao_port")
    # Single config for the whole stack: `chat_bridge_node:` section feeds
    # the bridge, `/**:` block feeds llama_node.
    params_file = LaunchConfiguration("params_file")
    # Whisper has its own yaml (no `/**:` block: that would shadow its
    # `model.*` keys, see config/whisper.yaml).
    whisper_params_file = LaunchConfiguration("whisper_params_file")

    naoqi_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("naoqi_driver"),
                "launch",
                "naoqi_driver.launch.py",
            )
        ),
        launch_arguments={
            "nao_ip": nao_ip,
            "nao_port": nao_port,
        }.items(),
    )

    llama_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("llama_bringup"),
                "launch",
                "base.launch.py",
            )
        ),
        launch_arguments={
            "params_file": params_file,
            # Pin the namespace: launch configurations are context-global
            # (first declaration wins), so without this the `namespace`
            # arg declared by naoqi_driver.launch.py would silently push
            # llama_node into /naoqi_driver instead of /llama.
            "namespace": "llama",
        }.items(),
    )

    bridge = Node(
        package="nao_agent",
        executable="chat_bridge_node",
        name="chat_bridge_node",
        output="screen",
        parameters=[params_file],
    )

    motion = Node(
        package="nao_agent",
        executable="motion_server_node",
        name="motion_server_node",
        output="screen",
        parameters=[params_file, {"nao_ip": nao_ip, "nao_port": nao_port}],
    )

    whisper_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("whisper_bringup"),
                "launch",
                "whisper.launch.py",
            )
        ),
        launch_arguments={
            "whisper_params_file": whisper_params_file,
            "silero_vad_params_file": whisper_params_file,
            # No host-mic capturer: audio comes from the NAO driver.
            "launch_audio_capturer": "False",
        }.items(),
    )

    feeder = Node(
        package="nao_agent",
        executable="stt_feeder_node",
        name="stt_feeder_node",
        output="screen",
        parameters=[params_file],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("nao_ip", default_value="127.0.0.1"),
            DeclareLaunchArgument("nao_port", default_value="9559"),
            DeclareLaunchArgument(
                "params_file",
                default_value=os.path.join(
                    get_package_share_directory("nao_agent"),
                    "config",
                    "params.yaml",
                ),
            ),
            DeclareLaunchArgument(
                "whisper_params_file",
                default_value=os.path.join(
                    get_package_share_directory("nao_agent"),
                    "config",
                    "whisper.yaml",
                ),
            ),
            naoqi_launch,
            llama_launch,
            bridge,
            motion,
            whisper_launch,
            feeder,
        ]
    )
