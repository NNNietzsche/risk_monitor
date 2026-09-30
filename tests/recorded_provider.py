"""Retrieval and normalization are separate: raw payload is committed first."""
from datetime import datetime, timedelta
from typing import Protocol
from backend.models import Observation

VESSEL_SCENARIOS = {"sequence", "outside", "inside", "boundary", "missing", "stale", "out_of_order", "duplicate", "failure"}
FLIGHT_SCENARIOS = {"sequence", "on_time", "delayed", "recovered", "cancelled", "diverted", "actual", "missing", "stale", "out_of_order", "duplicate", "failure"}


class Provider(Protocol):
    name: str
    def fetch(self, target: dict, scenario: str, now: datetime) -> dict: ...
    def normalize(self, payload: dict, target: dict) -> Observation: ...


class MockProvider:
    name = "recorded-v1"

    scenario = "sequence"

    def fetch(self, target, now):
        scenario = self.scenario
        if scenario == "failure":
            raise TimeoutError("模拟数据源超时")
        if scenario == "duplicate" and target.get("latest"):
            return {"mock": True, "target_id": target["id"], "observation": target["latest"]["data"]}
        if scenario == "sequence":
            steps = ["outside", "inside", "inside", "outside"] if target["kind"] == "vessel" else ["on_time", "delayed", "delayed", "recovered"]
            scenario = steps[target["cursor"] % len(steps)]
        observed = now
        if scenario == "stale":
            observed = now - timedelta(hours=2)
        if scenario == "out_of_order":
            observed = datetime.fromisoformat(target["latest"]["observed_at"]) - timedelta(seconds=1) if target.get("latest") else now - timedelta(hours=2)
        data = {"kind": target["kind"], "observed_at": observed.isoformat()}
        if target["kind"] == "vessel":
            west, south, east, north = next(r for r in target["regions"] if r["id"]=="test-zone")["geometry"]["bbox"]
            lon, lat = (west + east) / 2, (south + north) / 2
            if scenario == "outside":
                if west > -180:
                    lon = west - min(1, (west + 180) / 2)
                elif east < 180:
                    lon = east + min(1, (180 - east) / 2)
                elif south > -90:
                    lat = south - min(1, (south + 90) / 2)
                elif north < 90:
                    lat = north + min(1, (90 - north) / 2)
            if scenario == "boundary":
                lon = west
            # Keep the built-in demo's regular positions at sea, while preserving
            # its outside/inside transition and leaving custom regions untouched.
            if any(r["id"]=="test-zone" for r in target["regions"]) and scenario != "boundary":
                lon, lat = (52, 12) if scenario == "outside" else (47, 12)
            data.update(latitude=lat, longitude=lon, navigation_status="under_way")
            if scenario == "missing":
                data["latitude"] = None
        else:
            departure = datetime.fromisoformat(target["flight"]["scheduled_departure"])
            arrival = datetime.fromisoformat(target["flight"]["scheduled_arrival"])
            delay = target["rule"]["config"]["threshold_minutes"] + 20 if scenario == "delayed" else 0
            data.update(estimated_departure=(departure + timedelta(minutes=delay)).isoformat(),
                        estimated_arrival=(arrival + timedelta(minutes=delay)).isoformat(), flight_status="scheduled")
            # Fictional demo positions, independent of schedule/delay calculations.
            # Unsupported routes deliberately have no position rather than a guessed location.
            route = (target["flight"]["departure"], target["flight"]["arrival"])
            points = [(139.7,35.6), (137,35.2), (134,34.2), (131,33), (128,31.8), (125,31.3), (121.8,31.2)]
            if route in {("HND", "PVG"), ("PVG", "HND")}:
                if route[0] == "PVG":
                    points.reverse()
                lon, lat = points[-1] if scenario == "actual" else points[target["cursor"] % len(points)]
                data.update(longitude=lon, latitude=lat, flight_status="active")
            if scenario in {"cancelled", "diverted"}:
                data["flight_status"] = scenario
                if scenario == "cancelled":
                    data["latitude"] = data["longitude"] = None
            if scenario == "actual":
                data.update(actual_departure=(departure + timedelta(minutes=90)).isoformat(),
                            estimated_departure=(departure + timedelta(minutes=20)).isoformat(),
                            actual_arrival=(arrival + timedelta(minutes=90)).isoformat(), flight_status="landed")
            if scenario == "missing":
                data["estimated_departure"] = data["estimated_arrival"] = None
                data["latitude"] = data["longitude"] = None
        return {"mock": True, "target_id": target["id"], "observation": data}

    def normalize(self, payload, target):
        if payload.get("target_id") != target["id"]:
            raise ValueError("数据对象与监控对象不匹配")
        result = Observation.model_validate(payload["observation"])
        if result.kind != target["kind"]:
            raise ValueError("数据类型与监控对象不匹配")
        return result
