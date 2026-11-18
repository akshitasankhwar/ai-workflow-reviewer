"""Code is compiled from its AST, never executed; unsupported constructs are reported."""
from reviewer.contracts.ir import ERROR_ROUTE, NO_ROUTE
from reviewer.ingest.code_compiler import compile_code
from reviewer.semantics.evaluator import decide

from tests.conftest import BASE_BUNDLE

BASE_CODE = (BASE_BUNDLE / "code" / "router.py").read_text(encoding="utf-8")

SAMPLES = [
    {"priority": "urgent", "wait_time": 0},
    {"category": "billing", "priority": "urgent", "wait_time": 0},
    {"category": "billing", "priority": "low", "wait_time": 25},
    {"category": "billing", "priority": "low", "wait_time": 24},
]
EXPECTED = ["manual_review", "priority_queue", "escalation", "normal_queue"]


def test_base_code_compiles_and_routes(fields):
    cc = compile_code(BASE_CODE, "c1", fields, entrypoint="route")
    assert cc.decision_list is not None
    assert not [i for i in cc.issues if i.blocking]
    assert [decide(cc.decision_list, t)[0] for t in SAMPLES] == EXPECTED


def test_code_is_not_executed(fields, tmp_path):
    marker = tmp_path / "ran"
    src = f"open({str(marker)!r}, 'w')\n" + BASE_CODE
    compile_code(src, "c1", fields, entrypoint="route")
    assert not marker.exists()


def test_unsupported_construct_is_reported(fields):
    src = "def route(ticket):\n    for x in ticket:\n        return 'a'\n    return 'b'\n"
    cc = compile_code(src, "c1", fields, entrypoint="route")
    assert cc.issues or any(c.status != "supported" for c in cc.coverage)


def test_index_access_on_missing_field_is_error(fields):
    src = ("def route(ticket):\n"
           "    if ticket['priority'] == 'urgent':\n"
           "        return 'priority_queue'  # ref: R2\n"
           "    return 'normal_queue'  # ref: R9\n")
    cc = compile_code(src, "c1", fields, entrypoint="route")
    assert decide(cc.decision_list, {})[0] == ERROR_ROUTE
    assert decide(cc.decision_list, {"priority": "low"})[0] == "normal_queue"


def test_falling_off_the_end_is_no_route(fields):
    src = ("def route(ticket):\n"
           "    if ticket.get('priority') == 'urgent':\n"
           "        return 'priority_queue'  # ref: R2\n")
    cc = compile_code(src, "c1", fields, entrypoint="route")
    assert decide(cc.decision_list, {"priority": "low"})[0] == NO_ROUTE


def test_missing_entrypoint_is_reported(fields):
    cc = compile_code(BASE_CODE, "c1", fields, entrypoint="dispatch")
    assert cc.decision_list is None and cc.issues
