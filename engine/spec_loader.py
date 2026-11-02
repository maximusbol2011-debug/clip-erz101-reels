import json, os, templates
def load():
    return templates.make(json.load(open(os.environ["AUTOPILOT_SPEC"])))
