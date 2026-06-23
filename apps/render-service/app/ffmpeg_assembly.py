def build_crossfade_loop_cmd(input_path: str, output_path: str, fade_duration_s: float = 0.5) -> list[str]:
    """Default seamless-loop technique: blends the clip's tail over its
    own head via xfade, so playback loops without a visible jump cut."""
    filter_complex = (
        f"[0:v][0:v]xfade=transition=fade:duration={fade_duration_s}:offset=0[v]"
    )
    return [
        "ffmpeg", "-y",
        "-i", input_path,
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        output_path,
    ]


def build_pingpong_loop_cmd(input_path: str, output_path: str) -> list[str]:
    """Fallback for non-directional/ambient assets (floating dust, embers):
    duplicate the stream, reverse it, join back-to-back for a
    mathematically flawless loop (no fade artifacts)."""
    filter_complex = (
        "[0:v]split[a][b];[b]reverse[br];[a][br]concat=n=2:v=1:a=0[v]"
    )
    return [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        output_path,
    ]
