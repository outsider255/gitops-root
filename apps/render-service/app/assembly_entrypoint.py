"""Entrypoint for the real assembly Job container. Invoked as:
python3 assembly_entrypoint.py <loop_path> <category> <output_path> <track_path> [<track_path> ...]
Chains Tasks 5-8's command builders and actually runs them via subprocess
(this file, unlike ffmpeg_assembly.py's pure builders, is the one place
that executes ffmpeg for real)."""
import subprocess
import sys
import tempfile
import os

import ffmpeg_assembly as fa

TRACK_TARGET_DURATION_S = 7200.0


def main(loop_path: str, category: str, output_path: str, track_paths: list[str]):
    with tempfile.TemporaryDirectory() as tmp:
        looped_path = os.path.join(tmp, "looped.mp4")
        subprocess.run(
            fa.build_crossfade_loop_cmd(loop_path, looped_path),
            check=True, capture_output=True, timeout=120,
        )

        try:
            overlay_path = fa.pick_random_overlay()
            composited_path = os.path.join(tmp, "composited.mp4")
            subprocess.run(
                fa.build_overlay_composite_cmd(looped_path, overlay_path, None, composited_path),
                check=True, capture_output=True, timeout=120,
            )
        except fa.NoOverlaysAvailable:
            composited_path = looped_path

        effects_path = os.path.join(tmp, "effects.mp4")
        subprocess.run(
            fa.build_effects_cmd(composited_path, effects_path),
            check=True, capture_output=True, timeout=120,
        )

        if len(track_paths) > 1:
            combined_audio_path = os.path.join(tmp, "combined_audio.mp3")
            subprocess.run(
                fa.build_audio_crossfade_chain_cmd(track_paths, combined_audio_path),
                check=True, capture_output=True, timeout=120,
            )
        else:
            combined_audio_path = track_paths[0]

        subprocess.run(
            fa.build_loop_to_duration_cmd(effects_path, combined_audio_path, TRACK_TARGET_DURATION_S, output_path),
            check=True, capture_output=True, timeout=900,
        )

    print(f"assembly complete: {output_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
