"""Render autopilot specs to mp4.  python3 render_specs.py specs/2026-11-02/*.json"""
import json, os, sys, time, importlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "reels-engine"))
import templates, lib




def render_spec(path, outdir, work):
    spec = json.load(open(path))
    os.environ["AUTOPILOT_SPEC"] = path
    out = os.path.join(outdir, spec["slug"] + ".mp4")
    t = time.time()
    v = lib.render("spec_loader", "load", out, work)
    print(spec["slug"], round(v.total, 1), "s video in", round(time.time() - t), "s", flush=True)
    return out

if __name__ == "__main__":
    outdir = os.environ.get("OUTDIR", os.path.join(HERE, "out"))
    work = os.environ.get("WORKDIR", "/tmp/autopilot-work")
    os.makedirs(outdir, exist_ok=True)
    for p in sys.argv[1:]:
        render_spec(p, outdir, work)
