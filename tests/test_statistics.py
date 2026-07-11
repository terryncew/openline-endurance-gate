from openline_endurance_gate.statistics import exact_sign_flip_p, paired_effect


def test_sign_flip_uses_all_powered_pairs_without_truncation():
    values = [1.0] * 40 + [-1.0] * 40
    assert exact_sign_flip_p(values) == 1.0
    changed_tail = [1.0] * 40 + [-1.0] * 20 + [1.0] * 20
    assert exact_sign_flip_p(changed_tail) < 1.0


def test_paired_effect_reports_full_count_and_interval():
    result = paired_effect(range(-10, 11), resamples=200, seed_tag="test")
    assert result["paired_difference_count"] == 21
    assert len(result["median_confidence_interval"]) == 2
