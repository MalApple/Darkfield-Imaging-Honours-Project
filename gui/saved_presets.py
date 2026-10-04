import json
import os


PRESETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets.json")

def load_presets():
    try:
        with open(PRESETS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}  

def save_presets(presets):
    with open(PRESETS_FILE, "w") as f:
        json.dump(presets, f, indent=4)