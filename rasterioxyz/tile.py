"""Raster tiling functionality."""

import logging
import warnings
from collections.abc import Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import partial
from http.server import HTTPServer
from itertools import chain, product
from pathlib import Path
from typing import Any, Literal

import numpy as np
import rasterio as rio
from rasterio import enums, errors, transform, warp, windows

from rasterioxyz._errors import TileWarning
from rasterioxyz._serve import _TileRequestHandler


class Tiles:
    """Generate XYZ tiles from `rasterio.DatasetReader` objects."""

    __slots__ = (
        "_bands",
        "_dtype",
        "_max",
        "_mercator",
        "_min",
        "_tile_dims",
        "allow_upsample",
        "img",
        "pixels",
        "resampling",
        "tiles",
        "zooms",
    )
    _origin = 20037508.342789244
    _cwd = Path.cwd()
    _pm_epsg = 3857
    _merc_x = 20037508.34
    _merc_y = 20048966.1

    def __init__(
        self,
        image: rio.DatasetReader,
        zooms: Sequence[int] = range(13),
        pixels: int = 256,
        resampling: enums.Resampling = enums.Resampling.nearest,
        *,
        allow_upsample: bool = True,
    ) -> None:
        """Generate XYZ tiles from `rasterio.DatasetReader` objects.

        Parameters
        ----------
        image : rasterio.io.DatasetReader
            Georeferenced raster to tile.
        zooms : typing.Sequence[int], default = range(13)
            Sequence of integer zoom levels between 0 and 25 for which to
            generate tiles. These need not be sequential.
        pixels : int, default = 256
            Integer pixel height and width of generated tiles. Must be 256 or
            512.
        resampling : rasterio.enums.Resampling, default = Resampling.nearest
            Resampling method recognised by `rasterio` to use in tiling. See
            `rasterio.enums.Resampling` for all supported values.
        allow_upsample : bool, default = True
            Whether or not to automatically skip generation of tiles for zoom
            levels wherein spatial resolution exceeds that of source data.
            Default `True` does not skip.

        Examples
        --------
        Generate and write tiles to local storage:

        >>> dataset = rasterio.open("georeferenced_image.tif")
        >>> tiled = rasterioxyz.Tiles(
                dataset,
                zooms=[0, 5, 10],
                pixels=512,
                resampling="bilinear",
            )
        >>> tiled.write()

        Serve dynamically generated tiles over HTTP:

        >>> dataset = rasterio.open("georeferenced_image.tif")
        >>> tiled = rasterioxyz.Tiles(dataset)
        >>> tiled.serve()

        Generate the sole zoom level 0 tile and inspect the result:

        >>> dataset = rasterio.open("georeferenced_image.tif")
        >>> tiled = rasterioxyz.Tiles(dataset, zooms=[0])
        >>> next(tiled.tiles)

        """
        self._validate_type("image", image, rio.DatasetReader)
        if image.crs is None:
            msg = "image must be georeferenced."
            raise errors.CRSError(msg)
        self.img = image

        self._validate_type("zooms", zooms, Sequence)
        valid_zooms = list(range(26))
        for zoom in zooms:
            self._validate_type("zoom values", zoom, int)
            self._validate_value("zoom values", zoom, valid_zooms)
        self.zooms = zooms
        self._tile_dims = self._get_zoom_tile_dims()

        self._validate_type("pixels", pixels, int)
        self._validate_value("pixels", pixels, [256, 512])
        self.pixels = pixels

        self._validate_type("resampling", resampling, enums.Resampling)
        self.resampling = resampling.value

        self.allow_upsample = allow_upsample
        self._mercator = self._get_mercator_properties()
        self._bands = min(self.img.count, 3)

        self._dtype = self.img.dtypes[0]
        if self._dtype != "uint8":
            msg = (
                f"Source dtype is {self._dtype}. Cast to uint8 for better "
                "performance."
            )
            self._raise_warning(msg, 2)
            self._min, self._max = self._get_minmax()

        self.tiles = self._tile()

    def __repr__(self) -> str:
        """Return a string representation describing key attributes."""
        return (
            f"Tiles(image={self.img} zooms={self.zooms} pixels={self.pixels} "
            f"resampling={enums.Resampling(self.resampling).name})"
        )

    def __eq__(self, other: object) -> bool:
        """Test for equality using key distinguishing attributes."""
        if not isinstance(other, Tiles):
            return False
        ds_eq = self.img.name == other.img.name
        meta_eq = self.img.profile == other.img.profile
        zoom_eq = self.zooms == other.zooms
        pix_eq = self.pixels == other.pixels
        resamp_eq = self.resampling == other.resampling
        return all([ds_eq, meta_eq, zoom_eq, pix_eq, resamp_eq])

    def __setattr__(self, name: str, value: object) -> None:
        """Override __setattr__ so attributes cannot be overwritten."""
        if hasattr(self, name):
            msg = f"Attribute '{name}' is read only."
            raise AttributeError(msg)
        super().__setattr__(name, value)

    def write(
        self,
        path: str | Path = _cwd,
        driver: Literal["PNG", "JPEG"] = "PNG",
        threads: int | None = None,
    ) -> None:
        """Write tile images to a local directory in a given format.

        Parameters
        ----------
        path : str, default = pathlib.Path.cwd()
            Existing local directory in which zoom and column folders will be
            created and tile images written. Default is the current working
            directory.
        driver : str, default = "PNG"
            Image format to write data in. Must be one of "PNG" or "JPEG".
        threads : int | None, default = None
            Maximum number of threads used to write tile images. Default None
            uses all available.

        Raises
        ------
        FileNotFoundError
            If the passed directory does not exist.

        """
        self._filter_georeference_warnings()
        self._validate_type("driver", driver, str)
        self._validate_value("driver", driver, ["PNG", "JPEG"])

        out_dir = Path(path) if not isinstance(path, Path) else path
        if not out_dir.exists() or not out_dir.is_dir():
            msg = f"directory does not exist: {path}"
            raise FileNotFoundError(msg)

        def _write(tile: dict[str, int | np.ndarray | bool]) -> None:
            """Nested convenience function for writing tiles to disk."""
            img_dir = out_dir / str(tile["zoom"]) / str(tile["column"])
            img_dir.mkdir(parents=True, exist_ok=True)
            with Path.open(img_dir / f"{tile['row']}.{driver}", "wb") as dst:
                dst.write(self._get_tile_bytes(tile, driver))

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [
                executor.submit(_write, tile)
                for tile in self.tiles
                if not tile["is_empty"]
            ]
            for future in futures:
                future.result()

    def serve(
        self,
        port: int = 8080,
        driver: Literal["PNG", "JPEG"] = "PNG",
        cache_age: int = 300,
        *,
        quiet: bool = False,
    ) -> None:
        """Serve tile images via HTTP.

        Parameters
        ----------
        port : int, default = 8080
            TCP port on which to serve tile images.
        driver : str, default = "PNG"
            Format in which to serve tile images.
        cache_age : int, default = 300
            Time in seconds to cache served tile images after request creation.
            Applications like QGIS cache tiles regardless of this setting.
        quiet : bool, default = False
            Whether or not to silence server logs beyond the startup message.

        """
        self._filter_georeference_warnings()
        self._validate_type("driver", driver, str)
        self._validate_value("driver", driver, ["PNG", "JPEG"])
        logger = self._create_logger()
        driver = driver.lower()  # type:ignore[assignment]
        request_handler = partial(
            _TileRequestHandler,
            data=self,
            driver=driver,
            cache_age=cache_age,
            start=datetime.now(UTC),
        )
        template_url = f"http://localhost:{port}/{{z}}/{{x}}/{{y}}.{driver}"
        logger.info("Starting HTTP server: url=%s", template_url)
        if quiet:
            logger.setLevel(51)
        server = HTTPServer(("", port), request_handler)
        server.serve_forever()

    @staticmethod
    def _validate_type(name: str, obj: object, tp: type) -> None:
        """Check an object is of given type."""
        if not isinstance(obj, tp):
            msg = f"{name} must be {tp.__name__}, not {type(obj).__name__}."
            raise TypeError(msg)

    @staticmethod
    def _validate_value(name: str, obj: object, valid: Sequence) -> None:
        """Check an object is one of given values."""
        if obj not in valid:
            msg = f"{name} must be in {valid}, not {obj}."
            raise ValueError(msg)

    @staticmethod
    def _raise_warning(message: str, level: int) -> None:
        """Raise a `TileWarning` at a given stack level."""
        warnings.warn(message, TileWarning, level)

    @staticmethod
    def _create_logger() -> logging.Logger:
        """Create the `Tiles` object logger."""
        logger = logging.getLogger("rasterioxyz")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        fmt = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        return logger

    @staticmethod
    def _filter_georeference_warnings() -> None:
        """Filter warnings for non-georeferenced data (tiles)."""
        warnings.filterwarnings(
            "ignore",
            category=errors.NotGeoreferencedWarning,
        )

    def _get_zoom_tile_dims(self) -> dict[int, float]:
        """Get tile dimensions for each zoom level."""
        return {
            zoom: (self._origin * 2) / 4 ** (zoom / 2) for zoom in self.zooms
        }

    def _get_mercator_properties(self) -> dict[str, rio.Affine | list[float]]:
        """Get Pseudo-Mercator (EPSG:3857) properties."""
        if self.img.crs == self._pm_epsg:
            tf = self.img.transform
            bounds = self.img.bounds
        else:
            msg = (
                f"Source CRS is {self.img.crs}. Reproject to EPSG:3857 for "
                "better performance."
            )
            self._raise_warning(msg, 4)
            minx, miny, maxx, maxy = warp.transform_bounds(
                self.img.crs,
                self._pm_epsg,
                *self.img.bounds,
            )
            minx = max(minx, -self._merc_x)
            miny = max(miny, -self._merc_y)
            maxx = min(maxx, self._merc_x)
            maxy = min(maxy, self._merc_y)
            clipped_src_bds = warp.transform_bounds(
                self._pm_epsg,
                self.img.crs,
                *[minx, miny, maxx, maxy],
            )
            wdw = windows.from_bounds(*clipped_src_bds, self.img.transform)
            tf, width, height = warp.calculate_default_transform(
                self.img.crs,
                self._pm_epsg,
                wdw.width,
                wdw.height,
                *clipped_src_bds,
            )
            minx = tf[2]
            maxx = minx + tf[0] * width
            maxy = tf[5]
            miny = maxy + tf[4] * height
            bounds = [minx, miny, maxx, maxy]
        return {"transform": tf, "bounds": bounds}

    def _get_minmax(self) -> tuple[int | float, int | float]:
        """Get the minimum and maximum values across all bands."""
        band_stats = [
            self.img.stats(indexes=band)[0]
            for band in range(1, self._bands + 1)
        ]
        band_minmax = [(stats.min, stats.max) for stats in band_stats]
        return min(chain(*band_minmax)), max(chain(*band_minmax))

    def _tile(self) -> Generator[dict[str, Any]]:
        """Lazily tile data."""
        for zoom in self.zooms:
            if zoom_tiles := self._build_zoom(zoom):
                for col, row in zoom_tiles:
                    yield self._build_tile(zoom, col, row)

    def _build_zoom(self, zoom: int) -> product | None:
        """Retrieve all column-row conbinations for a given zoom."""
        tile_dims = self._tile_dims[zoom]
        tile_res = tile_dims / self.pixels
        if tile_res < self._mercator["transform"][0]:
            msg = f"Tile resolution is higher than source at zoom {zoom}"
            if not self.allow_upsample:
                msg += " and upsampling is disabled, skipping."
                self._raise_warning(msg, 4)
                return None
            msg += (
                ". Reduce maximum zoom or disable upsampling for better "
                "performance."
            )
            self._raise_warning(msg, 4)
        start_col = int(
            (self._mercator["bounds"][0] - -self._origin) // tile_dims,
        )
        end_col = int(
            (self._mercator["bounds"][2] - -self._origin) // tile_dims,
        )
        start_row = int(
            abs(self._mercator["bounds"][3] - self._origin) // tile_dims,
        )
        end_row = int(
            abs(self._mercator["bounds"][1] - self._origin) // tile_dims,
        )
        return product(
            range(start_col, end_col + 1),
            range(start_row, end_row + 1),
        )

    def _build_tile(
        self,
        zoom: int,
        col: int,
        row: int,
    ) -> dict[str, int | np.ndarray | bool]:
        """Get properties of a single tile."""
        tile_dims = self._tile_dims[zoom]
        minx = self._origin * -1 + col * tile_dims
        maxx = minx + tile_dims
        maxy = self._origin - row * tile_dims
        miny = maxy - tile_dims
        bounds = [minx, miny, maxx, maxy]
        affine = transform.from_bounds(*bounds, self.pixels, self.pixels)
        window = windows.from_bounds(*bounds, self._mercator["transform"])
        if self.img.crs == self._pm_epsg:
            tile_data = self._read(window)
        else:
            tile_data = self._reproject(window, affine)
        if tile_data.dtype != np.uint8:
            tile_data = self._to_uint8(tile_data)
        return {
            "zoom": zoom,
            "column": col,
            "row": row,
            "data": tile_data,
            "is_empty": tile_data[-1].mean() == 0,
        }

    def _reproject(
        self,
        tile_window: windows.Window,
        tile_transform: rio.Affine,
    ) -> np.ndarray:
        """Read and reproject data for a single tile."""
        return warp.reproject(
            source=rio.Band(
                self.img,
                range(1, self._bands + 1),
                dtype=self._dtype,
                shape=(tile_window.height, tile_window.width),
            ),
            destination=np.zeros(
                (self._bands + 1, self.pixels, self.pixels),
                dtype=self._dtype,
            ),
            src_transform=self.img.transform,
            src_crs=self.img.crs,
            dst_transform=tile_transform,
            dst_crs=self._pm_epsg,
            dst_alpha=self._bands + 1,
            resampling=self.resampling,
        )[0]

    def _read(self, tile_window: windows.Window) -> np.ndarray:
        """Read data for a single tile."""
        tile_array = self.img.read(
            out_shape=(self._bands, self.pixels, self.pixels),
            window=tile_window,
            masked=True,
            boundless=True,
            resampling=enums.Resampling(self.resampling),
        )
        tile_alpha = (
            np.where(tile_array[0].mask, 0, 255)
            .reshape((1, self.pixels, self.pixels))
            .astype(self._dtype)
        )
        return np.append(tile_array, tile_alpha, axis=0)

    def _to_uint8(self, tile_array: np.ndarray) -> np.ndarray:
        """Cast data for a single tile to uint8."""
        tile_array[:-1] = (
            (tile_array[:-1] - self._min) / (self._max - self._min)
        ) * (255 - 0) + 0
        return tile_array.astype(np.uint8)

    def _get_tile_bytes(
        self,
        tile: dict[str, int | np.ndarray | bool],
        driver: str,
    ) -> bytes:
        """Return a single tile's data as bytes."""
        array_data: np.ndarray = tile["data"]
        with rio.MemoryFile() as memfile:
            with memfile.open(
                driver,
                width=self.pixels,
                height=self.pixels,
                count=array_data.shape[0],
                dtype=np.uint8,
            ) as ds:
                ds.write(tile["data"])
            memfile.seek(0)
            return memfile.read()
