"""Static climate knowledge used by the weather_info endpoint."""

CLIMATE_PROFILES = {
    "tropical": {"summary": "Warm all year with a wet and a dry season.",
                 "seasons": {"dry": "Dec-Mar, 27-32C, best for beaches", "wet": "Jun-Oct, 24-30C, heavy afternoon showers"}},
    "dry": {"summary": "Hot, sunny days and cool nights with little rain.",
            "seasons": {"summer": "Jun-Sep, 35C+, very hot", "winter": "Dec-Feb, 12-22C, comfortable"}},
    "temperate": {"summary": "Four distinct seasons with mild summers.",
                  "seasons": {"spring": "Mar-May, 8-18C", "summer": "Jun-Aug, 18-27C",
                              "autumn": "Sep-Nov, 8-18C", "winter": "Dec-Feb, 0-8C"}},
    "continental": {"summary": "Hot summers and cold winters.",
                    "seasons": {"summer": "Jun-Aug, 20-30C", "winter": "Dec-Feb, -10-2C"}},
    "polar": {"summary": "Cold year-round; long daylight or darkness by season.",
              "seasons": {"summer": "Jun-Aug, 0-10C, midnight sun", "winter": "Dec-Feb, -30-(-10)C, polar night"}},
}
