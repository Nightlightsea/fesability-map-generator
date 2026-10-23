"""Method constants shared by the feasibility-map program.

Everything a researcher tweaks for experiments (points, offsets, colors,
paths) lives in points.json.  This file holds only routing/render methodology:
free-flow speeds by OSM road class, drawn line widths, tile-fetch settings.
"""
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA = os.path.join(PACKAGE_DIR, "points.json")
CACHE_DIR = os.path.join(PACKAGE_DIR, "cache")

# km/h free-flow speeds by OSM road class (modern)
SPEED_MODERN = {
    "motorway": 105, "motorway_link": 60,
    "trunk": 90, "trunk_link": 55,
    "primary": 80, "primary_link": 50,
    "secondary": 70, "secondary_link": 45,
    "tertiary": 60, "tertiary_link": 40,
    "unclassified": 50, "residential": 40, "living_street": 25,
}

# km/h period speeds (pre-1974 limit regime); used only for the
# first-scene sensitivity check
SPEED_1969 = {
    "motorway": 100, "motorway_link": 55,
    "trunk": 85, "trunk_link": 50,
    "primary": 70, "primary_link": 45,
    "secondary": 60, "secondary_link": 40,
    "tertiary": 50, "tertiary_link": 35,
    "unclassified": 40, "residential": 30, "living_street": 20,
}

# drawn line width (points) by class family
LINE_WIDTH = {
    "motorway": 2.6, "trunk": 2.2, "primary": 1.8, "secondary": 1.4,
    "tertiary": 1.1, "unclassified": 0.8, "residential": 0.55,
    "living_street": 0.45,
}

HW_FAMILY = ("motorway", "trunk", "primary", "secondary", "tertiary",
             "unclassified", "residential", "living_street")

# road classes fetched from Overpass (full class name incl. _link variants)
ROAD_CLASS_REGEX = ("^(motorway|trunk|primary|secondary|tertiary|unclassified|"
                    "residential)(_link)?$")

OVERPASS_HOSTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
HTTP_HEADERS = {
    "User-Agent": "zodiac-cipher-research/1.0 (educational; local researcher)",
    "Accept": "application/json",
}
USER_AGENT = ("zodiac-cipher-research/1.0 "
              "(educational Bayesian/cipher investigation; local researcher)")
