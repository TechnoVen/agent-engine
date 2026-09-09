import os
import pytest
from server.watcher import (
    should_ignore_file,
    init_db,
    stage_patch_record,
    get_staged_patches,
    apply_staged_patch,
    reject_staged_patch,
    AutonomousPatchEngine
)

def test_agentignore_filter(tmp_path):
    """Verify that should_ignore_file correctly obeys ignore rules."""
    root = str(tmp_path)
    ignore_file = os.path.join(root, ".agentignore")
    with open(ignore_file, "w") as f:
        f.write("__pycache__/\n*.pyc\n.venv/\nwatcher.py\n")

    # Ignored paths
    assert should_ignore_file(os.path.join(root, ".venv/lib/test.py"), root_dir=root) is True
    assert should_ignore_file(os.path.join(root, "watcher.py"), root_dir=root) is True
    assert should_ignore_file(os.path.join(root, "__pycache__/test.cpython-312.pyc"), root_dir=root) is True

    # Allowed paths
    assert should_ignore_file(os.path.join(root, "core/app.py"), root_dir=root) is False
    assert should_ignore_file(os.path.join(root, "main.py"), root_dir=root) is False

def test_staging_database_flow(tmp_path):
    """Verify staging, retrieving, applying, and rejecting patches in SQLite."""
    test_db = str(tmp_path / "test_sentry.db")
    target_file = tmp_path / "vulnerable_app.py"
    
    original_code = "import os\nos.system('rm -rf ' + user_input)"
    patched_code = "import subprocess\nsubprocess.run(['rm', '-rf', user_input], check=True)"
    
    target_file.write_text(original_code)

    # 1. Stage patch
    patch_id = stage_patch_record(
        file_path=str(target_file),
        patch_type="security",
        risk_level="High",
        report="Command Injection risk in os.system",
        original_code=original_code,
        patched_code=patched_code,
        status="staged",
        db_path=test_db
    )
    assert patch_id == 1

    # 2. Get staged patches
    staged = get_staged_patches(db_path=test_db)
    assert len(staged) == 1
    assert staged[0]["file_path"] == str(target_file)
    assert staged[0]["risk_level"] == "High"

    # 3. Apply patch
    success = apply_staged_patch(patch_id, db_path=test_db)
    assert success is True
    assert target_file.read_text() == patched_code

    # Staged list should now be empty
    assert len(get_staged_patches(db_path=test_db)) == 0

    # 4. Stage another patch to test rejection
    p2_id = stage_patch_record(
        file_path=str(target_file),
        patch_type="lint",
        risk_level="Low",
        report="Missing docstring",
        original_code=patched_code,
        patched_code=patched_code,
        status="staged",
        db_path=test_db
    )
    assert reject_staged_patch(p2_id, db_path=test_db) is True

def test_patch_engine_sanitizer():
    """Verify code sanitizer strips markdown code blocks and commentary."""
    engine = AutonomousPatchEngine()
    
    # 1. Standard python block
    raw = "```python\nprint('hello')\n```"
    assert engine.sanitize_code_output(raw) == "print('hello')"

    # 2. Markdown with surrounding explanation
    raw_with_commentary = "Here is the fixed code:\n\n```python\ndef secure_query(user_id: int):\n    return db.fetch(user_id)\n```\n\nHope this helps!"
    assert engine.sanitize_code_output(raw_with_commentary) == "def secure_query(user_id: int):\n    return db.fetch(user_id)"

    # 3. py fence
    raw_py = "```py\nx = 42\n```"
    assert engine.sanitize_code_output(raw_py) == "x = 42"

    # 4. Pure python code without fences
    raw_clean = "def test():\n    pass"
    assert engine.sanitize_code_output(raw_clean) == raw_clean

def test_infinite_loop_breaker(tmp_path):
    """Verify that SentryWatchHandler locks files that thrash in auto-apply mode."""
    from server.watcher import SentryWatchHandler
    test_db = str(tmp_path / "loop_test.db")
    target_file = tmp_path / "thrashing_app.py"
    target_file.write_text("x = 1")

    handler = SentryWatchHandler(root_dir=str(tmp_path), auto_apply=True, db_path=test_db)
    
    # Mock engine scan_and_patch to simulate repeated patches
    handler.engine.scan_and_patch = lambda code: {
        "needs_patch": True,
        "type": "lint",
        "risk_level": "Low",
        "report": "Simulated style error",
        "original_code": code,
        "patched_code": "x = 2"
    }

    # Execute 4 consecutive modifications
    for _ in range(4):
        handler.process_file(str(target_file))

    # File must be locked
    assert str(target_file) in handler.locked_files
    staged = get_staged_patches(db_path=test_db)
    assert any("[LOOP_BREAKER]" in p["report"] for p in staged)
