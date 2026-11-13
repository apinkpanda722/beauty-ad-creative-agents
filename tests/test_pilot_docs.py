"""The docs-only CLI rewrites codebook and instructions and nothing else."""

from io import StringIO

from beautyads.eval import pilot_docs


def test_rewrites_only_docs_inside_interim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "data/interim/pilot"
    out_dir.mkdir(parents=True)
    sheet = out_dir / "pilot_sheet.csv"
    key = out_dir / "pilot_key.json"
    sheet.write_text("sheet", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    out = StringIO()
    assert pilot_docs.main(["--out-dir", str(out_dir)], out=out) == 0
    assert (
        (out_dir / "pilot_codebook.csv")
        .read_text(encoding="utf-8")
        .startswith("axis,value,note")
    )
    assert (out_dir / "pilot_instructions.md").is_file()
    assert sheet.read_text(encoding="utf-8") == "sheet"
    assert key.read_text(encoding="utf-8") == "key"


def test_output_outside_interim_is_rejected_without_writing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = StringIO()
    target = tmp_path / "tracked"
    assert pilot_docs.main(["--out-dir", str(target)], out=out) == 2
    assert "PREFLIGHT_FAILED OUTPUT_NOT_IGNORED" in out.getvalue()
    assert not target.exists()
