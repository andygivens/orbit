import subprocess

import pytest


@pytest.mark.contract
def test_validate_openapi_schema():
    result = subprocess.run(
        [
            "python",
            "scripts/contract_validate.py",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Validation failed:\n{result.stdout}\n{result.stderr}"
    assert "validated successfully" in result.stdout
