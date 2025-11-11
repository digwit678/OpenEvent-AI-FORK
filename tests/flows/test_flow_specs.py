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
