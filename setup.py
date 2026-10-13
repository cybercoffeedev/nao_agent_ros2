from setuptools import find_packages, setup

package_name = "nao_agent"

setup (
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/bringup.launch.py']),
        ('share/' + package_name + '/config', ['config/params.yaml']),
        ('share/' + package_name + '/config/grammar', ['config/grammar/response.json']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer="cybercoffeedev",
    maintainer_email="cybercoffeedev@users.noreply.github.com",
    description="Chat bridge: prompt -> llama_ros -> speech + NAO posture actions.",
    license='Apache-2.0',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            'chat_bridge_node = nao_agent.chat_bridge_node:main',
            'motion_server_node = nao_agent.motion.server:main',
        ],
    },
)