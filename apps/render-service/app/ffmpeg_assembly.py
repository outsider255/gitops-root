import os
import random
import math


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


def repeat_count_for_target_duration(loop_duration_s: float, target_duration_s: float) -> int:
    return math.ceil(target_duration_s / loop_duration_s)


def build_inputs_manifest(loop_path: str, repeat_count: int) -> str:
    """Returns the inputs.txt CONTENT (caller writes it to disk) --
    repeats the seamless loop path enough times to cover the audio
    duration. Stream-copy concat below then wraps it without
    re-encoding a single frame."""
    return "\n".join(f"file '{loop_path}'" for _ in range(repeat_count)) + "\n"


def build_vertical_crop_cmd(
    input_path: str,
    output_path: str,
    focal_x: float,
    focal_y: float,
    source_w: int = 1920,
    source_h: int = 1080,
) -> list[str]:
    """Crops a 16:9 source to a 9:16 vertical slice centered on the
    stored focal point, clamped so the crop box never extends past the
    source frame. Free -- reuses the existing 16:9 loop, no second
    generation call (regenerating a native-vertical asset would double
    the visual-generation cost per loop)."""
    crop_w = round(source_h * 9 / 16)
    crop_h = source_h
    target_x = round(focal_x * source_w - crop_w / 2)
    max_x = source_w - crop_w
    x = max(0, min(target_x, max_x))
    filter_complex = f"[0:v]crop={crop_w}:{crop_h}:{x}:0[v]"
    return [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        output_path,
    ]


def build_audio_trim_cmd(input_path: str, output_path: str, start_s: float, duration_s: float, fade_s: float = 1.0) -> list[str]:
    """Trims a 30-45s segment from the main track (with fade in/out) so
    the Short previews the actual audio from the full video."""
    end_s = start_s + duration_s
    filter_complex = (
        f"[0:a]atrim={start_s}:{end_s},"
        f"afade=t=in:st={start_s}:d={fade_s},"
        f"afade=t=out:st={end_s - fade_s}:d={fade_s}[a]"
    )
    return [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[a]",
        output_path,
    ]


def build_effects_cmd(
    input_path: str,
    output_path: str,
    vignette_angle: str = "PI/5",
    saturation: float = 1.08,
    contrast: float = 1.04,
    grain_strength: int = 8,
) -> list[str]:
    """Replaces camera motion with simple static-loop post-effects:
    a subtle vignette, a light color grade, and low-strength film grain
    (noise=allf=t+u keeps it temporal+uniform so it reads as grain, not
    flat static)."""
    filter_complex = (
        f"[0:v]vignette={vignette_angle},"
        f"eq=saturation={saturation}:contrast={contrast},"
        f"noise=alls={grain_strength}:allf=t+u[v]"
    )
    return [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        output_path,
    ]


def build_loop_to_duration_cmd(video_path: str, audio_path: str, target_duration_s: float, output_path: str) -> list[str]:
    """make_lofi.ps1's actual technique: -stream_loop -1 repeats each input
    indefinitely without building a giant concat manifest, -t caps the
    output once both streams reach target_duration_s. Video stays
    -c:v copy (no re-encode, same perf characteristic as the reference
    script); audio is re-encoded to aac like the rest of this pipeline."""
    return [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", video_path,
        "-stream_loop", "-1", "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-t", str(target_duration_s),
        output_path,
    ]


def build_audio_crossfade_chain_cmd(track_paths: list[str], output_path: str, crossfade_s: float = 3.0) -> list[str]:
    """Stitches N distinct tracks into one combined audio file via chained
    acrossfade (mirrors make_lofi.ps1's acrossfade=d=3:c1=tri:c2=tri),
    giving real variety before build_loop_to_duration_cmd loops the result
    to fill the full runtime. A single track passes through untouched."""
    cmd = ["ffmpeg", "-y"]
    for path in track_paths:
        cmd += ["-i", path]

    if len(track_paths) == 1:
        cmd += [output_path]
        return cmd

    filter_parts = []
    prev_label = "0:a"
    for i in range(1, len(track_paths)):
        out_label = f"af{i}" if i < len(track_paths) - 1 else "a"
        filter_parts.append(
            f"[{prev_label}][{i}:a]acrossfade=d={crossfade_s}:c1=tri:c2=tri[{out_label}]"
        )
        prev_label = out_label

    filter_complex = ";".join(filter_parts)
    cmd += ["-filter_complex", filter_complex, "-map", "[a]", output_path]
    return cmd


def build_concat_cmd(inputs_txt_path: str, audio_path: str, output_path: str) -> list[str]:
    """Resource-safe compile: never re-encodes raw frames (-c:v copy),
    so a 1-2 hour output renders near-instantly regardless of host CPU
    headroom."""
    return [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", inputs_txt_path,
        "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac",
        "-shortest",
        output_path,
    ]
