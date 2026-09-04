PROFILES = {
    "NEXT_DAY": {
        "db_strategy": "next_day",
        "horizon_days": 1,
        "artifact": "champion_next_day.joblib",
        "min_probability": 0.55,
        "min_rr": 1.5,
        "label": "Daily / Next Day",
    },
    "SWING": {
        "db_strategy": "swing_5d",
        "horizon_days": 5,
        "artifact": "champion_swing.joblib",
        "min_probability": 0.55,
        "min_rr": 2.0,
        "label": "Swing 3–5 Days",
    },
    "SCALP": {
        "db_strategy": "scalp_intraday",
        "horizon_days": 0,
        "artifact": "champion_scalp.joblib",
        "min_probability": 0.60,
        "min_rr": 1.5,
        "label": "Scalp Intraday",
    },
}


def get_profile(name):
    return PROFILES.get((name or "NEXT_DAY").upper(), PROFILES["NEXT_DAY"])
