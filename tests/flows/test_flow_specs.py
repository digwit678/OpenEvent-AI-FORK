from pathlib import Path

from tests.flows.run_yaml_flow import run_suite_file

SPEC_DIR = Path(__file__).resolve().parents[1] / "specs" / "flows"


def _spec(name: str) -> Path:
    return SPEC_DIR / name


def test_flow_general_qna():
    run_suite_file(_spec("test_A_general_qna_step1_to_step4.yaml"))


def test_flow_shortcut():
    run_suite_file(_spec("test_B_shortcut_step1_to_step4.yaml"))


def test_flow_normal():
    run_suite_file(_spec("test_C_normal_step1_to_step4.yaml"))


def test_flow_hybrid():
    run_suite_file(_spec("test_D_hybrid_step1_to_step4.yaml"))


def test_flow_past_date():
    run_suite_file(_spec("test_E_past_date_step1_to_step4.yaml"))


def test_flow_week2_december():
    run_suite_file(_spec("test_E_week2_december_workshop.yaml"))


def test_guard_no_rooms_before_date():
    run_suite_file(_spec("test_GUARD_no_rooms_before_date.yaml"))


def test_guard_no_billing_before_room():
    run_suite_file(_spec("test_GUARD_no_billing_before_room.yaml"))


def test_guard_coffee_only_no_lunch():
    run_suite_file(_spec("test_GUARD_coffee_only_no_lunch.yaml"))
