import argparse
import io
import json
import os
import shutil
import struct
import sys
import time
import uuid
from pathlib import Path


DEFAULT_BRIDGE_ROOT = r"D:\tools\python_scripts\VaM 1.20.0.6\Custom\PluginData\NeuralCompanionBridge"
DEFAULT_TARGET_ATOM_UID = "Person"
DEFAULT_TARGET_STORABLE_ID = "plugin#0_NeuralCompanionBridge"


def wav_duration_seconds(path: Path) -> float:
    data = path.read_bytes()
    stream = io.BytesIO(data)

    if stream.read(4) != b"RIFF":
        raise ValueError(f"Not a RIFF WAV file: {path}")
    stream.read(4)
    if stream.read(4) != b"WAVE":
        raise ValueError(f"Not a WAVE file: {path}")

    sample_rate = 0
    block_align = 0
    data_size = 0

    while True:
        header = stream.read(8)
        if len(header) < 8:
            break
        chunk_id, chunk_size = struct.unpack("<4sI", header)
        chunk_data = stream.read(chunk_size)
        if chunk_size % 2 == 1:
            stream.read(1)

        if chunk_id == b"fmt " and len(chunk_data) >= 16:
            _audio_format, _num_channels, sample_rate, _byte_rate, block_align, _bits_per_sample = struct.unpack(
                "<HHIIHH", chunk_data[:16]
            )
        elif chunk_id == b"data":
            data_size = chunk_size

        if sample_rate > 0 and block_align > 0 and data_size > 0:
            break

    if sample_rate <= 0 or block_align <= 0:
        raise ValueError(f"Could not read WAV format details from: {path}")
    if data_size <= 0:
        return 0.0

    frame_count = data_size / float(block_align)
    return frame_count / float(sample_rate)


def atomic_write_json(path: Path, payload: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def read_status(status_path: Path) -> dict | None:
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_payload(
    *,
    target_atom_uid: str,
    target_storable_id: str,
    emotion: str,
    speaking: bool,
    audio_path: str,
    audio_duration_seconds: float,
    text: str,
    play_audio_in_vam: bool,
) -> dict:
    return {
        "target_atom_uid": target_atom_uid,
        "target_storable_id": target_storable_id,
        "emotion": (emotion or "neutral").strip().lower() or "neutral",
        "speaking": bool(speaking),
        "timeline_auto_resume": True,
        "expression_preset": "",
        "timeline_clip": "",
        "audio_path": audio_path,
        "audio_duration_seconds": float(audio_duration_seconds or 0.0),
        "text": text or "",
        "play_audio_in_vam": bool(play_audio_in_vam),
        "enabled": True,
    }


def send_command(inbox_dir: Path, session_id: str, action: str, payload: dict) -> tuple[Path, dict]:
    command_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    command_path = inbox_dir / f"{command_id}_{action}.json"
    body = {
        "session_id": session_id,
        "command_id": command_id,
        "sent_at": time.time(),
        "action": action,
        "payload": payload,
    }
    atomic_write_json(command_path, body)
    return command_path, body


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone VaM bridge audio tester.")
    parser.add_argument("--bridge-root", default=DEFAULT_BRIDGE_ROOT, help="VaM NeuralCompanionBridge root")
    parser.add_argument("--wav", default=str(Path(__file__).with_name("input.wav")), help="Input WAV to stage")
    parser.add_argument("--text", default="VaM bridge audio test", help="Text note to include in the speech chunk")
    parser.add_argument("--emotion", default="neutral", help="Emotion field to send")
    parser.add_argument("--target-atom-uid", default=DEFAULT_TARGET_ATOM_UID, help="Target VaM atom UID")
    parser.add_argument("--target-storable-id", default=DEFAULT_TARGET_STORABLE_ID, help="Target plugin storable id")
    parser.add_argument("--watch-seconds", type=float, default=10.0, help="How long to watch status.json after sending")
    parser.add_argument("--skip-session-start", action="store_true", help="Do not emit a session_start command")
    parser.add_argument("--snapshot-dir", default=str(Path(__file__).resolve().parent), help="Where to save sent command snapshots")
    args = parser.parse_args()

    bridge_root = Path(args.bridge_root).expanduser().resolve()
    inbox_dir = bridge_root / "inbox"
    outbox_dir = bridge_root / "outbox"
    audio_dir = bridge_root / "audio"
    status_path = outbox_dir / "status.json"
    input_wav = Path(args.wav).expanduser().resolve()
    snapshot_dir = Path(args.snapshot_dir).expanduser().resolve()

    if not input_wav.exists():
        print(f"Input WAV not found: {input_wav}", file=sys.stderr)
        return 1

    inbox_dir.mkdir(parents=True, exist_ok=True)
    outbox_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    duration_seconds = wav_duration_seconds(input_wav)
    session_id = f"vamtest_{uuid.uuid4().hex[:10]}"
    chunk_id = input_wav.stem + "_" + uuid.uuid4().hex[:8]
    staged_wav = audio_dir / f"{chunk_id}.wav"
    shutil.copy2(input_wav, staged_wav)

    print(f"Bridge root: {bridge_root}")
    print(f"Input WAV:   {input_wav}")
    print(f"Staged WAV:  {staged_wav}")
    print(f"Duration:    {duration_seconds:.2f}s")

    if not args.skip_session_start:
        start_payload = build_payload(
            target_atom_uid=args.target_atom_uid,
            target_storable_id=args.target_storable_id,
            emotion=args.emotion,
            speaking=False,
            audio_path="",
            audio_duration_seconds=0.0,
            text="",
            play_audio_in_vam=False,
        )
        start_path, start_body = send_command(inbox_dir, session_id, "session_start", start_payload)
        atomic_write_json(snapshot_dir / "last_sent_session_start.json", start_body)
        print(f"Sent:        {start_path.name}")
        time.sleep(0.15)

    speech_payload = build_payload(
        target_atom_uid=args.target_atom_uid,
        target_storable_id=args.target_storable_id,
        emotion=args.emotion,
        speaking=True,
        audio_path=str(staged_wav),
        audio_duration_seconds=duration_seconds,
        text=args.text,
        play_audio_in_vam=True,
    )
    speech_path, speech_body = send_command(inbox_dir, session_id, "speech_chunk", speech_payload)
    atomic_write_json(snapshot_dir / "last_sent_speech_chunk.json", speech_body)
    print(f"Sent:        {speech_path.name}")
    print(f"Snapshot:    {snapshot_dir / 'last_sent_speech_chunk.json'}")
    print("")

    deadline = time.time() + max(0.0, args.watch_seconds)
    last_snapshot = None
    while time.time() < deadline:
        snapshot = read_status(status_path)
        if snapshot and snapshot != last_snapshot:
            print("Status:")
            print(json.dumps(snapshot, indent=2))
            print("")
            last_snapshot = snapshot
        time.sleep(0.2)

    final_status = read_status(status_path)
    if final_status:
        print("Final status:")
        print(json.dumps(final_status, indent=2))
    else:
        print(f"No readable status found at {status_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
