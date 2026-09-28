from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    nao_ip = LaunchConfiguration('nao_ip')
    nao_port = LaunchConfiguration('nao_port')

    naoqi_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('naoqi_driver'),
                'launch', 'naoqi_driver.launch.py',
            )
        ),
        launch_arguments={
            'nao_ip': nao_ip,
            'nao_port': nao_port,
        }.items(),
    )

    tts = Node(
        package='nao_agent',
        executable='tts_node',
        name='tts_node',
        output='screen',
        parameters=[os.path.join(
            get_package_share_directory('nao_agent'),
            'config', 'params.yaml')],
    )

    return LaunchDescription([
        DeclareLaunchArgument('nao_ip', default_value='127.0.0.1'),
        DeclareLaunchArgument('nao_port', default_value='9559'),
        naoqi_launch,
        tts,
    ])