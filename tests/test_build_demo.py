from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "store"))
import build_demo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import vault_core as vc


def test_demo_build_real_v3_pipeline_end_to_end(tmp_path, monkeypatch):
    source = tmp_path / "source-real"
    source.mkdir()
    transcript = "\n".join(
        [
            '---',
            'title: "Fair Value Gap Demo"',
            'video_id: "demo123"',
            '---',
        ] + [f"0:{i:02d} Fair Value Gap imbalance delivery context example {i}." for i in range(20)]
    )
    (source / "2022 ICT Mentorship - Demo.md").write_text(transcript, encoding="utf-8")
    monkeypatch.setattr(build_demo, "STORE_DIR", tmp_path / "store-real")

    package = build_demo.build_demo(source, count=1, cta="https://example.test/#pricing")

    db, _chroma_dir, who = vc.open_vault(
        vault_file=package / "ict-vault.kevin", license_file=package / "license.key")
    try:
        assert who == "demo@ict-vault.free"
        assert db.execute("SELECT COUNT(*) FROM transcripts_fts").fetchone()[0] > 0
        assert vc.demo_info(db)["count"] == "1"
    finally:
        db.close()
    assert not (build_demo.STORE_DIR / "demo_build" / "_stage").exists()
    assert not (build_demo.STORE_DIR / "demo_build" / "_artifacts").exists()


def test_demo_build_routes_encryption_and_license_through_isolated_build(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "2022 ICT Mentorship - Ep 01.md").write_text("demo", encoding="utf-8")
    monkeypatch.setattr(build_demo, "STORE_DIR", tmp_path / "store")
    calls = []

    def fake_run(command, env):
        calls.append(dict(env))
        source_dir = Path(env["ICT_SOURCE_DIR"])
        build_dir = Path(env["ICT_BUILD_DIR"])
        assert build_dir.resolve() != source_dir.resolve()
        if command[-1].endswith("ict_ingest_v3.py"):
            (build_dir / "kg.db").write_bytes(b"kg")
            (build_dir / "_vectors").mkdir()
            (build_dir / ".ict-v3-resume-manifest.json").write_text("{}")
        else:
            (build_dir / "ict-vault.kevin").write_bytes(b"vault")
        return subprocess.CompletedProcess(command, 0)

    def fake_license(email, purchase, vault_dir):
        license_path = Path(vault_dir) / "license_demo.key"
        license_path.write_bytes(b"license")
        return license_path, "demo"

    monkeypatch.setattr(build_demo.subprocess, "run", fake_run)
    monkeypatch.setattr(build_demo, "generate_license", fake_license)
    build_demo.build_demo(source, count=1)

    assert Path(calls[0]["ICT_BUILD_DIR"]).name == "_artifacts"
    assert calls[0]["ICT_BUILD_DIR"] == calls[1]["ICT_BUILD_DIR"]
    package = build_demo.STORE_DIR / "demo_build" / "ict-vault-demo"
    assert (package / "ict-vault.kevin").read_bytes() == b"vault"
    assert (package / "license.key").read_bytes() == b"license"
    assert (package / "metadata_enricher.py").exists()
    assert (package / "VAULT.md").exists()
