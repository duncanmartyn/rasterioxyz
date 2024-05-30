import warnings
from itertools import product
from pathlib import Path
from typing import Any, Generator, Sequence

from numpy import append, ndarray, uint8, where, zeros
from rasterio import (
    Affine,
    Band,
    DatasetReader,
    errors,
    open as ropen,
    transform,
    warp,
    windows,
)

from rasterioxyz._errors import TileWarning
from rasterioxyz._utils import _Bounds, _ImageProperties, _Tile, _Zoom


class Tiles:
    """
    Object for generating Pseudo-Mercator XYZ standard tiles from a Rasterio dataset
    corresponding to a georeferenced raster image.

    Parameters
    ----------
    image : rasterio.io.DatasetReader
        Georeferenced raster to tile.
    zooms : typing.Sequence[int], default = range(13)
        Sequence of integer zoom levels between 0 and 25 for which to generate tiles.
        These need not be sequential.
    pixels : int, default = 256
        Integer pixel height and width of generated tiles. Must be one of 256 or 512.
    resampling : str, default = "nearest"
        Resampling method recognised by Rasterio to use in tiling. See Rasterio
        documentation or the rasterio.enums module for the full list of supported
        techniques.

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
    >>> tiled.write(directory="out_directory", file_format="JPEG")

    Generate the sole zoom level 0 tile and inspect the result:

    >>> dataset = rasterio.open("georeferenced_image.tif")
    >>> tiled = rasterioxyz.Tiles(
            dataset,
            zooms=[0],
            pixels=512,
            resampling="bilinear",
        )
    >>> next(tiled.tiles)
    _Tile(
        zoom=0,
        column=0,
        row=0,
        bounds=_Bounds(
            minx=-20037508.342789244,
            miny=-20037508.342789244,
            maxx=20037508.342789244,
            maxy=20037508.342789244
        ),
        transform=Affine(
            78271.51696402048,
            0.0,
            -20037508.342789244,
            0.0,
            -78271.51696402048,
            20037508.342789244
        ),
        window=Window(
            col_off=-963146.7606931949,
            row_off=-1507618.2343921484,
            width=3575210.518075101,
            height=3575210.5167582342
        ),
        data=array(
            [[[0, 0, 0, ..., 0, 0, 0],
              [0, 0, 0, ..., 0, 0, 0],
              [0, 0, 0, ..., 0, 0, 0],
                        ...,
              [0, 0, 0, ..., 0, 0, 0],
              [0, 0, 0, ..., 0, 0, 0],
              [0, 0, 0, ..., 0, 0, 0]]],
              dtype=uint8
        )
    )
    """
    __slots__ = (
        "img",
        "zooms",
        "pixels",
        "resampling",
        "_img_dtype",
        "_img_is_3857",
        "_img_properties",
        "_tile_bands",
        "_img_max",
        "_img_min",
        "tiles",
    )
    _valid_resampling = {
        "nearest": 0,
        "bilinear": 1,
        "cubic": 2,
        "cubic_spline": 3,
        "lanczos": 4,
        "average": 5,
        "mode": 6,
        "gauss": 7,
        "max": 8,
        "min": 9,
        "med": 10,
        "q1": 11,
        "q3": 12,
        "sum": 13,
        "rms": 14,
    }
    _origin = 20037508.342789244

    def __init__(
            self,
            image: DatasetReader,
            zooms: Sequence[int] = range(13),
            pixels: int = 256,
            resampling: str = "nearest",
    ) -> None:
        if not isinstance(image, DatasetReader):
            raise TypeError(
                "image must be of type rasterio.DatasetReader, not "
                f"{type(image).__name__}.",
            )
        if image.crs is None:
            raise errors.CRSError("image must be a georeferenced dataset.")
        self.img = image

        if not isinstance(zooms, Sequence):
            raise TypeError(f"zooms must be a sequence, not {type(zooms).__name__}.")
        if not all(isinstance(zoom, int) for zoom in zooms):
            raise TypeError("all zoom values must be of type int.")
        if not all(zoom <= 25 and zoom >= 0 for zoom in zooms):
            raise ValueError("all zoom values must be between 0 and 25.")
        self.zooms = zooms

        if not isinstance(pixels, int):
            raise TypeError(f"pixels must be of type int, not {type(pixels).__name__}.")
        if pixels not in (256, 512):
            raise ValueError(f"pixels must be 256 or 512, not {pixels}.")
        self.pixels = pixels

        if not isinstance(resampling, str):
            raise TypeError(
                f"resampling must be of type str, not {type(resampling).__name__}.",
            )
        if resampling not in self._valid_resampling.keys():
            raise ValueError(
                f"resampling must be one of {list(self._valid_resampling.keys())}, not "
                f"{resampling}.",
            )
        self.resampling = self._valid_resampling.get(resampling, 0)

        self._img_is_3857 = self.img.crs == 3857
        if not self._img_is_3857:
            warnings.warn(
                f"source CRS is {self.img.crs}. Data will be reprojected to EPSG:3857.",
                TileWarning,
                stacklevel=2,
            )
        self._img_properties = self._get_mercator_properties()

        self._tile_bands = self.img.count if self.img.count <= 3 else 3

        self._img_dtype = self.img.dtypes[0]
        if self._img_dtype != "uint8":
            warnings.warn(
                f"source dtype is {self._img_dtype}. Data will be rescaled to uint8.",
                TileWarning,
                stacklevel=2,
            )
            self._img_max, self._img_min = self._get_image_statistics()

        self.tiles = self._tile()

    def __repr__(self) -> str:
        """Return a string representation of an instance of Tiles."""
        resampling_str = f"'{list(self._valid_resampling.keys())[self.resampling]}'"
        message = (
            f"Tiles(image={self.img} zooms={self.zooms} pixels={self.pixels} "
            f"resampling={resampling_str})"
        )
        return message

    def __eq__(self, other: Any) -> bool:
        """Test for equality between an instance of Tiles and another object."""
        if not isinstance(other, Tiles):
            return False

        dataset_eq = self.img.profile == other.img.profile
        zooms_eq = self.zooms == other.zooms
        pixels_eq = self.pixels == other.pixels
        resampling_eq = self.resampling == other.resampling

        if all([dataset_eq, zooms_eq, pixels_eq, resampling_eq]):
            return True
        else:
            return False

    def __setattr__(self, name: str, value: Any) -> None:
        """Override __setattr__ so attributes cannot be overwritten."""
        if hasattr(self, name):
            raise AttributeError(f'Attribute "{name}" is read only.')
        super().__setattr__(name, value)

    def _get_mercator_properties(self) -> _ImageProperties:
        """
        Get key Pseudo-Mercator properties (affine transformation and bounds) of the
        source rasterio dataset, returning an _ImageProperties object thereof.

        Returns
        -------
        properties : _ImageProperties
            _ImageProperties object corresponding to the source rasterio dataset.
        """
        if self._img_is_3857:
            properties = _ImageProperties(
                self.img.transform,
                _Bounds(*self.img.bounds),
            )
        else:
            transform, width, height = warp.calculate_default_transform(
                self.img.crs,
                3857,
                self.img.width,
                self.img.height,
                *self.img.bounds,
            )
            minx = transform[2]
            maxx = minx + transform[0] * width
            maxy = transform[5]
            miny = maxy + transform[4] * height
            properties = _ImageProperties(
                transform,
                _Bounds(minx, miny, maxx, maxy),
            )
        return properties

    def _get_image_statistics(self) -> tuple[int | float, int | float]:
        """
        Retrieve the minimum and maximum values across the source dataset's bands-to-tile
        for use in dtype rescaling/casting.

        Returns
        -------
        img_max : int | float
            Maximum value across all bands of the source dataset.
        img_min : int | float
            Minimum value across all bands of the source dataset.
        """
        band_statistics = [
            self.img.statistics(band) for band in range(1, self._tile_bands + 1)
        ]
        img_max = max([stats.max for stats in band_statistics])
        img_min = min([stats.min for stats in band_statistics])
        return img_max, img_min

    def _tile(self) -> Generator[_Tile, None, None]:
        """
        Generate _Tile objects for the instance's rasterio dataset and zooms.

        Yields
        ------
        tile : _Tile
            _Tile object corresponding to a single XYZ tile.
        """
        for zoom in self.zooms:
            zoom_properties = self._build_zoom(zoom)
            for col, row in zoom_properties.tile_indices:
                tile = self._build_tile(zoom, col, row, zoom_properties.tile_dims)

                yield tile

    def _build_zoom(self, zoom: int) -> _Zoom:
        """
        Generate a _Zoom object corresponding to a single XYZ zoom level.

        Parameters
        ----------
        zoom : int
            Zoom level for which to generate a _Zoom object.

        Returns
        -------
        tile : _Tile
            _Zoom object corresponding to a single XYZ zoom level.
        """
        zoom_ntiles = 4 ** zoom
        zoom_dims = zoom_ntiles ** .5
        tile_dims = (self._origin * 2) / zoom_dims
        tile_res = tile_dims / self.pixels
        if tile_res < self._img_properties.transform[0]:
            warnings.warn(
                f"tile resolution is higher than source at zoom level {zoom}. "
                "Consider reducing maximum zoom level for better performance.",
                TileWarning,
                stacklevel=3,
            )
        start_col = int((self._img_properties.bounds.minx - -self._origin) // tile_dims)
        end_col = int((self._img_properties.bounds.maxx - -self._origin) // tile_dims)
        start_row = int(
            abs(self._img_properties.bounds.maxy - self._origin) // tile_dims,
        )
        end_row = int(
            abs(self._img_properties.bounds.miny - self._origin) // tile_dims,
        )
        tile_indices = product(
            range(start_col, end_col + 1),
            range(start_row, end_row + 1),
        )
        zoom_properties = _Zoom(zoom, tile_dims, tile_indices)
        return zoom_properties

    def _build_tile(self, zoom: int, col: int, row: int, dims: int | float) -> _Tile:
        """
        Generate a _Tile object corresponding to a single XYZ tile.

        Parameters
        ----------
        zoom : int
            Tile to generate's zoom level.
        col : int
            Tile to generate's column.
        row : int
            Tile to generate's row.
        dims : int | float
            Tile to generate's height/width in metres.

        Returns
        -------
        tile : _Tile
            _Tile object corresponding to a single XYZ tile.
        """
        minx = self._origin * -1 + col * dims
        maxx = minx + dims
        maxy = self._origin - row * dims
        miny = maxy - dims
        bounds = _Bounds(minx, miny, maxx, maxy)
        affine = transform.from_bounds(*bounds, self.pixels, self.pixels)
        window = windows.from_bounds(*bounds, self._img_properties.transform)
        if self._img_is_3857:
            tile_data = self._read_tile_data(window)
        else:
            tile_data = self._reproject_tile_data(window, affine)
        if tile_data.dtype != uint8:
            tile_data = self._array_to_uint8(tile_data)
        tile = _Tile(
            zoom=zoom,
            column=col,
            row=row,
            bounds=bounds,
            transform=affine,
            window=window,
            data=tile_data,
        )
        return tile

    def _reproject_tile_data(
            self,
            tile_window: windows.Window,
            tile_transform: Affine
    ) -> ndarray:
        """
        Read, reproject, and resample source image data within a tile's window.

        Parameters
        ----------
        tile : _Tile
            Tile object for which data will be read.

        Returns
        -------
        tile_array : numpy.ndarray
            Data within the tile's window.
        """
        tile_array = warp.reproject(
            source=Band(
                self.img,
                range(1, self._tile_bands + 1),
                dtype=self._img_dtype,
                shape=(tile_window.height, tile_window.width),
            ),
            destination=zeros(
                (self._tile_bands + 1, self.pixels, self.pixels),
                dtype=self._img_dtype,
            ),
            src_transform=self.img.transform,
            src_crs=self.img.crs,
            dst_transform=tile_transform,
            dst_crs=3857,
            dst_alpha=self._tile_bands + 1,
            resampling=self.resampling,
        )[0]
        return tile_array

    def _read_tile_data(self, tile_window: windows.Window) -> ndarray:
        """
        Read, resample, and add an alpha channel to source image data within a tile's
        window

        Parameters
        ----------
        tile : _Tile
            Tile object for which data will be read.

        Returns
        -------
        tile_array : numpy.ndarray
            Data within the tile's window.
        """
        tile_array = self.img.read(
            out_shape=(self._tile_bands, self.pixels, self.pixels),
            window=tile_window,
            masked=True,
            boundless=True,
            resampling=self.resampling,
        )
        tile_alpha = where(
            tile_array[0].mask, 0, 255
        ).reshape((1, self.pixels, self.pixels)).astype(self._img_dtype)
        tile_array = append(tile_array, tile_alpha, axis=0)
        return tile_array

    def _array_to_uint8(self, tile_array: ndarray) -> ndarray:
        """
        Rescale values of all but the last channel (assumed to be alpha) of a 3D array
        to between 0 and 255 and cast to uint8.

        Parameters
        ----------
        array : numpy.ndarray
            Array to rescale and cast to uint8.

        Returns
        -------
        rescaled_array : numpy.ndarray
            Rescaled uint8 array.
        """
        tile_array[:-1] = (
            (tile_array[:-1] - self._img_min) / (self._img_max - self._img_min)
        ) * (255 - 0) + 0
        tile_array = tile_array.astype(uint8)
        return tile_array

    def write(self, directory: str | Path, driver: str = "PNG") -> None:
        """
        Write tile images to a local directory in a given format.

        Parameters
        ----------
        directory : str
            Existing local directory in which zoom and column folders will be created
            and images will be written.
        driver : str, default = "PNG"
            Image format to write data in. Must be one of "PNG" or "JPEG".
        """
        warnings.filterwarnings("ignore", category=errors.NotGeoreferencedWarning)

        if not isinstance(driver, (str, Path)):
            raise TypeError(f"driver must be str or Path, not {type(driver)}.")
        if driver.upper() not in ["PNG", "JPEG"]:
            raise ValueError(f"driver must be PNG or JPEG, not {driver}.")

        out_dir = Path(directory) if not isinstance(directory, Path) else directory
        if not out_dir.exists() or not out_dir.is_dir():
            raise FileNotFoundError(f"directory does not exist: {directory}")

        for tile in self.tiles:
            img_dir = out_dir.joinpath(str(tile.zoom), str(tile.column))
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir.joinpath(f"{tile.row}.{driver}")

            # if alpha indicates total transparency, skip write
            if tile.data[-1].mean() == 0:
                continue

            with ropen(
                img_path,
                "w",
                driver=driver,
                width=self.pixels,
                height=self.pixels,
                count=tile.data.shape[0],
                dtype=uint8,
            ) as dst:
                dst.write(tile.data)
