"""Tests for core RasterioXYZ functionality."""

import shutil
import threading
from collections.abc import Generator
from pathlib import Path

import pytest
import requests
from rasterio import DatasetReader
from rasterio.enums import Resampling as Res
from rasterio.errors import CRSError

from rasterioxyz import Tiles

from .conftest import (
    DEFAULT_CASE,
    TEST_OUTPUT_DIR,
    create_test_data,
    get_free_port,
    get_png_dimensions,
    run_tile_server,
)


@pytest.mark.parametrize(
    ("test_data_param", "zooms", "pixels", "resampling", "error"),
    [
        (DEFAULT_CASE, [0], 256, Res.nearest, None),
        ({"crs": None, "bounds": None}, [0], 256, Res.nearest, CRSError),
        (DEFAULT_CASE, 0, 256, Res.nearest, TypeError),
        (DEFAULT_CASE, ["0"], 256, Res.nearest, TypeError),
        (DEFAULT_CASE, [50], 256, Res.nearest, ValueError),
        (DEFAULT_CASE, [0], "256", Res.nearest, TypeError),
        (DEFAULT_CASE, [0], 1000, Res.nearest, ValueError),
        (DEFAULT_CASE, [0], 256, "nearest", TypeError),
    ],
    indirect=["test_data_param"],
)
def test_constructor(
    test_data_param: DatasetReader,
    zooms: int,
    pixels: int,
    resampling: str,
    error: Exception,
) -> None:
    """Test construction of a `Tiles` object."""
    if error:
        with pytest.raises(error):
            Tiles(test_data_param, zooms, pixels, resampling)
    else:
        tiles = Tiles(test_data_param, zooms, pixels, resampling)
        assert isinstance(tiles.tiles, Generator)


@pytest.mark.parametrize(
    (
        "test_data_param",
        "zooms",
        "driver",
        "out_tiles",
        "allow_upsample",
        "error",
    ),
    [
        (
            DEFAULT_CASE,
            [0, 1],
            "PNG",
            ["0/0/0", "1/0/0", "1/0/1", "1/1/0", "1/1/1"],
            True,
            None,
        ),
        (
            {"crs": 4326, "bounds": (-180, -90, 180, 90)},
            [0, 1],
            "PNG",
            ["0/0/0", "1/0/0", "1/0/1", "1/1/0", "1/1/1"],
            True,
            None,
        ),
        (
            {"crs": 4326, "bounds": (-180, -90, 180, 90)},
            [0, 1],
            "PNG",
            ["0/0/0"],
            False,
            None,
        ),
        (
            {"crs": 4326, "bounds": (-180, -90, 180, 90), "dtype": "float32"},
            [0, 1],
            "PNG",
            ["0/0/0"],
            False,
            None,
        ),
        (DEFAULT_CASE, [0], 0, [], True, TypeError),
        (DEFAULT_CASE, [0], "TIF", [], True, ValueError),
        (DEFAULT_CASE, [0], "PNG", [], True, FileNotFoundError),
    ],
    indirect=["test_data_param"],
)
def test_write(  # noqa: PLR0913
    test_data_param: DatasetReader,
    zooms: list[int],
    driver: str,
    out_tiles: list[float | int],
    allow_upsample: bool,  # noqa: FBT001
    error: Exception,
) -> None:
    """Test writing of generated tiles."""
    tiles = Tiles(test_data_param, zooms, allow_upsample=allow_upsample)
    test_tiles_dir = TEST_OUTPUT_DIR / Path(test_data_param.name).stem

    if error and not test_tiles_dir.exists():
        with pytest.raises(error):
            tiles.write(test_tiles_dir, driver)
    else:
        test_tiles_dir.mkdir()
        tiles.write(test_tiles_dir, driver)

        tile_image_paths: list[Path] = []
        for tile in out_tiles:
            path = test_tiles_dir / f"{tile}.{driver.lower()}"
            tile_image_paths.append(path)
            assert path.exists()

        assert all(
            get_png_dimensions(image_path) == (tiles.pixels, tiles.pixels)
            for image_path in tile_image_paths
        )
        shutil.rmtree(test_tiles_dir, ignore_errors=True)


@pytest.mark.parametrize(
    ("test_data_param", "driver", "error"),
    [
        (
            DEFAULT_CASE,
            "PNG",
            None,
        ),
        (DEFAULT_CASE, 0, TypeError),
        (DEFAULT_CASE, "TIF", ValueError),
    ],
    indirect=["test_data_param"],
)
def test_serve(
    test_data_param: DatasetReader,
    driver: str,
    error: Exception,
) -> None:
    """Test serving of generated tiles.

    Thread for serving spawned here ends with the process that spawned it.
    As this is in a test environment, it can be unpredictable as to when it's
    closed and require manual termination (e.g. IDE or terminal instance).
    This isn't ideal and as a quick fix will be addressed in future.
    Child processes aren't possible due to unpickleable
    `rasterio.DatasetReader` objects.

    Testing the 304 (cached) response by passing the If-Modified-Since header
    worked locally but not in CI and so is not covered.

    When running test cases in parallel, `get_free_port` risks race conditions.
    """
    tiles = Tiles(test_data_param, zooms=[0])
    codes = {
        "OK": 200,
        "non-tile": 204,
        "cached": 304,
        "malformed": 400,
        "not found": 404,
    }
    if error:
        with pytest.raises(error):
            tiles.serve(driver=driver)
    else:
        port = get_free_port()
        svr_thread = threading.Thread(
            target=run_tile_server,
            args=(port, tiles, driver),
            daemon=True,
        )
        svr_thread.start()
        try:
            z = x = y = 0
            drv = driver.lower()
            response_200 = requests.get(
                f"http://localhost:{port}/{z}/{x}/{y}.{drv}",
                timeout=5,
            )
            assert response_200.status_code == codes["OK"]
            response_204 = requests.get(
                f"http://localhost:{port}/favicon.ico",
                timeout=5,
            )
            assert response_204.status_code == codes["non-tile"]
            response_400 = requests.get(
                f"http://localhost:{port}/{x}/{y}.{drv}",
                timeout=5,
            )
            assert response_400.status_code == codes["malformed"]
            # NOTE: tests 404 for greater than max zoom, not empty tile
            response_404 = requests.get(
                f"http://localhost:{port}/{z + 1}/0/0.{drv}",
                timeout=5,
            )
            assert response_404.status_code == codes["not found"]
        finally:
            pass


def test_eq() -> None:
    """Ensure calls of __eq__ produce the correct result."""
    with create_test_data(**DEFAULT_CASE) as td:
        tiles = Tiles(td)
        other_eq = Tiles(td)
        other_neq = Tiles(td, [0])
        other_type = 0

        assert tiles == other_eq
        assert tiles != other_neq
        assert tiles != other_type


def test_repr() -> None:
    """Ensure calls of __repr__ produce the correct string representation."""
    with create_test_data(**DEFAULT_CASE) as td:
        tiles = Tiles(td)
        comparison_str = (
            f"Tiles(image={tiles.img} zooms={tiles.zooms} "
            f"pixels={tiles.pixels} resampling={Res(tiles.resampling).name})"
        )
        assert str(tiles) == comparison_str


def test_setattr() -> None:
    """Ensure calls of __setattr__ raise an AttributeError."""
    with create_test_data(**DEFAULT_CASE) as td:
        tiles = Tiles(td)
        with pytest.raises(AttributeError):
            tiles.pixels = 512
        with pytest.raises(AttributeError):
            tiles.new_attr = 512
