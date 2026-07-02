"""Decode CARTO point geometry (hex EWKB strings, SRID 4326) into lon/lat.

Point EWKB layout: 1 byte endianness + 4 bytes type|SRID flag + 4 bytes SRID +
8 bytes x + 8 bytes y = 25 bytes = 50 hex chars. Anything that doesn't match
the little-endian SRID-4326 point prefix is left null with status `invalid`.
"""

from __future__ import annotations

import polars as pl

EWKB_POINT_4326_PREFIX = "0101000020E6100000"


def with_point_lonlat(lf: pl.LazyFrame, column: str = "the_geom") -> pl.LazyFrame:
    hexstr = pl.col(column).cast(pl.String)
    valid = hexstr.str.starts_with(EWKB_POINT_4326_PREFIX) & (hexstr.str.len_chars() == 50)

    def coord(offset: int) -> pl.Expr:
        return (
            pl.when(valid)
            .then(hexstr.str.slice(offset, 16))
            .otherwise(None)
            .str.decode("hex", strict=False)
            .bin.reinterpret(dtype=pl.Float64, endianness="little")
        )

    status = (
        pl.when(hexstr.is_null())
        .then(pl.lit("missing"))
        .when(~valid)
        .then(pl.lit("invalid"))
        .otherwise(pl.lit("ok"))
    )
    return lf.with_columns(
        coord(18).alias("lon"), coord(34).alias("lat"), status.alias("lonlat_status")
    )
