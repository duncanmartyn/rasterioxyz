import shutil
from pathlib import Path
from typing import Generator

import pytest
from rasterio.errors import CRSError

from .conftest import TEST_OUTPUT_DIR
from rasterioxyz.tile import Tiles


class TestTiles:
    @pytest.mark.parametrize(
        "test_data, zooms, pixels, resampling, error",
        [
            ({"crs": 3857, "dtype": "uint8"}, [0, 5, 10], 256, "nearest", None),
            ({"crs": None, "dtype": None}, [5], 256, "nearest", TypeError),
            ({"crs": 3857, "dtype": "uint8"}, 0, 256, "nearest", TypeError),
            ({"crs": 3857, "dtype": "uint8"}, ["0"], 256, "nearest", TypeError),
            ({"crs": 3857, "dtype": "uint8"}, [50], 256, "nearest", ValueError),
            ({"crs": 3857, "dtype": "uint8"}, [5], "256", "nearest", TypeError),
            ({"crs": 3857, "dtype": "uint8"}, [5], 1000, "nearest", ValueError),
            ({"crs": 3857, "dtype": "uint8"}, [5], 256, ["nearest"], TypeError),
            ({"crs": 3857, "dtype": "uint8"}, [5], 256, "any", ValueError),
            ({"crs": None, "dtype": "uint8"}, [5], 256, "nearest", CRSError),
            ({"crs": 32630, "dtype": "uint8"}, [5], 256, "nearest", None)
        ],
        indirect=["test_data"],
    )
    def test_constructor(self, test_data, zooms, pixels, resampling, error) -> None:
        if error:
            with pytest.raises(error):
                Tiles(test_data, zooms, pixels, resampling)
        else:
            tiles = Tiles(test_data, zooms, pixels, resampling)
            assert isinstance(tiles.tiles, Generator)  # nosec

    @pytest.mark.parametrize(
        "test_data, zooms, driver, error",
        [
            ({"crs": 3857, "dtype": "float32"}, [0, 10], "PNG", None),
            ({"crs": 4326, "dtype": "uint8"}, [0, 5], "PNG", None),
            ({"crs": 3857, "dtype": "uint8"}, [5], 0, TypeError),
            ({"crs": 3857, "dtype": "uint8"}, [5], "TIF", ValueError),
            ({"crs": 3857, "dtype": "uint8"}, [5], "PNG", FileNotFoundError),
        ],
        indirect=["test_data"],
    )
    def test_write(self, test_data, zooms, driver, error) -> None:
        tiles = Tiles(test_data, zooms)
        test_tiles_dir = TEST_OUTPUT_DIR.joinpath(Path(test_data.name).stem)

        if error and not test_tiles_dir.exists():
            with pytest.raises(error):
                tiles.write(test_tiles_dir, driver)
        else:
            test_tiles_dir.mkdir(exist_ok=True)
            tiles.write(test_tiles_dir, driver)

            zoom_dirs = [int(zoom_dir.stem) for zoom_dir in test_tiles_dir.glob("*")]
            # dir for each zoom level exists
            assert [zoom_dir for zoom_dir in zoom_dirs if zoom_dir in zooms]  # nosec
            # dirs for columns exist
            col_dirs = list(test_tiles_dir.glob("*/*"))
            assert col_dirs  # nosec
            # tile PNGs exist
            tile_image_paths = list(test_tiles_dir.glob("**/*.PNG"))
            assert tile_image_paths  # nosec
            # tile PNGs have correct dimensions
            assert all(
                self.get_png_dimensions(image_path) == (tiles.pixels, tiles.pixels)
                for image_path in tile_image_paths
            )  # nosec
            shutil.rmtree(test_tiles_dir, ignore_errors=True)

    @pytest.mark.parametrize(
        "test_data",
        ({"crs": 3857, "dtype": "uint8"},),
        indirect=["test_data"],
    )
    def test_eq(self, test_data) -> None:
        tiles = Tiles(test_data)
        other_eq = Tiles(test_data)
        other_neq = Tiles(test_data, [0])
        other_type = 0

        assert tiles == other_eq  # nosec
        assert tiles != other_neq  # nosec
        assert tiles != other_type  # nosec

    @pytest.mark.parametrize(
        "test_data",
        ({"crs": 3857, "dtype": "uint8"},),
        indirect=["test_data"],
    )
    def test_repr(self, test_data) -> None:
        tiles = Tiles(test_data)
        resampling_str: str = (
            f"'{list(tiles._valid_resampling.keys())[tiles.resampling]}'"
        )
        comparison_str = (
            f"Tiles(image={tiles.img} zooms={tiles.zooms} pixels={tiles.pixels} "
            f"resampling={resampling_str})"
        )
        assert str(tiles) == comparison_str  # nosec

    @pytest.mark.parametrize(
        "test_data",
        ({"crs": 3857, "dtype": "uint8"},),
        indirect=["test_data"],
    )
    def test_setattr(self, test_data) -> None:
        tiles = Tiles(test_data)
        with pytest.raises(AttributeError):
            tiles.pixels = 512
        with pytest.raises(AttributeError):
            tiles.new_attr = 512

    @staticmethod
    def get_png_dimensions(file_path) -> tuple[int, int]:
        with open(file_path, 'rb') as src:
            src.read(8)
            ihdr = src.read(25)
            width = int.from_bytes(ihdr[8:12], "big")
            height = int.from_bytes(ihdr[12:16], "big")
            return width, height
