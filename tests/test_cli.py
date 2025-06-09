"""Tests for RasterioXYZ CLI functionality."""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from _pytest.monkeypatch import MonkeyPatch

from rasterioxyz import _cli

from .conftest import (
    DEFAULT_CASE,
    create_test_data,
)


def test_cli_help() -> None:
    """Test the -h flag produces a 0 return code."""
    result = subprocess.call(  # noqa: S603
        [
            sys.executable,
            "-m",
            "rasterioxyz._cli",
            "-h",
        ],
    )
    assert result == 0


def test_cli_write(monkeypatch: MonkeyPatch) -> None:
    """Test the write command produces a 0 return code.

    Conflict between subprocess and monkeypatch mean dummy CLI usage is
    necessary (or easier) here.
    """
    with (
        create_test_data(**DEFAULT_CASE) as test_data,
        TemporaryDirectory() as tmp_dir,
    ):
        test_tiles_dir = Path(tmp_dir) / Path(test_data.name).stem
        test_tiles_dir.mkdir()
        monkeypatch.setattr(
            "rasterioxyz._cli.rasterio.open",
            lambda _: test_data,
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "rasterioxyz._cli",
                "write",
                "test/path.tif",
                "--max",
                "1",
                "--dst",
                str(test_tiles_dir),
            ],
        )
        _cli.main()
        assert list(test_tiles_dir.glob("**/*.PNG"))
