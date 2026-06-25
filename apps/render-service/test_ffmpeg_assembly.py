import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

import ffmpeg_assembly as fa


def test_crossfade_cmd_uses_xfade_filter():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" in cmd
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "xfade" in filter_arg


def test_crossfade_cmd_inputs_the_same_file_twice():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4")
    assert cmd.count("/assets/loops/42.mp4") == 2


def test_crossfade_cmd_respects_fade_duration():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4", fade_duration_s=1.2)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "duration=1.2" in filter_arg


def test_crossfade_cmd_ends_with_output_path():
    cmd = fa.build_crossfade_loop_cmd("/assets/loops/42.mp4", "/tmp/looped_42.mp4")
    assert cmd[-1] == "/tmp/looped_42.mp4"


def test_pingpong_cmd_uses_reverse_and_concat():
    cmd = fa.build_pingpong_loop_cmd("/assets/loops/43.mp4", "/tmp/looped_43.mp4")
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "reverse" in filter_arg
    assert "concat" in filter_arg


def test_pingpong_cmd_ends_with_output_path():
    cmd = fa.build_pingpong_loop_cmd("/assets/loops/43.mp4", "/tmp/looped_43.mp4")
    assert cmd[-1] == "/tmp/looped_43.mp4"


def test_ken_burns_cmd_uses_zoompan_filter():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4")
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "zoompan" in filter_arg


def test_ken_burns_cmd_sets_duration_via_loop_frames():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4", duration_s=8.0)
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "8.0"


def test_ken_burns_cmd_loops_the_still_input():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4")
    assert "-loop" in cmd
    assert cmd[cmd.index("-loop") + 1] == "1"


def test_ken_burns_cmd_respects_zoom_target():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4", zoom_target=1.25)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "1.25" in filter_arg


def test_ken_burns_cmd_defaults_to_1920x1080():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4")
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "s=1920x1080" in filter_arg


def test_ken_burns_cmd_respects_vertical_output_dims():
    cmd = fa.build_ken_burns_cmd("/assets/stills/77.jpg", "/tmp/loop_77.mp4", output_w=1080, output_h=1920)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "s=1080x1920" in filter_arg


def test_pick_random_overlay_returns_a_file_from_dir(tmp_path):
    (tmp_path / "rain.mp4").write_bytes(b"x")
    (tmp_path / "snow.mp4").write_bytes(b"x")
    picked = fa.pick_random_overlay(str(tmp_path))
    assert picked in (str(tmp_path / "rain.mp4"), str(tmp_path / "snow.mp4"))


def test_pick_random_overlay_raises_on_empty_dir(tmp_path):
    import pytest
    with pytest.raises(fa.NoOverlaysAvailable):
        fa.pick_random_overlay(str(tmp_path))


def test_pick_random_overlay_raises_on_nonexistent_dir(tmp_path):
    import pytest
    with pytest.raises(fa.NoOverlaysAvailable):
        fa.pick_random_overlay(str(tmp_path / "does_not_exist"))


def test_overlay_composite_cmd_uses_screen_blend():
    cmd = fa.build_overlay_composite_cmd(
        "/tmp/loop_77.mp4", "/assets/overlays/rain.mp4", None, "/tmp/composited.mp4"
    )
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "blend=all_mode=screen" in filter_arg


def test_overlay_composite_cmd_includes_qr_overlay_when_provided():
    cmd = fa.build_overlay_composite_cmd(
        "/tmp/loop_77.mp4", "/assets/overlays/rain.mp4", "/tmp/qr.png", "/tmp/composited.mp4"
    )
    assert "/tmp/qr.png" in cmd
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay" in filter_arg


def test_overlay_composite_cmd_skips_qr_input_when_none():
    cmd = fa.build_overlay_composite_cmd(
        "/tmp/loop_77.mp4", "/assets/overlays/rain.mp4", None, "/tmp/composited.mp4"
    )
    assert "/tmp/qr.png" not in cmd


def test_inputs_manifest_repeats_loop_path_n_times():
    manifest = fa.build_inputs_manifest("/tmp/loop_77.mp4", repeat_count=3)
    lines = [l for l in manifest.splitlines() if l.strip()]
    assert len(lines) == 3
    assert all(l == "file '/tmp/loop_77.mp4'" for l in lines)


def test_concat_cmd_uses_stream_copy_no_reencode():
    cmd = fa.build_concat_cmd("/tmp/inputs.txt", "/tmp/track.mp3", "/tmp/final.mp4")
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy"


def test_concat_cmd_uses_concat_demuxer():
    cmd = fa.build_concat_cmd("/tmp/inputs.txt", "/tmp/track.mp3", "/tmp/final.mp4")
    assert "-f" in cmd
    assert cmd[cmd.index("-f") + 1] == "concat"
    assert "-safe" in cmd
    assert cmd[cmd.index("-safe") + 1] == "0"


def test_concat_cmd_uses_shortest_flag():
    cmd = fa.build_concat_cmd("/tmp/inputs.txt", "/tmp/track.mp3", "/tmp/final.mp4")
    assert "-shortest" in cmd


def test_repeat_count_for_target_duration_rounds_up():
    assert fa.repeat_count_for_target_duration(loop_duration_s=8.0, target_duration_s=240.0) == 30
    assert fa.repeat_count_for_target_duration(loop_duration_s=8.0, target_duration_s=241.0) == 31


def test_vertical_crop_cmd_uses_crop_filter_centered_on_focal_point():
    cmd = fa.build_vertical_crop_cmd("/tmp/main.mp4", "/tmp/short.mp4", focal_x=0.5, focal_y=0.5)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "crop=" in filter_arg


def test_vertical_crop_cmd_outputs_9x16_aspect_via_crop_dims():
    cmd = fa.build_vertical_crop_cmd("/tmp/main.mp4", "/tmp/short.mp4", focal_x=0.5, focal_y=0.5, source_w=1920, source_h=1080)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    # crop width for a 9:16 vertical slice of a 1080-tall source is 1080*9/16 = 607.5 -> 608
    assert "crop=608:1080" in filter_arg


def test_vertical_crop_cmd_clamps_offset_so_crop_stays_in_frame():
    # focal_x near the right edge must not push the crop box past source_w
    cmd = fa.build_vertical_crop_cmd("/tmp/main.mp4", "/tmp/short.mp4", focal_x=0.98, focal_y=0.5, source_w=1920, source_h=1080)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "crop=608:1080:1312:0" in filter_arg  # 1920-608=1312 is the max valid x offset


def test_audio_trim_cmd_uses_atrim_and_afade():
    cmd = fa.build_audio_trim_cmd("/tmp/track.mp3", "/tmp/clip_audio.mp3", start_s=30.0, duration_s=40.0)
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "atrim=30.0:70.0" in filter_arg
    assert "afade" in filter_arg


def test_loop_to_duration_cmd_stream_loops_both_inputs():
    cmd = fa.build_loop_to_duration_cmd("/tmp/video.mp4", "/tmp/audio.mp3", 7200.0, "/tmp/final.mp4")
    loop_indices = [i for i, a in enumerate(cmd) if a == "-stream_loop"]
    assert len(loop_indices) == 2
    for i in loop_indices:
        assert cmd[i + 1] == "-1"


def test_loop_to_duration_cmd_caps_with_t_flag():
    cmd = fa.build_loop_to_duration_cmd("/tmp/video.mp4", "/tmp/audio.mp3", 7200.0, "/tmp/final.mp4")
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "7200.0"


def test_loop_to_duration_cmd_stream_copies_video_and_encodes_audio():
    cmd = fa.build_loop_to_duration_cmd("/tmp/video.mp4", "/tmp/audio.mp3", 7200.0, "/tmp/final.mp4")
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"


def test_loop_to_duration_cmd_inputs_video_then_audio():
    cmd = fa.build_loop_to_duration_cmd("/tmp/video.mp4", "/tmp/audio.mp3", 7200.0, "/tmp/final.mp4")
    assert cmd.index("/tmp/video.mp4") < cmd.index("/tmp/audio.mp3")


def test_loop_to_duration_cmd_ends_with_output_path():
    cmd = fa.build_loop_to_duration_cmd("/tmp/video.mp4", "/tmp/audio.mp3", 7200.0, "/tmp/final.mp4")
    assert cmd[-1] == "/tmp/final.mp4"


def test_audio_crossfade_chain_cmd_chains_acrossfade_across_all_tracks():
    cmd = fa.build_audio_crossfade_chain_cmd(
        ["/tmp/t1.mp3", "/tmp/t2.mp3", "/tmp/t3.mp3"], "/tmp/combined.mp3"
    )
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert filter_arg.count("acrossfade") == 2
    for t in ["/tmp/t1.mp3", "/tmp/t2.mp3", "/tmp/t3.mp3"]:
        assert t in cmd


def test_audio_crossfade_chain_cmd_respects_crossfade_duration():
    cmd = fa.build_audio_crossfade_chain_cmd(
        ["/tmp/t1.mp3", "/tmp/t2.mp3"], "/tmp/combined.mp3", crossfade_s=5.0
    )
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "d=5.0" in filter_arg


def test_audio_crossfade_chain_cmd_single_track_passthrough():
    cmd = fa.build_audio_crossfade_chain_cmd(["/tmp/t1.mp3"], "/tmp/combined.mp3")
    assert "/tmp/t1.mp3" in cmd
    assert cmd[-1] == "/tmp/combined.mp3"


def test_audio_crossfade_chain_cmd_ends_with_output_path():
    cmd = fa.build_audio_crossfade_chain_cmd(["/tmp/t1.mp3", "/tmp/t2.mp3"], "/tmp/combined.mp3")
    assert cmd[-1] == "/tmp/combined.mp3"


def test_effects_cmd_applies_vignette_color_grade_and_grain():
    cmd = fa.build_effects_cmd("/tmp/composited.mp4", "/tmp/effects.mp4")
    filter_arg = cmd[cmd.index("-filter_complex") + 1]
    assert "vignette" in filter_arg
    assert "eq=" in filter_arg
    assert "noise=" in filter_arg


def test_effects_cmd_ends_with_output_path():
    cmd = fa.build_effects_cmd("/tmp/composited.mp4", "/tmp/effects.mp4")
    assert cmd[-1] == "/tmp/effects.mp4"


def test_effects_cmd_is_a_single_input_single_output_filter_chain():
    cmd = fa.build_effects_cmd("/tmp/composited.mp4", "/tmp/effects.mp4")
    assert cmd.count("/tmp/composited.mp4") == 1
    assert "-map" in cmd
    assert cmd[cmd.index("-map") + 1] == "[v]"
