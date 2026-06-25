"""Entrypoint for the Shorts clip Job container. Invoked as:
python3 clip_entrypoint.py <vertical_loop_path> <track_path> <audio_start_s> <audio_duration_s> <output_path>
The loop is already vertical-native (generated 9:16 by Mode A), so no crop
step is needed here -- cropping a 16:9 loop around a guessed focal point
was dropped in favor of dedicated vertical generation."""
import subprocess
import sys
import tempfile
import os

import ffmpeg_assembly as fa


def main(loop_path, track_path, audio_start_s, audio_duration_s, output_path):
    with tempfile.TemporaryDirectory() as tmp:
        trimmed_audio_path = os.path.join(tmp, "clip_audio.mp3")
        subprocess.run(
            fa.build_audio_trim_cmd(track_path, trimmed_audio_path, float(audio_start_s), float(audio_duration_s)),
            check=True, capture_output=True, timeout=60,
        )

        subprocess.run(
            fa.build_loop_to_duration_cmd(loop_path, trimmed_audio_path, float(audio_duration_s), output_path),
            check=True, capture_output=True, timeout=60,
        )

    print(f"clip complete: {output_path}")


if __name__ == "__main__":
    main(*sys.argv[1:6])
