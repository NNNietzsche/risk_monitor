import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .models import MonitorCreate, RegionCreate
from .providers import MockProvider, VESSEL_SCENARIOS, FLIGHT_SCENARIOS
from .rules import ENGINE_VERSION, evaluate


def stamp():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def unpack(row, fields=()):
    if row is None:
        return None
    result = dict(row)
    for field in fields:
        if field in result:
            result[field] = json.loads(result[field])
    return result


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class ClosingConnection:
    def __init__(self, db):
        self.db = db
    def __enter__(self):
        return self.db
    def __exit__(self, kind, value, trace):
        try:
            self.db.rollback() if kind else self.db.commit()
        finally:
            self.db.close()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.providers = {"mock-v1": MockProvider()}
        with self.connection() as db:
            db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
            db.execute("INSERT OR IGNORE INTO schema_versions VALUES (1,?)", (stamp(),))
            db.execute("INSERT OR IGNORE INTO regions VALUES (?,?,?,?,?)",
                       ("demo-zone", "演示区域 A（非真实风险评级）", 1,
                        encoded({"type": "Polygon", "coordinates": [[[40,10],[50,10],[50,20],[40,20],[40,10]]],
                                 "bbox": [40,10,50,20]}), stamp()))
            db.execute("PRAGMA optimize")

    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return ClosingConnection(db)

    def _target(self, db, monitor_id):
        m = unpack(db.execute("SELECT * FROM monitors WHERE id=?", (monitor_id,)).fetchone(), ("state",))
        if not m:
            raise NotFound("监控对象不存在")
        m["enabled"] = bool(m["enabled"])
        m["rule"] = unpack(db.execute("SELECT * FROM rule_versions WHERE id=?", (m["rule_id"],)).fetchone(), ("config",))
        m["asset"] = unpack(db.execute("SELECT * FROM assets WHERE id=?", (m["asset_id"],)).fetchone())
        m["flight"] = unpack(db.execute("SELECT * FROM flight_instances WHERE id=?", (m["flight_id"],)).fetchone())
        m["region"] = unpack(db.execute("SELECT * FROM regions WHERE id=?", (m["rule"]["config"].get("region_id"),)).fetchone(), ("geometry",))
        m["latest"] = unpack(db.execute("SELECT * FROM observations WHERE monitor_id=? AND quality='evaluated' ORDER BY observed_at DESC LIMIT 1", (monitor_id,)).fetchone(), ("data",))
        if m["latest"] and m["health"] == "ok":
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(m["latest"]["observed_at"])).total_seconds()
            if age > m["rule"]["config"]["max_age_seconds"]:
                m["health"] = "stale"
        return m

    def monitors(self):
        with self.connection() as db:
            return [self._target(db, r["id"]) for r in db.execute("SELECT id FROM monitors ORDER BY created_at DESC").fetchall()]

    def detail(self, monitor_id):
        with self.connection() as db:
            result = self._target(db, monitor_id)
            result["observations"] = [unpack(r, ("data",)) for r in db.execute("SELECT * FROM observations WHERE monitor_id=? ORDER BY observed_at DESC LIMIT 50", (monitor_id,))]
            result["raw_records"] = [unpack(r, ("payload",)) for r in db.execute("SELECT * FROM raw_records WHERE monitor_id=? ORDER BY received_at DESC LIMIT 20", (monitor_id,))]
            result["evaluations"] = [unpack(r, ("evidence",)) for r in db.execute("SELECT * FROM evaluations WHERE monitor_id=? ORDER BY evaluated_at DESC LIMIT 50", (monitor_id,))]
            result["configuration_audit"] = [unpack(r, ("before_value","after_value")) for r in db.execute("SELECT * FROM configuration_audit WHERE monitor_id=? ORDER BY created_at DESC LIMIT 50", (monitor_id,))]
            return result

    def regions(self):
        with self.connection() as db:
            return [unpack(r, ("geometry",)) for r in db.execute("SELECT * FROM regions ORDER BY created_at")]

    def create_region(self, request: RegionCreate):
        region_id = uid()
        w, s, e, n = request.west, request.south, request.east, request.north
        geometry = {"type": "Polygon", "coordinates": [[[w,s],[e,s],[e,n],[w,n],[w,s]]], "bbox": [w,s,e,n]}
        with self.lock, self.connection() as db:
            db.execute("INSERT INTO regions VALUES (?,?,?,?,?)", (region_id, request.name, 1, encoded(geometry), stamp()))
        return next(r for r in self.regions() if r["id"] == region_id)

    def create_monitor(self, request: MonitorCreate):
        m_id, rule_id = uid(), uid()
        asset_id = flight_id = None
        config = {"max_age_seconds": 900}
        try:
            with self.lock, self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                if request.kind == "vessel":
                    if not db.execute("SELECT id FROM regions WHERE id=?", (request.region_id,)).fetchone():
                        raise NotFound("风险区域不存在")
                    asset_id = uid()
                    db.execute("INSERT INTO assets(id,kind,name,imo,mmsi) VALUES (?,?,?,?,?)",
                               (asset_id, "vessel", request.name, request.imo, request.mmsi))
                    config["region_id"] = request.region_id
                else:
                    aircraft_id = None
                    if request.aircraft_registration:
                        row = db.execute("SELECT id FROM assets WHERE registration=?", (request.aircraft_registration,)).fetchone()
                        aircraft_id = row["id"] if row else uid()
                        if not row:
                            db.execute("INSERT INTO assets(id,kind,name,registration) VALUES (?,?,?,?)",
                                       (aircraft_id, "aircraft", request.aircraft_registration, request.aircraft_registration))
                    flight_id = uid()
                    db.execute("INSERT INTO flight_instances VALUES (?,?,?,?,?,?,?,?,?)",
                               (flight_id, aircraft_id, request.carrier, request.flight_number, str(request.service_date),
                                request.departure, request.arrival, request.scheduled_departure.isoformat(), request.scheduled_arrival.isoformat()))
                    config.update(threshold_minutes=request.threshold_minutes, delay_basis=request.delay_basis)
                db.execute("INSERT INTO rule_versions VALUES (?,?,?,?,?,?)", (rule_id, request.kind, 1, ENGINE_VERSION, encoded(config), stamp()))
                db.execute("INSERT INTO monitors(id,name,kind,asset_id,flight_id,rule_id,created_at) VALUES (?,?,?,?,?,?,?)",
                           (m_id, request.name, request.kind, asset_id, flight_id, rule_id, stamp()))
                self._audit(db, m_id, "created", {}, request.model_dump(mode="json"))
        except sqlite3.IntegrityError as exc:
            raise Conflict("相同 IMO/MMSI 的船舶或相同航班实例已经存在") from exc
        return self.detail(m_id)

    def _audit(self, db, monitor_id, action, before, after):
        db.execute("INSERT INTO configuration_audit VALUES (?,?,?,?,?,?)",
                   (uid(), monitor_id, action, encoded(before), encoded(after), stamp()))

    def set_enabled(self, monitor_id, enabled):
        with self.lock, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            m = self._target(db, monitor_id)
            db.execute("UPDATE monitors SET enabled=? WHERE id=?", (int(enabled), monitor_id))
            self._audit(db, monitor_id, "enabled", {"enabled": m["enabled"]}, {"enabled": enabled})
        return self.detail(monitor_id)

    def change_rule(self, monitor_id, request):
        with self.lock, self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            m = self._target(db, monitor_id)
            if m["kind"] != "flight":
                raise Conflict("此接口仅支持航班延误规则")
            old = m["rule"]
            config = {**old["config"], **request.model_dump()}
            new_id = uid()
            db.execute("INSERT INTO rule_versions VALUES (?,?,?,?,?,?)",
                       (new_id, "flight", old["version"] + 1, ENGINE_VERSION, encoded(config), stamp()))
            db.execute("UPDATE monitors SET rule_id=?,state='{}',health='unknown' WHERE id=?", (new_id, monitor_id))
            self._audit(db, monitor_id, "rule_changed", old, {"id": new_id, "config": config})
        return self.detail(monitor_id)

    def poll(self, monitor_id, scenario="sequence"):
        with self.lock:
            with self.connection() as db:
                m = self._target(db, monitor_id)
            if not m["enabled"]:
                raise Conflict("该监控已暂停")
            allowed = VESSEL_SCENARIOS if m["kind"] == "vessel" else FLIGHT_SCENARIOS
            if scenario not in allowed:
                raise ValueError("此场景不适用于该监控类型")
            now, raw_id = datetime.now(timezone.utc), uid()
            provider = self.providers[m["provider"]]
            error = None
            try:
                payload = provider.fetch(m, scenario, now)
            except (TimeoutError, ConnectionError, ValueError) as exc:
                payload, error = {"scenario": scenario, "error": str(exc), "mock": True}, str(exc)
            body = encoded(payload)
            # Commit original data before any normalization or risk evaluation.
            with self.connection() as db:
                db.execute("INSERT INTO raw_records VALUES (?,?,?,?,?,?,?,?)",
                           (raw_id, monitor_id, provider.name, now.isoformat(), body,
                            hashlib.sha256(body.encode()).hexdigest(), "fetch_error" if error else "received", error))
                db.execute("UPDATE monitors SET last_poll_at=?,cursor=cursor+1 WHERE id=?", (now.isoformat(), monitor_id))
            if error:
                with self.connection() as db:
                    db.execute("UPDATE monitors SET health='error',last_error=? WHERE id=?", (error, monitor_id))
                return {"raw_id": raw_id, "outcome": "fetch_error", "events": []}
            try:
                observation = provider.normalize(payload, m)
                data = observation.model_dump(mode="json")
                observed_at = observation.observed_at.isoformat()
            except (ValueError, KeyError, TypeError) as exc:
                self._reject(raw_id, monitor_id, "invalid", str(exc))
                return {"raw_id": raw_id, "outcome": "invalid", "events": []}
            try:
                with self.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    m = self._target(db, monitor_id)
                    latest_any = db.execute("SELECT observed_at FROM observations WHERE monitor_id=? ORDER BY observed_at DESC LIMIT 1", (monitor_id,)).fetchone()
                    if latest_any and observed_at <= latest_any["observed_at"]:
                        outcome = "duplicate" if observed_at == latest_any["observed_at"] else "out_of_order"
                        db.execute("UPDATE raw_records SET outcome=? WHERE id=?", (outcome, raw_id))
                        return {"raw_id": raw_id, "outcome": outcome, "events": []}
                    age = (now - observation.observed_at).total_seconds()
                    if age > m["rule"]["config"]["max_age_seconds"] or age < -60:
                        outcome = "stale" if age > 0 else "future"
                        db.execute("UPDATE raw_records SET outcome=? WHERE id=?", (outcome, raw_id))
                        db.execute("UPDATE monitors SET health=?,last_error=? WHERE id=?", (outcome, "数据时间不在有效窗口内", monitor_id))
                        return {"raw_id": raw_id, "outcome": outcome, "events": []}
                    state, quality, evidence, specs = evaluate(m, data)
                    obs_id, evaluation_id = uid(), uid()
                    evidence.update(observation_id=obs_id, raw_id=raw_id, raw_sha256=hashlib.sha256(body.encode()).hexdigest(),
                                    rule_id=m["rule_id"], rule_version=m["rule"]["version"])
                    db.execute("INSERT INTO observations VALUES (?,?,?,?,?,?)", (obs_id, monitor_id, raw_id, observed_at, encoded(data), quality))
                    db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?,?,?)",
                               (evaluation_id, monitor_id, obs_id, m["rule_id"], stamp(), quality, encoded(evidence)))
                    events = []
                    for event_type, severity, summary in specs:
                        event_id = uid()
                        db.execute("INSERT INTO risk_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (event_id, monitor_id, evaluation_id, m["rule_id"], event_type, severity, observed_at, stamp(), summary, encoded(evidence)))
                        events.append(event_id)
                    db.execute("UPDATE raw_records SET outcome=? WHERE id=?", (quality, raw_id))
                    db.execute("UPDATE monitors SET health=?,last_error=?,state=? WHERE id=?",
                               ("ok" if quality == "evaluated" else "missing", None if quality == "evaluated" else "关键字段缺失",
                                encoded(state if state is not None else m["state"]), monitor_id))
                    return {"raw_id": raw_id, "outcome": quality, "events": events}
            except Exception as exc:
                self._reject(raw_id, monitor_id, "processing_error", type(exc).__name__)
                raise

    def _reject(self, raw_id, monitor_id, outcome, message):
        with self.connection() as db:
            db.execute("UPDATE raw_records SET outcome=?,error=? WHERE id=?", (outcome, message, raw_id))
            db.execute("UPDATE monitors SET health=?,last_error=? WHERE id=?", (outcome, message, monitor_id))

    def poll_all(self):
        results = []
        for m in self.monitors():
            if m["enabled"]:
                try:
                    results.append({"monitor_id": m["id"], **self.poll(m["id"])})
                except Exception as exc:
                    results.append({"monitor_id": m["id"], "outcome": "error", "error": type(exc).__name__})
        return results

    def events(self, monitor_id=None, kind=None, severity=None, since=None, until=None, limit=100, offset=0):
        where, values = [], []
        for key, value in (("e.monitor_id", monitor_id), ("m.kind", kind), ("e.severity", severity)):
            if value:
                where.append(key + "=?")
                values.append(value)
        for operator, value in ((">=", since), ("<=", until)):
            if value:
                where.append("e.occurred_at" + operator + "?")
                values.append(value)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM risk_events e JOIN monitors m ON m.id=e.monitor_id" + clause, values).fetchone()[0]
            rows = db.execute("SELECT e.*,m.name AS monitor_name,m.kind FROM risk_events e JOIN monitors m ON m.id=e.monitor_id" + clause + " ORDER BY e.created_at DESC LIMIT ? OFFSET ?", [*values, limit, offset])
            return {"items": [unpack(r, ("evidence",)) for r in rows], "total": total, "limit": limit, "offset": offset}

    def event_detail(self, event_id):
        with self.connection() as db:
            event = unpack(db.execute("SELECT e.*,m.name AS monitor_name,m.kind FROM risk_events e JOIN monitors m ON m.id=e.monitor_id WHERE e.id=?", (event_id,)).fetchone(), ("evidence",))
            if not event:
                raise NotFound("事件不存在")
            event["raw_record"] = unpack(db.execute("SELECT * FROM raw_records WHERE id=?", (event["evidence"]["raw_id"],)).fetchone(), ("payload",))
            event["rule"] = unpack(db.execute("SELECT * FROM rule_versions WHERE id=?", (event["rule_id"],)).fetchone(), ("config",))
            event["previous_observation"] = unpack(db.execute("SELECT * FROM observations WHERE id=?", (event["evidence"].get("previous_observation_id"),)).fetchone(), ("data",))
            return event
