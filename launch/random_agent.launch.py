#!/usr/bin/env -S ros2 launch
"""Test environment by running a random agent"""

from os import path
from typing import List

from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution


def generate_launch_description() -> LaunchDescription:

    # Declare all launch arguments
    declared_arguments = generate_declared_arguments()

    # Get substitution for all arguments
    robot_model = LaunchConfiguration("robot_model")
    robot_name = LaunchConfiguration("robot_name")
    prefix = LaunchConfiguration("prefix")
    env = LaunchConfiguration("env")
    env_kwargs = LaunchConfiguration("env_kwargs")
    n_episodes = LaunchConfiguration("n_episodes")
    seed = LaunchConfiguration("seed")
    check_env = LaunchConfiguration("check_env")
    render = LaunchConfiguration("render")
    enable_rviz = LaunchConfiguration("enable_rviz")
    rviz_config = LaunchConfiguration("rviz_config")
    use_sim_time = LaunchConfiguration("use_sim_time")
    log_level = LaunchConfiguration("log_level")

    # List of included launch descriptions
    launch_descriptions = [
        # Configure and setup interface with simulated robots inside Ignition Gazebo
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution(
                    [
                        FindPackageShare("drl_grasping"),
                        "launch",
                        "sim",
                        "sim.launch.py",
                    ]
                )
            ),
            launch_arguments=[
                ("robot_model", robot_model),
                ("robot_name", robot_name),
                ("prefix", prefix),
                ("enable_rviz", enable_rviz),
                ("rviz_config", rviz_config),
                ("use_sim_time", use_sim_time),
                ("log_level", log_level),
            ],
        ),
    ]

    # List of nodes to be launched
    nodes = [
        # Train node
        Node(
            package="drl_grasping",
            executable="random_agent.py",
            output="log",
            arguments=[
                "--env",
                env,
                "--env-kwargs",
                env_kwargs,
                # Make sure `robot_model` is specified (with priority)
                "--env-kwargs",
                ['robot_model:"', robot_model, '"'],
                "--n-episodes",
                n_episodes,
                "--seed",
                seed,
                "--check-env",
                check_env,
                "--render",
                render,
                "--ros-args",
                "--log-level",
                log_level,
            ],
            parameters=[{"use_sim_time": use_sim_time}],
        ),
    ]

    return LaunchDescription(declared_arguments + launch_descriptions + nodes)


def generate_declared_arguments() -> List[DeclareLaunchArgument]:
    """
    Generate list of all launch arguments that are declared for this launch script.
    """

    return [
        # Robot model and its name
        DeclareLaunchArgument(
            "robot_model",
            default_value="pepper_robot",
            description="Name of the robot to use. Supported options are: 'pepper_robot' and 'lunalab_summit_xl_gen'.",
        ),
        DeclareLaunchArgument(
            "robot_name",
            default_value=LaunchConfiguration("robot_model"),
            description="Name of the robot.",
        ),
        DeclareLaunchArgument(
            "prefix",
            default_value="robot_",
            description="Prefix for all robot entities. If modified, then joint names in the configuration of controllers must also be updated.",
        ),
        # Environment and its parameters
        DeclareLaunchArgument(
            "env",
            default_value="GraspPlanetary-OctreeWithColor-Gazebo-v0",
            description="Environment ID",
        ),
        DeclareLaunchArgument(
            "env_kwargs",
            default_value=['robot_model:"', LaunchConfiguration("robot_model"), '"'],
            description="Optional keyword argument to pass to the env constructor.",
        ),
        DeclareLaunchArgument(
            "n_episodes",
            default_value="1000",
            description="Overwrite the number of episodes.",
        ),
        # Random seed
        DeclareLaunchArgument(
            "seed",
            default_value="69",
            description="Random generator seed.",
        ),
        # Flag to check environment
        DeclareLaunchArgument(
            "check_env",
            default_value="True",
            description="Flag to check the environment before running the random agent.",
        ),
        # Flag to enable rendering
        DeclareLaunchArgument(
            "render",
            default_value="True",
            description="Flag to enable rendering.",
        ),
        # Miscellaneous
        DeclareLaunchArgument(
            "enable_rviz", default_value="true", description="Flag to enable RViz2."
        ),
        DeclareLaunchArgument(
            "rviz_config",
            default_value=path.join(
                get_package_share_directory("drl_grasping"), "rviz", "drl_grasping.rviz"
            ),
            description="Path to configuration for RViz2.",
        ),
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="true",
            description="If true, use simulated clock.",
        ),
        DeclareLaunchArgument(
            "log_level",
            default_value="error",
            description="The level of logging that is applied to all ROS 2 nodes launched by this script.",
        ),
    ]
