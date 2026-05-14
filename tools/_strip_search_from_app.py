"""Remove duplicate search UI from gui/app.js (now in searchController.js)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "qobuz_dl" / "gui" / "app.js"


def main() -> None:
    lines = APP.read_text(encoding="utf-8").splitlines(True)
    out = []
    i = 0
    skipping = False
    while i < len(lines):
        ln = lines[i]
        if not skipping and ln.strip().startswith("// ── Search tab"):
            skipping = True
            i += 1
            continue
        if skipping:
            if ln.strip().startswith("// ── Settings tab"):
                skipping = False
                out.append(ln)
            i += 1
            continue
        out.append(ln)
        i += 1
    APP.write_text("".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
    print("Stripped search section from app.js")
