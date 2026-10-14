"""Pure audio shaping for the STT path (no ROS dependencies).

The NAO driver publishes interlaced multichannel buffers
(48 kHz, front/rear mics); Silero/whisper expect mono 16 kHz. These helpers
pick the front-mic pair, average it to mono and decimate by integer ratio.
Conversion to audio_common_msgs is done by the feeder node, so this module
is testable without ROS.
"""

FRONT_LEFT = 0
FRONT_RIGHT = 2
TARGET_RATE = 16000
INT16_MIN = -32768
INT16_MAX = 32767


def select_front_mono(data, channel_map):
    """Average the front-mic channels of each interlaced frame to mono.

    Falls back to averaging all channels when the map holds no front mic.
    Returns a list of ints; empty input gives empty output.
    """
    data = [int(v) for v in (data or [])]
    channel_map = [int(c) for c in (channel_map or [])]
    channels = len(channel_map)
    if not data or channels < 1:
        return []
    front = [i for i, c in enumerate(channel_map) if c in (FRONT_LEFT, FRONT_RIGHT)]
    picked = front or list(range(channels))
    frames = len(data) // channels
    mono = []
    for f in range(frames):
        base = f * channels
        mono.append(sum(data[base + i] for i in picked) // len(picked))
    return mono


def decimate(samples, in_rate, out_rate=TARGET_RATE):
    """Downsample by integer ratio with a boxcar average per group."""
    in_rate = int(in_rate)
    out_rate = int(out_rate)
    if in_rate <= 0 or out_rate <= 0 or in_rate % out_rate != 0:
        raise ValueError(f"unsupported rate conversion: {in_rate} -> {out_rate}")
    ratio = in_rate // out_rate
    if ratio < 1:
        raise ValueError(f"unsupported rate conversion: {in_rate} -> {out_rate}")
    samples = [int(v) for v in (samples or [])]
    return [sum(samples[i : i + ratio]) // ratio for i in range(0, len(samples), ratio)]


def shape_for_stt(data, channel_map, frequency):
    """Full path: front-mic mono at TARGET_RATE, clamped to int16."""
    mono = decimate(select_front_mono(data, channel_map), frequency, TARGET_RATE)
    return [min(INT16_MAX, max(INT16_MIN, v)) for v in mono]
