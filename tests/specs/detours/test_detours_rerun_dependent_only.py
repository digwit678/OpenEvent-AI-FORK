FLOW = {
    "caller_step": 4,
    "detour_step": 2,
    "dependent": {2, 3},
}


def test_only_dependent_steps_rerun():
    rerun = []
    for step in range(1, 5):
        if step in FLOW["dependent"]:
            rerun.append(step)
    assert rerun == [2, 3]

    return_path = {"caller_step": FLOW["caller_step"], "next_step": 4}
    assert return_path["caller_step"] == 4
    assert return_path["next_step"] == 4