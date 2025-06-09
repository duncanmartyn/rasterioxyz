"""Config of utils for testing core RasterioXYZ functionality."""

import socket
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from rasterio import DatasetReader, MemoryFile, transform

from rasterioxyz.tile import Tiles

DEFAULT_CASE = {
    "crs": 3857,
    "bounds": (-20037508.34, -20048966.1, 20037508.34, 20048966.1),
}
DEFAULT_DTYPE = "uint8"


@pytest.fixture
def test_data_param(
    request: pytest.FixtureRequest,
) -> Generator[DatasetReader]:
    """Fixture yielding a `rasterio.DatasetReader` for parameterised tests."""
    with create_test_data(**request.param) as td:
        yield td


@contextmanager
def create_test_data(
    *,
    crs: int | None,
    bounds: Sequence[int | float],
    dtype: str = DEFAULT_DTYPE,
) -> Generator[DatasetReader]:
    """Yield a `rasterio.DatasetReader`, cleaning up when done."""
    height = width = 360
    count = 3
    tf = transform.from_bounds(*bounds, width, height) if crs else None
    array = generate_test_array(dtype, count, width, height)

    memfile = MemoryFile()
    try:
        with memfile.open(
            driver="GTiff",
            height=height,
            width=width,
            count=count,
            crs=crs,
            transform=tf,
            dtype=dtype,
        ) as dst:
            dst.write(array)
        yield memfile.open()
    finally:
        memfile.close()


def generate_test_array(
    dtype: str,
    count: int,
    width: int,
    height: int,
) -> np.ndarray:
    """Return test array data to tile."""
    dtype_info = {"i": np.iinfo, "u": np.iinfo, "f": np.finfo}
    info = dtype_info.get(np.dtype(dtype).kind)(dtype)
    rng = np.random.default_rng()
    return rng.uniform(info.min, info.max, (count, height, width)).astype(
        dtype,
    )


def get_png_dimensions(file_path: Path) -> tuple[int, int]:
    """Return width and height of a PNG in pixels."""
    with Path.open(file_path, "rb") as src:
        src.read(8)
        ihdr = src.read(25)
        width = int.from_bytes(ihdr[8:12], "big")
        height = int.from_bytes(ihdr[12:16], "big")
        return width, height


def run_tile_server(port: int, tiles: Tiles, driver: str) -> None:
    """Run tile server, used in non-blocking thread."""
    tiles.serve(port=port, driver=driver, quiet=True)


def get_free_port() -> int:
    """Return a free port on which to serve."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]
