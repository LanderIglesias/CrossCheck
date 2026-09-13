from pathlib import Path

from crosscheck.audio.reference import reference_text, speaker_turns, unique_speaker_count

# Small synthetic sample matching the real Earnings-21 pipe-separated format exactly (confirmed
# against data/raw/earnings21/*.txt), not a guessed format.
SAMPLE = """token|speaker|ts|endTs|punctuation|case|tags|wer_tags
Good|0||||UC|[]|[]
morning|0|||.|LC|[]|['3']
Thank|1||||UC|[]|[]
you|1|||.|LC|[]|[]
"""


def _write_sample(tmp_path: Path) -> Path:
    path = tmp_path / "sample.txt"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def test_reference_text_joins_tokens_with_punctuation(tmp_path):
    path = _write_sample(tmp_path)
    assert reference_text(path) == "Good morning. Thank you."


def test_speaker_turns_groups_consecutive_same_speaker_tokens(tmp_path):
    path = _write_sample(tmp_path)
    turns = speaker_turns(path)
    assert len(turns) == 2
    assert turns[0].speaker == "0"
    assert turns[0].text == "Good morning."
    assert turns[1].speaker == "1"
    assert turns[1].text == "Thank you."


def test_unique_speaker_count(tmp_path):
    path = _write_sample(tmp_path)
    assert unique_speaker_count(path) == 2
