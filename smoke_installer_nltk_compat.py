from pathlib import Path


ROOT = Path(__file__).resolve().parent


def test_companion_requirements_pin_nltk_compatibility() -> None:
    requirements = (ROOT / "requirements.companion.txt").read_text(encoding="utf-8")
    requirement_lines = {
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "nltk==3.10.0" in requirement_lines


if __name__ == "__main__":
    test_companion_requirements_pin_nltk_compatibility()
    print("Installer NLTK compatibility smoke passed.")
