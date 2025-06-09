from argparse import (
    ArgumentParser,
    RawDescriptionHelpFormatter,
    _SubParsersAction,
)
from pathlib import Path

import rasterio
from rasterio.enums import Resampling

from rasterioxyz.tile import Tiles

DESCRIPTION = """
 _____         _           _     __ __ __ __ _____
| __  |___ ___| |_ ___ ___|_|___|  |  |  |  |__   |
|    -| .'|_ -|  _| -_|  _| | . |-   -|_   _|   __|
|__|__|__,|___|_| |___|_| |_|___|__|__| |_| |_____|

RasterioXYZ CLI for generating, writing, and serving XYZ tiles.
"""


def main() -> None:
    """Create and run the `rasterioxyz` CLI."""
    parser = ArgumentParser(
        description=DESCRIPTION,
        formatter_class=RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    _create_write_parser(subparsers)
    _create_serve_parser(subparsers)
    args = parser.parse_args()
    if args.min > args.max:
        msg = (
            f"Min zoom cannot be greater than max: min={args.min}, "
            f"max={args.max}"
        )
        raise ValueError(msg)
    tiles = Tiles(
        rasterio.open(args.src),
        range(args.min, args.max + 1),
        args.pixels,
        Resampling[args.resample],
        allow_upsample=args.no_upsample,
    )
    if args.cmd == "write":
        tiles.write(args.dst, args.driver, args.threads)
    elif args.cmd == "serve":
        tiles.serve(args.port, args.driver, args.cache, quiet=args.quiet)


def _create_write_parser(subparser: _SubParsersAction) -> None:
    """Add write-specific parser and arguments to the CLI."""
    parser = subparser.add_parser(
        "write",
        help="Generate and write tile images to a local directory.",
    )
    _create_common_arguments(parser)
    parser.add_argument(
        "--dst",
        default=Path.cwd(),
        type=Path,
        help=(
            "Directory in which to write generated tile images. Defaults to "
            "the current working directory."
        ),
    )
    parser.add_argument(
        "--threads",
        default=None,
        type=int,
        help=(
            "Maximum number of threads used to write tile images. Defaults "
            "to all available."
        ),
    )


def _create_serve_parser(subparser: _SubParsersAction) -> None:
    """Add serve-specific parser and arguments to the CLI."""
    parser = subparser.add_parser(
        "serve",
        help="Dynamically generate and serve tile images via HTTP.",
    )
    _create_common_arguments(parser)
    parser.add_argument(
        "--port",
        default=8080,
        type=int,
        help="Port on which to serve tile images. Defaults to 8080.",
    )
    parser.add_argument(
        "--cache",
        default=300,
        type=int,
        help=(
            "Time in seconds to cache served tile images after request. "
            "Defaults to 300."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence server logs. Defaults to False.",
    )


def _create_common_arguments(parser: ArgumentParser) -> None:
    """Add common arguments to a given command's parser."""
    parser.add_argument(
        "src",
        type=Path,
        help=(
            "Path to the georeferenced raster for which to generate and write "
            "tiles."
        ),
    )
    parser.add_argument(
        "--min",
        default=0,
        type=int,
        choices=list(range(26)),
        help=(
            "Minimum zoom level for which to generate tile images. Defaults "
            "to 0."
        ),
    )
    parser.add_argument(
        "--max",
        default=12,
        type=int,
        choices=list(range(26)),
        help=(
            "Maximum zoom level for which to generate tile images. Defaults "
            "to 12."
        ),
    )
    parser.add_argument(
        "--pixels",
        default=256,
        type=int,
        choices=[256, 512],
        help=(
            "Integer pixel height and width of generated tile images. "
            "Defaults to 256."
        ),
    )
    parser.add_argument(
        "--resample",
        default="nearest",
        help=(
            "Resampling method to use in tiling. Defaults to nearest "
            "neighbour."
        ),
        choices=Resampling._member_names_,
    )
    parser.add_argument(
        "--no-upsample",
        action="store_false",
        default=True,
        help=(
            "Skip generation of tiles for zoom levels wherein spatial "
            "resolution exceeds that of source data."
        ),
    )
    parser.add_argument(
        "--driver",
        default="PNG",
        type=str,
        choices=["PNG", "JPEG"],
        help="Format in which to write or serve tile images. Defaults to PNG.",
    )


if __name__ == "__main__":
    main()
