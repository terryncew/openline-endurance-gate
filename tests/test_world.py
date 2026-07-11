from openline_endurance_gate.sim import generate_perturbations, schedule_events
from openline_endurance_gate.world import INITIAL_REQUIREMENTS, invariant_results, solve


def test_canonical_solver_satisfies_all_twelve_invariants():
    config = solve(dict(INITIAL_REQUIREMENTS))
    results = invariant_results(config)
    assert len(results) == 12
    assert all(result.passed for result in results)


def test_schedule_order_preserves_final_ground_truth():
    events = generate_perturbations(101, {"low": 7, "medium": 6, "high": 7})
    finals = []
    for schedule in ("low_to_high", "high_to_low", "alternating", "randomized"):
        requirements = dict(INITIAL_REQUIREMENTS)
        ordered = schedule_events(events, schedule, 101)
        assert sorted(event.event_id for event in ordered) == sorted(event.event_id for event in events)
        for event in ordered:
            requirements[event.target] += event.delta
        finals.append((requirements, solve(requirements)))
    assert all(item == finals[0] for item in finals[1:])
