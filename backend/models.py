from datetime import date, datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("时间必须包含时区，例如 +09:00 或 Z")
    return value.astimezone(timezone.utc)


class BusinessProfile(StrictModel):
    vessel_type: Literal['container','tanker','liquid_cargo','bulk','cargo','passenger','pilot','tug','fishing','other'] | None = None
    aircraft_role: Literal['passenger','cargo','mixed','other'] | None = None
    aircraft_model: str | None = Field(default=None, min_length=1, max_length=30)


class MonitorCreate(StrictModel):
    kind: Literal["vessel", "flight", "aircraft"]
    name: str = Field(min_length=1, max_length=100)
    profile: BusinessProfile = Field(default_factory=BusinessProfile)
    provider: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    remark: str = Field(default='', max_length=100)
    icao24: str | None = Field(default=None, pattern=r"^[0-9a-f]{6}$")
    source_ref: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    imo: str | None = Field(default=None, pattern=r"^\d{7}$")
    mmsi: str | None = Field(default=None, pattern=r"^\d{9}$")
    carrier: str | None = Field(default=None, pattern=r"^[A-Z0-9]{2,3}$")
    flight_number: str | None = Field(default=None, pattern=r"^[0-9]{1,4}[A-Z]?$")
    service_date: date | None = None
    departure: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    arrival: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    scheduled_departure: datetime | None = None
    scheduled_arrival: datetime | None = None
    aircraft_registration: str | None = Field(default=None, pattern=r"^[A-Z0-9-]{3,12}$")
    threshold_minutes: int = Field(default=60, ge=1, le=1440)
    delay_basis: Literal["departure", "arrival"] = "departure"

    @model_validator(mode="after")
    def validate_business(self):
        if self.kind == "vessel" and (self.profile.aircraft_role or self.profile.aircraft_model):
            raise ValueError("船舶不能填写航空属性")
        if self.kind != "vessel" and self.profile.vessel_type:
            raise ValueError("航空目标不能填写船型")
        flight_fields = ("carrier", "flight_number", "service_date", "departure", "arrival", "scheduled_departure", "scheduled_arrival")
        if self.kind == "aircraft":
            if not self.aircraft_registration:
                raise ValueError("飞机实体需要注册号")
            if any(getattr(self, key) is not None for key in (*flight_fields, "imo", "mmsi")):
                raise ValueError("飞机实体不能包含具体航班或船舶字段")
            return self
        if self.icao24:
            raise ValueError("ICAO24 仅用于飞机实体")
        if self.kind == "vessel":
            if not self.imo and not self.mmsi and not self.source_ref:
                raise ValueError("船舶需要有效标识码")
            if self.imo and sum(int(n) * w for n, w in zip(self.imo[:6], range(7, 1, -1))) % 10 != int(self.imo[-1]):
                raise ValueError("IMO 校验位不正确")
            if any(getattr(self, key) is not None for key in (*flight_fields, "aircraft_registration")):
                raise ValueError("船舶不能包含航班字段")
        else:
            if self.imo or self.mmsi:
                raise ValueError("航班不能包含船舶字段")
            if any(getattr(self, key) is None for key in flight_fields):
                raise ValueError("航班需要运营方、班号、服务日期、机场和计划时间")
            if self.departure == self.arrival:
                raise ValueError("起降机场必须不同")
            if self.scheduled_departure.date() != self.service_date:
                raise ValueError("服务日期必须等于所填出发地时区的计划起飞日期")
            self.scheduled_departure = utc(self.scheduled_departure)
            self.scheduled_arrival = utc(self.scheduled_arrival)
            if self.scheduled_arrival <= self.scheduled_departure:
                raise ValueError("计划到达时间必须晚于起飞时间")
        return self


class MonitorPatch(StrictModel):
    enabled: bool


class RuleChange(StrictModel):
    threshold_minutes: int = Field(ge=1, le=1440)
    delay_basis: Literal["departure", "arrival"] = "departure"


class RegionCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)

    @model_validator(mode="after")
    def bounds(self):
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("需要 west < east、south < north；MVP 不支持跨日界线区域")
        return self


class Enrollment(StrictModel):
    kind: Literal['vessel', 'aircraft']
    identifier_type: Literal['imo', 'mmsi', 'registration']
    identifier: str = Field(min_length=1, max_length=20)
    remark: str = Field(default='', max_length=100)

    @model_validator(mode='after')
    def identity(self):
        import re
        if self.kind == 'aircraft':
            self.identifier = self.identifier.upper()
            if self.identifier_type != 'registration' or not re.fullmatch(r'[A-Z0-9-]{3,12}',self.identifier):
                raise ValueError('请填写有效飞机注册号，例如 JA602F')
        elif self.identifier_type == 'registration':
            raise ValueError('船舶请选择 IMO 或 MMSI')
        elif self.identifier_type == 'imo':
            if not re.fullmatch(r'[0-9]{7}',self.identifier):
                raise ValueError('IMO 应为 7 位数字')
            if sum(int(n)*w for n,w in zip(self.identifier[:6],range(7,1,-1)))%10 != int(self.identifier[-1]):
                raise ValueError('IMO 校验位不正确，请核对标识码')
        elif not re.fullmatch(r'[0-9]{9}',self.identifier) or int(self.identifier) == 0:
            raise ValueError('MMSI 应为 9 位数字')
        return self


class RemarkPatch(StrictModel):
    remark: str = Field(default='', max_length=100)


class PollRequest(StrictModel):
    """No caller-supplied source scenarios or overrides are accepted."""
    pass


class Observation(StrictModel):
    observed_at: datetime
    kind: Literal["vessel", "flight", "aircraft"]
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    navigation_status: str | None = None
    callsign: str | None = None
    aircraft_type: str | None = None
    vessel_type: str | None = None
    vessel_name: str | None = Field(default=None, max_length=100)
    aircraft_role: str | None = None
    aircraft_category: str | None = Field(default=None, max_length=120)
    flight_number: str | None = Field(default=None, max_length=30)
    flight_source_ref: str | None = Field(default=None, max_length=64)
    scheduled_departure: datetime | None = None
    scheduled_arrival: datetime | None = None
    location_name: str | None = Field(default=None, max_length=120)
    departure_port: str | None = Field(default=None, max_length=120)
    arrival_port: str | None = Field(default=None, max_length=120)
    departure_port_code: str | None = Field(default=None, max_length=12)
    arrival_port_code: str | None = Field(default=None, max_length=12)
    reported_destination: str | None = Field(default=None, max_length=120)
    vessel_flag: str | None = Field(default=None, max_length=80)
    vessel_length: float | None = Field(default=None, gt=0)
    vessel_width: float | None = Field(default=None, gt=0)
    speed_knots: float | None = Field(default=None, ge=0)
    course_degrees: float | None = Field(default=None, ge=0, le=360)
    draught_meters: float | None = Field(default=None, ge=0)
    has_newer_satellite_position: bool | None = None
    flight_context: Literal['live', 'recent', 'scheduled'] | None = None
    departure: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    arrival: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    departure_name: str | None = Field(default=None, max_length=160)
    arrival_name: str | None = Field(default=None, max_length=160)
    position_observed_at: datetime | None = None
    estimated_departure: datetime | None = None
    actual_departure: datetime | None = None
    estimated_arrival: datetime | None = None
    actual_arrival: datetime | None = None
    flight_status: Literal["scheduled", "active", "landed", "cancelled", "diverted"] | None = None

    @model_validator(mode="after")
    def times(self):
        for key in ("observed_at", "position_observed_at", "scheduled_departure", "scheduled_arrival", "estimated_departure", "actual_departure", "estimated_arrival", "actual_arrival"):
            value = getattr(self, key)
            if value is not None:
                setattr(self, key, utc(value))
        return self
