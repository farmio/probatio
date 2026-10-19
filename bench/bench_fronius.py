"""Validate a Fronius inverter response: mashumaro vs probatio (interpreted and compiled).

Run with: ``uv run --no-sync python bench/bench_fronius.py``.

The workload is one real-world request: the Fronius Solar API v1
``GetInverterRealtimeData.cgi`` response (``Scope=Device``,
``DataCollection=CommonInverterData``), the document Home Assistant's Fronius
integration polls from every inverter. It is a deeper, more irregular shape than the
synthetic rows in ``bench_dataclass.py``: three levels of nesting, API keys that do
not match Python field names (``Head``, ``DAY_ENERGY``, ``MgmtTimerRemainingTime``),
unit/value pairs that repeat ten times, and two fields an inverter omits at night.

The tree is modeled two ways, because the key naming decides which engine runs:

- *aliased*: Python field names (``day_energy``) read from the API key through an
  alias. This is how you would write it. probatio's code generator does not handle
  alias keys (``_is_generatable`` in ``_codegen.py``), so ``.compile()`` leaves the
  schema interpreted and the compiled column is reported as such.
- *api-named*: the API key is the field name (``DAY_ENERGY``). Unconventional, but
  no alias, so the top-level mapping compiles.

Even then the compiled column barely moves, and that is the second thing this
benchmark shows: ``DataclassSchema.compile()`` generates code for the outer mapping
only. A nested dataclass field is validated by the nested ``DataclassSchema``'s own
engine, which stays on its interpreted fused validator (``_compile_from`` in
``dataclass_schema.py`` does not recurse into it, and the nested schema is never
called through ``Schema.__call__``, so the ``AUTO`` policy never compiles it
either). Nine of this tree's ten mappings are nested, so nearly all the work stays
interpreted whatever the policy.

As in ``bench_dataclass.py``, this is not an apples-to-apples comparison. mashumaro's
generated ``from_dict`` builds the dataclass and mostly trusts the declared types;
probatio's ``DataclassSchema`` checks every leaf against its type (a ``Value`` of
``"300"`` is rejected, not stored) and then constructs. The rejection scenario at the
end shows the difference on a malformed response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Annotated, Any

from mashumaro import DataClassDictMixin

import probatio

probatio.set_compile_policy(probatio.CompilePolicy.OFF)


def _is_compiled(schema: probatio.Schema) -> bool:
    """Report whether the schema swapped in a generated validator."""
    return getattr(schema._compiled, "__name__", "") == "_validate"


# --- probatio, aliased: plain dataclasses, API keys mapped with ``Key(alias=...)`` ---


def _key(api_name: str) -> probatio.Key:
    """A strict rename: the field is read from ``api_name`` only."""
    return probatio.Key(alias=api_name, accept_canonical=False)


@dataclass
class Measurement:
    """One ``{"Unit": ..., "Value": ...}`` pair."""

    unit: Annotated[str, _key("Unit")]
    value: Annotated[float, _key("Value")]


@dataclass
class DeviceStatus:
    """The inverter's status block."""

    error_code: Annotated[int, _key("ErrorCode")]
    led_color: Annotated[int, _key("LEDColor")]
    led_state: Annotated[int, _key("LEDState")]
    mgmt_timer_remaining_time: Annotated[int, _key("MgmtTimerRemainingTime")]
    state_to_reset: Annotated[bool, _key("StateToReset")]
    status_code: Annotated[int, _key("StatusCode")]


@dataclass
class CommonInverterData:
    """``Body.Data`` for ``DataCollection=CommonInverterData``.

    ``IDC``/``UDC`` are absent when the inverter sleeps (no DC side at night).
    """

    day_energy: Annotated[Measurement, _key("DAY_ENERGY")]
    device_status: Annotated[DeviceStatus, _key("DeviceStatus")]
    fac: Annotated[Measurement, _key("FAC")]
    iac: Annotated[Measurement, _key("IAC")]
    pac: Annotated[Measurement, _key("PAC")]
    total_energy: Annotated[Measurement, _key("TOTAL_ENERGY")]
    uac: Annotated[Measurement, _key("UAC")]
    year_energy: Annotated[Measurement, _key("YEAR_ENERGY")]
    idc: Annotated[Measurement | None, _key("IDC")] = None
    udc: Annotated[Measurement | None, _key("UDC")] = None


@dataclass
class Body:
    """The response body."""

    data: Annotated[CommonInverterData, _key("Data")]


@dataclass
class RequestArguments:
    """The request echoed back in the head."""

    data_collection: Annotated[str, _key("DataCollection")]
    device_class: Annotated[str, _key("DeviceClass")]
    device_id: Annotated[str, _key("DeviceId")]
    scope: Annotated[str, _key("Scope")]


@dataclass
class Status:
    """The API status block."""

    code: Annotated[int, _key("Code")]
    reason: Annotated[str, _key("Reason")]
    user_message: Annotated[str, _key("UserMessage")]


@dataclass
class Head:
    """The response head."""

    request_arguments: Annotated[RequestArguments, _key("RequestArguments")]
    status: Annotated[Status, _key("Status")]
    timestamp: Annotated[str, _key("Timestamp")]


@dataclass
class InverterRealtimeData:
    """The whole ``GetInverterRealtimeData.cgi`` response."""

    body: Annotated[Body, _key("Body")]
    head: Annotated[Head, _key("Head")]


# --- probatio, api-named: the API key is the field name, so nothing is aliased ---


@dataclass
class MeasurementApi:
    Unit: str
    Value: float


@dataclass
class DeviceStatusApi:
    ErrorCode: int
    LEDColor: int
    LEDState: int
    MgmtTimerRemainingTime: int
    StateToReset: bool
    StatusCode: int


@dataclass
class CommonInverterDataApi:
    DAY_ENERGY: MeasurementApi
    DeviceStatus: DeviceStatusApi
    FAC: MeasurementApi
    IAC: MeasurementApi
    PAC: MeasurementApi
    TOTAL_ENERGY: MeasurementApi
    UAC: MeasurementApi
    YEAR_ENERGY: MeasurementApi
    IDC: MeasurementApi | None = None
    UDC: MeasurementApi | None = None


@dataclass
class BodyApi:
    Data: CommonInverterDataApi


@dataclass
class RequestArgumentsApi:
    DataCollection: str
    DeviceClass: str
    DeviceId: str
    Scope: str


@dataclass
class StatusApi:
    Code: int
    Reason: str
    UserMessage: str


@dataclass
class HeadApi:
    RequestArguments: RequestArgumentsApi
    Status: StatusApi
    Timestamp: str


@dataclass
class InverterRealtimeDataApi:
    Body: BodyApi
    Head: HeadApi


# --- mashumaro, aliased: the same tree with its mixin and ``alias`` metadata ---


@dataclass
class MeasurementMashumaro(DataClassDictMixin):
    unit: str = field(metadata={"alias": "Unit"})
    value: float = field(metadata={"alias": "Value"})


@dataclass
class DeviceStatusMashumaro(DataClassDictMixin):
    error_code: int = field(metadata={"alias": "ErrorCode"})
    led_color: int = field(metadata={"alias": "LEDColor"})
    led_state: int = field(metadata={"alias": "LEDState"})
    mgmt_timer_remaining_time: int = field(metadata={"alias": "MgmtTimerRemainingTime"})
    state_to_reset: bool = field(metadata={"alias": "StateToReset"})
    status_code: int = field(metadata={"alias": "StatusCode"})


@dataclass
class CommonInverterDataMashumaro(DataClassDictMixin):
    day_energy: MeasurementMashumaro = field(metadata={"alias": "DAY_ENERGY"})
    device_status: DeviceStatusMashumaro = field(metadata={"alias": "DeviceStatus"})
    fac: MeasurementMashumaro = field(metadata={"alias": "FAC"})
    iac: MeasurementMashumaro = field(metadata={"alias": "IAC"})
    pac: MeasurementMashumaro = field(metadata={"alias": "PAC"})
    total_energy: MeasurementMashumaro = field(metadata={"alias": "TOTAL_ENERGY"})
    uac: MeasurementMashumaro = field(metadata={"alias": "UAC"})
    year_energy: MeasurementMashumaro = field(metadata={"alias": "YEAR_ENERGY"})
    idc: MeasurementMashumaro | None = field(default=None, metadata={"alias": "IDC"})
    udc: MeasurementMashumaro | None = field(default=None, metadata={"alias": "UDC"})


@dataclass
class BodyMashumaro(DataClassDictMixin):
    data: CommonInverterDataMashumaro = field(metadata={"alias": "Data"})


@dataclass
class RequestArgumentsMashumaro(DataClassDictMixin):
    data_collection: str = field(metadata={"alias": "DataCollection"})
    device_class: str = field(metadata={"alias": "DeviceClass"})
    device_id: str = field(metadata={"alias": "DeviceId"})
    scope: str = field(metadata={"alias": "Scope"})


@dataclass
class StatusMashumaro(DataClassDictMixin):
    code: int = field(metadata={"alias": "Code"})
    reason: str = field(metadata={"alias": "Reason"})
    user_message: str = field(metadata={"alias": "UserMessage"})


@dataclass
class HeadMashumaro(DataClassDictMixin):
    request_arguments: RequestArgumentsMashumaro = field(
        metadata={"alias": "RequestArguments"}
    )
    status: StatusMashumaro = field(metadata={"alias": "Status"})
    timestamp: str = field(metadata={"alias": "Timestamp"})


@dataclass
class InverterRealtimeDataMashumaro(DataClassDictMixin):
    body: BodyMashumaro = field(metadata={"alias": "Body"})
    head: HeadMashumaro = field(metadata={"alias": "Head"})


# --- mashumaro, api-named ---


@dataclass
class MeasurementApiMashumaro(DataClassDictMixin):
    Unit: str
    Value: float


@dataclass
class DeviceStatusApiMashumaro(DataClassDictMixin):
    ErrorCode: int
    LEDColor: int
    LEDState: int
    MgmtTimerRemainingTime: int
    StateToReset: bool
    StatusCode: int


@dataclass
class CommonInverterDataApiMashumaro(DataClassDictMixin):
    DAY_ENERGY: MeasurementApiMashumaro
    DeviceStatus: DeviceStatusApiMashumaro
    FAC: MeasurementApiMashumaro
    IAC: MeasurementApiMashumaro
    PAC: MeasurementApiMashumaro
    TOTAL_ENERGY: MeasurementApiMashumaro
    UAC: MeasurementApiMashumaro
    YEAR_ENERGY: MeasurementApiMashumaro
    IDC: MeasurementApiMashumaro | None = None
    UDC: MeasurementApiMashumaro | None = None


@dataclass
class BodyApiMashumaro(DataClassDictMixin):
    Data: CommonInverterDataApiMashumaro


@dataclass
class RequestArgumentsApiMashumaro(DataClassDictMixin):
    DataCollection: str
    DeviceClass: str
    DeviceId: str
    Scope: str


@dataclass
class StatusApiMashumaro(DataClassDictMixin):
    Code: int
    Reason: str
    UserMessage: str


@dataclass
class HeadApiMashumaro(DataClassDictMixin):
    RequestArguments: RequestArgumentsApiMashumaro
    Status: StatusApiMashumaro
    Timestamp: str


@dataclass
class InverterRealtimeDataApiMashumaro(DataClassDictMixin):
    Body: BodyApiMashumaro
    Head: HeadApiMashumaro


# --- the payload: a daytime response from a Symo inverter ---

PAYLOAD: dict[str, Any] = {
    "Body": {
        "Data": {
            "DAY_ENERGY": {"Unit": "Wh", "Value": 12345.0},
            "DeviceStatus": {
                "ErrorCode": 0,
                "LEDColor": 2,
                "LEDState": 0,
                "MgmtTimerRemainingTime": -1,
                "StateToReset": False,
                "StatusCode": 7,
            },
            "FAC": {"Unit": "Hz", "Value": 50.0},
            "IAC": {"Unit": "A", "Value": 1.21},
            "IDC": {"Unit": "A", "Value": 2.43},
            "PAC": {"Unit": "W", "Value": 300.0},
            "TOTAL_ENERGY": {"Unit": "Wh", "Value": 1234567.0},
            "UAC": {"Unit": "V", "Value": 230.1},
            "UDC": {"Unit": "V", "Value": 400.2},
            "YEAR_ENERGY": {"Unit": "Wh", "Value": 123456.0},
        }
    },
    "Head": {
        "RequestArguments": {
            "DataCollection": "CommonInverterData",
            "DeviceClass": "Inverter",
            "DeviceId": "1",
            "Scope": "Device",
        },
        "Status": {"Code": 0, "Reason": "", "UserMessage": ""},
        "Timestamp": "2026-10-19T12:00:00+02:00",
    },
}


def _night_payload() -> dict[str, Any]:
    """The same response with the DC side missing, as a sleeping inverter sends it."""
    data = dict(PAYLOAD["Body"]["Data"])
    del data["IDC"]
    del data["UDC"]
    return {**PAYLOAD, "Body": {"Data": data}}


def _malformed_payload() -> dict[str, Any]:
    """The daytime response with ``PAC.Value`` as a string instead of a number."""
    data = dict(PAYLOAD["Body"]["Data"])
    data["PAC"] = {"Unit": "W", "Value": "300"}
    return {**PAYLOAD, "Body": {"Data": data}}


PAYLOADS = [
    ("daytime", PAYLOAD),
    ("night, no DC", _night_payload()),
]

MODELS = [
    ("aliased", InverterRealtimeDataMashumaro, InverterRealtimeData),
    ("api-named", InverterRealtimeDataApiMashumaro, InverterRealtimeDataApi),
]

ITERATIONS = 20_000
REPEATS = 5


def _per_op_us(call: Any, payload: Any) -> float:
    """Return microseconds per construction, the best of ``REPEATS`` timed runs."""
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(ITERATIONS):
            call(payload)
        best = min(best, time.perf_counter() - start)
    return best / ITERATIONS * 1_000_000


def _pac_value(built: Any) -> float:
    """Read ``PAC.Value`` from either model's result."""
    data = getattr(built, "body", None) or built.Body
    data = getattr(data, "data", None) or data.Data
    pac = getattr(data, "pac", None) or data.PAC
    return getattr(pac, "value", None) or pac.Value


def measure() -> list[dict[str, Any]]:
    """Time every model and payload.

    Returns ``[{model, scenario, mashumaro, probatio, compiled, generated}]``;
    ``generated`` is whether ``.compile()`` produced generated code (``compiled`` is
    the interpreted engine again when it did not).
    """
    rows: list[dict[str, Any]] = []
    for model, mash_cls, cls in MODELS:
        mash = mash_cls.from_dict
        interp = probatio.DataclassSchema(cls, compile=False)
        compiled = probatio.DataclassSchema(cls).compile()

        for scenario, payload in PAYLOADS:
            # Warm each once before timing, and check the three agree on the result.
            expected = _pac_value(mash(payload))
            assert _pac_value(interp(payload)) == expected
            assert _pac_value(compiled(payload)) == expected

            rows.append(
                {
                    "model": model,
                    "scenario": scenario,
                    "mashumaro": _per_op_us(mash, payload),
                    "probatio": _per_op_us(interp, payload),
                    "compiled": _per_op_us(compiled, payload),
                    "generated": _is_compiled(compiled),
                }
            )
    return rows


def describe_rejection() -> list[tuple[str, str]]:
    """Report what each library does with ``PAC.Value`` as the string ``"300"``."""
    payload = _malformed_payload()
    outcomes: list[tuple[str, str]] = []

    built = InverterRealtimeDataMashumaro.from_dict(payload)
    outcomes.append(
        ("mashumaro", f"accepted, pac.value = {built.body.data.pac.value!r}")
    )

    for label, build in (
        ("probatio", probatio.DataclassSchema(InverterRealtimeData, compile=False)),
        ("compiled", probatio.DataclassSchema(InverterRealtimeDataApi).compile()),
    ):
        try:
            build(payload)
        except probatio.Invalid as err:
            outcomes.append((label, f"rejected: {err}"))
        else:
            outcomes.append((label, "accepted"))
    return outcomes


def main() -> None:
    """Run the Fronius response through mashumaro and both probatio engines."""
    header = (
        f"{'model':<10} {'scenario':<13} {'mashumaro':>11} {'probatio':>11} "
        f"{'compiled':>11} {'comp vs mash':>13}"
    )
    print(header)
    print("-" * len(header))
    for row in measure():
        mash_us, interp_us, comp_us = row["mashumaro"], row["probatio"], row["compiled"]
        if row["generated"]:
            compiled_cell = f"{comp_us:>9.3f}µs {comp_us / mash_us:>12.2f}x"
        else:
            compiled_cell = f"{'(interp)':>11} {interp_us / mash_us:>12.2f}x"
        print(
            f"{row['model']:<10} {row['scenario']:<13} {mash_us:>9.3f}µs "
            f"{interp_us:>9.3f}µs {compiled_cell}"
        )
    print(
        "\nTimes are microseconds per construction (lower is faster). 'comp vs mash' "
        "is how much slower probatio is than mashumaro, on the compiled engine where "
        "it generated. '(interp)' means .compile() left the schema interpreted: the "
        "code generator does not handle alias keys, so the aliased model never "
        "compiles. Where it did generate, only the top-level mapping is generated "
        "code; the nine nested dataclass mappings stay interpreted, which is why "
        "the gain is small. mashumaro only deserializes; probatio also validates "
        "every leaf's type, so it does more work for that price.\n"
    )

    print('With PAC.Value sent as the string "300":')
    for label, outcome in describe_rejection():
        print(f"  {label:<10} {outcome}")


if __name__ == "__main__":
    main()
