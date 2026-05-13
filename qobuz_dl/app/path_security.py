import platform
import shutil
import subprocess
from pathlib import Path


ALLOWED_AUDIO_SUFFIXES = (
    ".flac",
    ".mp3",
    ".m4a",
    ".ogg",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
)


def audio_path_allowed_for_lyrics_attach(audio_path: str, roots) -> bool:
    try:
        p = Path(audio_path).expanduser().resolve()
    except OSError:
        return False
    if not p.is_file():
        return False
    allowed = False
    for root in roots:
        try:
            p.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        return False
    name_low = str(p.name or "").lower()
    if name_low.endswith(".missing.txt"):
        return True
    return p.suffix.lower() in ALLOWED_AUDIO_SUFFIXES


def reveal_file_in_os(file_path: Path) -> None:
    """Open the system file manager and reveal ``file_path``."""
    p = file_path.expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", "-R", str(p)])
    elif system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        if shutil.which("nautilus"):
            subprocess.Popen(["nautilus", "--select", str(p)])
        elif shutil.which("dolphin"):
            subprocess.Popen(["dolphin", "--select", str(p)])
        elif shutil.which("nemo"):
            subprocess.Popen(["nemo", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])
