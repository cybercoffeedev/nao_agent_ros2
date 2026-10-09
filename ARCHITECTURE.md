# Architecture Overview
This document describes the architecture of `nao_agent_ros2`: a ROS 2 agent
that gives the NAO6 robot conversational abilities by bridging a local LLM
(`llama_ros`) with the robot speech stack (`naoqi_driver2` / ALTextToSpeech).
It is a living document — update it as the codebase evolves.

## 1. Project Structure

```text
[src/nao_agent_ros2/]
├── nao_agent/                # Main Python package (ament_python)
│   ├── __init__.py
│   ├── chat_bridge_node.py   # Composition root / thin ROS wrapper (entry point)
│   ├── llm/                  # LLM adapter layer (no direct NAOqi knowledge)
│   │   ├── __init__.py
│   │   ├── chat_client.py    # Adapter for GenerateChatCompletions action
│   │   └── prompts.py        # Pure prompt logic, system prompt (no ROS deps)
│   └── speech/               # Speech adapter layer (no LLM knowledge)
│       ├── __init__.py
│       └── speaker.py        # Adapter for /speech -> ALTextToSpeech
├── config/
│   └── params.yaml           # Single config: `chat_bridge_node:` section + `/**:` model block
├── launch/
│   └── bringup.launch.py     # System composition: driver + LLM + bridge
├── resource/nao_agent        # ament package marker (do not touch)
├── dependencies.repos        # vcstool sources: naoqi_driver2, llama_ros
├── package.xml               # Package manifest (depends: rclpy, std_msgs, llama_msgs)
├── setup.py                  # Build config + console_scripts entry points
├── setup.cfg                 # Script install dir
└── ARCHITECTURE.md           # This document
```

External (sibling source checkouts, not part of this repo):

```text
src/
├── llama_ros/                # LLM backend (llama_node, llama_msgs, llama_bringup)
└── naoqi_driver2/            # NAOqi <-> ROS 2 driver (naoqi_driver_node)
```

## 2. High-Level System Diagram

```text
[Developer/Test] -- std_msgs/String --> [/prompt]
                                          |
                                          v
                                  [chat_bridge_node]
                                   /          \
            GenerateChatCompletions action    publishes
            /llama or /naoqi_driver            |
            generate_chat_completions          v
                     |                  [/speech: std_msgs/String]
                     v                          |
              [llama_node]                      v
              (llama_ros, GGUF)         [naoqi_driver_node]
                                        SpeechSubscriber
                                                |
                                                v
                                    ALTextToSpeech.say(text)
                                      (robot / naoqi-bin)
```

Data flow: a test prompt injected on `/prompt` is wrapped into
`messages[]` (system + user), sent as a `GenerateChatCompletions` goal,
and the resulting `choices[0].message.content` is published on `/speech`,
which `naoqi_driver2` forwards to `ALTextToSpeech.say()`. The chain is
fully asynchronous (goal_response -> result -> publish) with single-flight
backpressure: a new prompt is dropped while one is in progress.

## 3. Core Components

### 3.1. chat_bridge_node

Name: `chat_bridge_node` (`nao_agent/chat_bridge_node.py`)

Description: Composition root and only ROS-aware orchestrator. Subscribes
to the prompt topic, drives the LLM action client through its callback
chain, and publishes the answer for speech. Holds no LLM/NAOqi logic
itself — that lives in the `llm/` and `speech/` adapters.

Technologies: Python, rclpy, rclpy.action

Deployment: ROS 2 node launched via `bringup.launch.py`; also runnable
standalone with `ros2 run nao_agent chat_bridge_node --ros-args --params-file ...`

### 3.2. ChatClient (llm adapter)

Name: `ChatClient` (`nao_agent/llm/chat_client.py`)

Description: Adapter over `llama_msgs/action/GenerateChatCompletions`.
Builds the goal (`messages`, `add_generation_prompt`, `use_jinja`,
`sampling_config.temp`) and exposes non-blocking `send_async()` plus the
`extract_text()` result parser. Single extension point for constrained
decoding: tools / `sampling_config.grammar` (GBNF).

Technologies: Python, rclpy.action, llama_msgs

### 3.3. prompts (pure logic)

Name: `prompts` (`nao_agent/llm/prompts.py`)

Description: Framework-free message builder (`build_messages()`); the prompt
text lives only in `config/params.yaml` (`system_prompt`). Testable without ROS.

Technologies: Pure Python

### 3.4. Speaker (speech adapter)

Name: `Speaker` (`nao_agent/speech/speaker.py`)

Description: Publishes plain-text answers on the speech topic consumed by
`naoqi_driver2`'s `SpeechSubscriber`. Skips empty responses with a warning.

Technologies: Python, rclpy, std_msgs

### 3.5. Launch composition

Name: `bringup.launch.py`

Description: Declares `nao_ip`, `nao_port`, `params_file`
(default `config/params.yaml`, holding both the `chat_bridge_node:`
section and the `/**:` model block) and
includes `naoqi_driver.launch.py`, `llama_bringup/base.launch.py` plus the
`chat_bridge_node`.

Technologies: ROS 2 Launch (Python)

## 4. Data Stores

### 4.1. ROS graph (transient transport)

Name: Topics `/prompt`, `/speech`; action `generate_chat_completions`

Type: ROS 2 DDS topics / action (in-memory, no persistence)

Purpose: `/prompt` carries test-injected user utterances
(`std_msgs/String`); `/speech` carries LLM answers to the driver;
the action carries chat goals/results including streaming feedback.

Key Schemas/Collections: `std_msgs/msg/String`,
`llama_msgs/action/GenerateChatCompletions`,
`llama_msgs/msg/ChatMessage`

### 4.2. Model artifacts

Name: GGUF model files (e.g. `bielik-7b-instruct-v0.1.Q4_K_M.gguf`)

Type: Local files, fetched from HuggingFace Hub per `llama_bringup` config

Purpose: Weights loaded by `llama_node` at startup; selected via
`model_params_file`.

## 5. External Integrations / APIs

llama_ros (`llama_node` + `llama_msgs`)

Purpose: Local LLM inference backend (chat completions, tokenize,
embeddings).

Integration Method: ROS 2 action `GenerateChatCompletions`
(default server `/llama/generate_chat_completions`; deployments that
remap the node namespace, e.g. `/naoqi_driver`, must align the
`llama_action` param — see `config/params.yaml`).

naoqi_driver2 (`naoqi_driver_node`)

Purpose: NAOqi <-> ROS 2 bridge; its `SpeechSubscriber` maps
`/speech` (`std_msgs/String`) to `ALTextToSpeech.say()` and exposes
`set_language` / `get_language` services plus the `listen` action.

Integration Method: ROS 2 topic `/speech`; services
`/naoqi_driver/set_language`, `/naoqi_driver/get_language`.

NAOqi / naoqi-bin simulator (`ALTextToSpeech`)

Purpose: On-robot speech synthesis; the `naoqi-bin` simulator used in
development provides no audio output or microphone, so verification is
done by observing `/speech` traffic.

Integration Method: libqi session (`nao_ip`, `nao_port`, default
`127.0.0.1:9559`).

## 6. Deployment & Infrastructure

Cloud Provider: None (local robot / workstation deployment)

Key Services Used: ROS 2 Jazzy, colcon workspace (`/home/ws`),
DDS with `ROS_DOMAIN_ID=42`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`

CI/CD Pipeline: None yet (manual `colcon build --packages-select nao_agent`)

Monitoring & Logging: ROS 2 logging (`/rosout`); key observables are the
`chat_bridge` prompt/LLM logs and `ros2 topic echo /speech`

## 7. Security Considerations

Authentication: None — trusted local network / localhost only.

Authorization: None — any host in the DDS domain can publish `/prompt`
and trigger speech; do not expose the domain beyond the lab network.

Data Encryption: None at the ROS layer (plain DDS on localhost).

Key Security Tools/Practices: `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`
to keep discovery off the wider network.

## 8. Development & Testing Environment

Local Setup Instructions:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select llama_msgs nao_agent
source install/setup.bash
ros2 launch nao_agent bringup.launch.py nao_ip:=127.0.0.1 nao_port:=9559
# terminal 2: ros2 topic echo /speech
# terminal 3: ros2 topic pub --once /prompt std_msgs/msg/String "{data: 'Cześć, kim jesteś?'}"
```

Testing Frameworks: Manual smoke checks (`build_messages`, `make_goal`,
node init/destroy scripts); `pytest` listed as test dependency, no test
suite yet.

Code Quality Tools: `py_compile` gate; `ament_flake8` / `ament_pep257`
declared as test dependencies.

## 9. Future Considerations / Roadmap

- Constrained decoding for robot actions: wire `tools` /
  `sampling_config.grammar` (GBNF) through `ChatClient.make_goal`
  (marked `TODO` in code) so the LLM can select moves/poses, with a
  Strategy-per-action executor behind the bridge.
- Real voice input: `whisper_ros` integration replacing the `/prompt`
  test-injection topic (currently out of scope: `naoqi-bin` has no mic).
- Runtime action remapping: recreate the `ActionClient` when the
  `llama_action` parameter changes instead of binding it once at startup.
- Persistent test suite under `test/` (prompts, goal building, speaker
  with a mocked publisher).

## 10. Project Identification

Project Name: nao_agent_ros2 (NAO6 conversational agent, ROS 2)

Repository URL: https://github.com/cybercoffeedev/nao_agent_ros2

Primary Contact/Team: cybercoffeedev

Date of Last Update: 2026-10-08

## 11. Glossary / Acronyms

NAOqi: SoftBank Robotics middleware/framework running on NAO robots;
exposes services such as ALTextToSpeech.

ALTextToSpeech: NAOqi service for speech synthesis (`say()`).

naoqi-bin: NAOqi simulator binary; no audio output or microphone support.

llama_ros: ROS 2 wrapper around llama.cpp exposing LLM inference as
actions/services (by Miguel Ángel González Santamarta et al.).

GenerateChatCompletions: `llama_msgs` action for chat-style inference
(`messages[]` -> `choices[].message.content`).

GBNF: Grammar format (GGML BNF) constraining LLM sampling to a formal
grammar — planned for robot action selection.

GGUF: Model file format used by llama.cpp (e.g. Qwen3 quantizations).

Single-flight: Backpressure policy dropping new prompts while one LLM
goal is in progress, avoiding overlapping `say()` calls.
