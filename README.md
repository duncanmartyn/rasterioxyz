![pypi version](https://img.shields.io/pypi/v/rasterioxyz)
![pypi downloads](https://img.shields.io/pypi/dm/rasterioxyz)
[![publish](https://github.com/duncanmartyn/rasterioxyz/actions/workflows/publish.yaml/badge.svg?branch=main)](https://github.com/duncanmartyn/rasterioxyz/actions/workflows/publish.yaml)
[![ci](https://github.com/duncanmartyn/rasterioxyz/actions/workflows/test.yaml/badge.svg?branch=main)](https://github.com/duncanmartyn/rasterioxyz/actions/workflows/ci.yaml)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

- [RasterioXYZ](#rasterioxyz)
- [Design](#design)
    - [Memory efficiency](#memory-efficiency)
    - [Flexibility](#flexibility)
- [Examples](#examples)
- [Roadmap](#roadmap)
- [Contributions](#contributions)

# RasterioXYZ

RasterioXYZ is a lightweight package for tiling georeferenced `rasterio.DatasetReader` objects according to the XYZ tiles standard written in and depending on the following:
- `python ^3.13`
- `rasterio ^1.4.3`

For greater functionality in navigating the tile-tree, see [`Mercantile`](https://github.com/mapbox/mercantile).

# Design

### Memory efficiency

While faster tiling may be achieved by reprojecting and/or resampling the entire source image to the required CRS and maximum resolution, respectively, such an approach precludes tiling larger-than-memory rasters or those with the potential to be so (i.e. with resampling). By lazily reading and, if needed, resampling, reprojecting, and dtype casting windows of the source dataset for each tile, memory use is kept low.

### Flexibility

Some basic design decisions for flexibility:

- Imagery of all data types and PROJ-recognised projections can be tiled with no alterations made to the original dataset prior to tiling.
- Tiles need not be generated for all zoom levels in a range - simply pass a sequence of integer zoom levels between 0 and 25 in any order.
- Tiles can be saved in PNG or JPEG format, though the XYZ standard dictates the former (also lossless and appears to produce better colour balancing).
- Use of any resampling technique through `rasterio.enums.Resampling`.
- Creation of standard (256 px) or high (512 px) resolution tiles.
- Ability to skip tiling at zoom levels requiring resolution upsampling.

# Examples

```python
import rasterio
import rasterioxyz

img = rasterio.open("georeferenced_image.tif")
tiles = rasterioxyz.Tiles(
  image=img,
  zooms=range(26),
  pixels=512,
  resampling=rasterio.enums.Resampling.bilinear,
  allow_upsample=False,
)
tiles.write()
# OR
tiles.serve()
```

Several pre-emptive measures can be taken to improve the speed of tiling:

- Project source data in EPSG:3857
- Cast and scale source data to uint8
- Use the default value of 256 for `pixels`
- Use the default value of `rasterio.enums.Resampling.nearest` for `resampling`
- Set `allow_upsample` to `False`

Previously, tiles had to be written to disk before testing in desktop GIS platforms. With `v0.1.1`, tiles can be dynamically generated and served. Simply create a `Tiles` object with your data, call `.serve()`, then add the logged URL as an XYZ source or format it with a zoom, column, and row and request tiles through a browser. This is useful in testing and evaluating results prior to incurring cloud storage I/O costs. Software like QGIS cache tiled data and may ignore HTTP headers like If-Modified-Since. When tiling different datasets in quick succession, clearing the cache prevents tiles from previous datasets appearing in requests for newly tiled data. Alternatively, serve on a different port for each dataset.

Also added in `v0.1.1` was the RasterioXYZ CLI. Once installed, enter `rasterioxyz -h` in a terminal to check it out.

# Roadmap

Check the [repository issues](https://github.com/duncanmartyn/rasterioxyz/issues) for possible future additions.

See the [project changelog](CHANGELOG.md) for fixes and improvements.

# Contributions

Feel free to raise any issues, especially bugs and feature requests!
