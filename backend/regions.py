"""Global geofences shared by every vessel; boundary points count as inside."""
import hashlib
import json
from pathlib import Path


def defaults():
    return json.loads(Path(__file__).with_name('default_regions.json').read_text(encoding='utf-8'))


def revision(regions):
    facts = sorted((r['id'], r['version'], r['geometry']) for r in regions)
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def contains(geometry, lon, lat):
    def ring_state(ring):
        inside = False
        for (ax, ay), (bx, by) in zip(ring, ring[1:]):
            cross = (lon-ax)*(by-ay)-(lat-ay)*(bx-ax)
            if abs(cross) < 1e-9 and min(ax,bx) <= lon <= max(ax,bx) and min(ay,by) <= lat <= max(ay,by):
                return 'boundary'
            if (ay > lat) != (by > lat) and lon < (bx-ax)*(lat-ay)/(by-ay)+ax:
                inside = not inside
        return inside
    rings = geometry['coordinates']
    outer = ring_state(rings[0])
    if outer == 'boundary':
        return True
    if not outer:
        return False
    for hole in rings[1:]:
        result = ring_state(hole)
        if result == 'boundary':
            return True
        if result:
            return False
    return True
