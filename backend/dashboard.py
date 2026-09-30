"""Read-only dashboard and paged historical timeline."""
from pydantic import BaseModel, Field
from typing import Literal
from .store import stamp, unpack
from .responses import MonitorOut, EventPage, ObservationOut, EventOut, SourceOut, RegionOut
from .timeline import timeline_assessment


class TimelineAssessment(BaseModel):
    tone: Literal["normal", "warning", "danger", "unknown"]
    label: str
    description: str
    rule_version: int | None = None


class TimelineOut(ObservationOut):
    provider: str
    source: SourceOut
    name: str
    events: list[EventOut] = Field(default_factory=list)
    assessment: TimelineAssessment | None = None


class TimelinePage(BaseModel):
    items: list[TimelineOut]
    total: int
    limit: int
    offset: int
    snapshot: int


class DashboardOut(BaseModel):
    updated_at: str
    monitors: list[MonitorOut]
    regions: list[RegionOut]
    events: EventPage


class Dashboard:
    def __init__(self, store):
        self.store = store

    def timeline(self, limit=10, offset=0, snapshot=None, kind=None, entry_type="all", severity=None):
        with self.store.connection() as db:
            # Freeze the set of rows while paging so concurrent polling cannot shift pages.
            db.execute("BEGIN")
            if snapshot is None:
                snapshot = db.execute("SELECT COALESCE(MAX(rowid),0) FROM observations").fetchone()[0]
            conditions, args = ["o.rowid<=?", "m.deleted_at IS NULL"], [snapshot]
            if kind:
                conditions.append("m.kind=?")
                args.append(kind)
            if entry_type == "quality":
                conditions.append("o.quality<>'evaluated'")
            if entry_type == "events" or severity:
                event_filter = " AND re.severity=?" if severity else ""
                conditions.append("EXISTS(SELECT 1 FROM evaluations ev JOIN risk_events re ON re.evaluation_id=ev.id WHERE ev.observation_id=o.id" + event_filter + ")")
                if severity:
                    args.append(severity)
            source = " FROM observations o JOIN monitors m ON m.id=o.monitor_id JOIN raw_records rr ON rr.id=o.raw_id WHERE " + " AND ".join(conditions)
            total = db.execute("SELECT COUNT(*)" + source, args).fetchone()[0]
            rows = db.execute("SELECT o.*,m.name,rr.provider" + source + " ORDER BY o.observed_at DESC,o.id DESC LIMIT ? OFFSET ?", (*args,limit,offset)).fetchall()
            items = []
            for raw in rows:
                row = unpack(raw, ("data",))
                evaluation = unpack(db.execute("SELECT * FROM evaluations WHERE observation_id=? ORDER BY evaluated_at DESC,id DESC LIMIT 1", (row["id"],)).fetchone(), ("evidence",))
                events = [unpack(r, ("evidence",)) for r in db.execute("SELECT re.*,m.name AS monitor_name,m.kind FROM risk_events re JOIN evaluations ev ON ev.id=re.evaluation_id JOIN monitors m ON m.id=re.monitor_id WHERE ev.observation_id=? ORDER BY re.created_at,re.id", (row["id"],))]
                row["source"] = self.store.registry.source(row["provider"])
                row["events"] = events
                row["assessment"] = timeline_assessment(row, evaluation, events)
                items.append(row)
            return {"items": items, "total": total, "limit": limit, "offset": offset, "snapshot": snapshot}

    def dashboard(self):
        return {'updated_at':stamp(), 'monitors':self.store.monitors(),
                'regions':self.store.regions(), 'events':self.store.events(limit=100)}
