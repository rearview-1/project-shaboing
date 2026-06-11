from tools.verify_project_integrity import verify


def test_project_integrity_required_files_and_modules_present():
    ok, errors = verify(compile_python=False)
    assert ok, "\n".join(errors)
