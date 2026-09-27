"""Stand-in for a geocoding service: New York ZIP code -> coordinates.

Only the ZIP codes used in the sample data are known. Replace with a real
geocoding call when you have an API key.
"""

ZIPS = {
    "10001": (40.7549, -73.9844),
    "10004": (40.7075, -74.0113),
    "10011": (40.7465, -74.0014),
    "10024": (40.7870, -73.9754),
    "10027": (40.8116, -73.9465),
    "10032": (40.8477, -73.9390),
    "10034": (40.8563, -73.9270),
    "11101": (40.7447, -73.9485),
    "11103": (40.7644, -73.9235),
    "11104": (40.7432, -73.9196),
    "11209": (40.6300, -74.0300),
    "11211": (40.7081, -73.9571),
    "11213": (40.6694, -73.9442),
    "11214": (40.6000, -73.9900),
    "11215": (40.6724, -73.9778),
    "11216": (40.6872, -73.9418),
    "11354": (40.7590, -73.8290),
    "11372": (40.7496, -73.8837),
    "11373": (40.7360, -73.8780),
    "11375": (40.7306, -73.8470),
}


def coordinates_of(zip_code: str) -> tuple[float, float] | None:
    """Approximate coordinates of a New York ZIP, or None if it is not known."""
    return ZIPS.get(str(zip_code).strip())
