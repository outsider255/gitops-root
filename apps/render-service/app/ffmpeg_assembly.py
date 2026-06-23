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


def build_ken_burns_cmd(image_path: str, output_path: str, duration_s: float = 8.0, zoom_target: float = 1.1) -> list[str]:
    """Converts a static still into a slow-zoom video loop -- the
    fallback motion technique for Nano Banana Pro stills (no Veo
    video-generation call needed). zoompan's d= (frame count) controls
    duration at a fixed fps; -t additionally caps output length so the
    two stay consistent regardless of zoompan's internal frame math."""
    fps = 25
    frame_count = int(duration_s * fps)
    zoom_expr = f"zoom+({zoom_target}-1)/{frame_count}"
    filter_complex = (
        f"[0:v]zoompan=z='{zoom_expr}':d={frame_count}:s=1920x1080:fps={fps}[v]"
    )
    return [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-t", str(duration_s),
        output_path,
    ]


import os
import random


class NoOverlaysAvailable(Exception):
    pass


def pick_random_overlay(overlays_dir: str = "/assets/overlays") -> str:
    """Randomly selects one pre-downloaded atmospheric overlay (rain,
    snow, film grain, etc.) per render run."""
    if not os.path.isdir(overlays_dir):
        raise NoOverlaysAvailable(f"{overlays_dir} does not exist")
    candidates = [
        os.path.join(overlays_dir, f)
        for f in os.listdir(overlays_dir)
        if os.path.isfile(os.path.join(overlays_dir, f))
    ]
    if not candidates:
        raise NoOverlaysAvailable(f"no overlay files in {overlays_dir}")
    return random.choice(candidates)


def build_overlay_composite_cmd(
    base_video_path: str,
    overlay_path: str,
    qr_image_path: str | None,
    output_path: str,
) -> list[str]:
    """Low-opacity screen-blends the atmospheric overlay onto the base
    loop, then (if provided) overlays a QR code in the bottom-right
    corner -- qr_image_path is generated once per video by the caller
    (Task 9) via the `qrcode` package from overlay_config.qr_url, not
    inside ffmpeg (ffmpeg has no native QR generation)."""
    cmd = ["ffmpeg", "-y", "-i", base_video_path, "-i", overlay_path]
    if qr_image_path:
        cmd += ["-i", qr_image_path]
        filter_complex = (
            "[0:v][1:v]blend=all_mode=screen:all_opacity=0.25[bg];"
            "[bg][2:v]overlay=W-w-20:H-h-20[v]"
        )
    else:
        filter_complex = "[0:v][1:v]blend=all_mode=screen:all_opacity=0.25[v]"
    cmd += ["-filter_complex", filter_complex, "-map", "[v]", output_path]
    return cmd
