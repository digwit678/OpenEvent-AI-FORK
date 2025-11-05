import { computeStepProgress } from '../utils';

describe('Step3 counters', () => {
  it('reflect backend room_selected and requirements_match flags', () => {
    const state = {
      step_counters: {
        Step3_Room: {
          met: 2,
          total: 3,
        },
      },
    };

    const summary = {
      date: { confirmed: true },
      room_selected: false,
      requirements_match: true,
    };

    const result = computeStepProgress({ state, summary });
    const step3 = result.Step3_Room;
    expect(step3).toBeTruthy();
    expect(step3?.breakdown[0].met).toBe(true);
    expect(step3?.breakdown[1].met).toBe(false);
    expect(step3?.breakdown[2].met).toBe(true);
    expect(step3?.completed).toBe(2);
    expect(step3?.total).toBe(3);

    const updated = computeStepProgress({
      state,
      summary: { ...summary, room_selected: true },
    });
    const updatedStep3 = updated.Step3_Room;
    expect(updatedStep3?.breakdown[1].met).toBe(true);
  });
});
