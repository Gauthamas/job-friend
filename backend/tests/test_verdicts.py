from app.verdicts import derive_requirement_verdict, effective_verdict


def row(model_verdict=None, user_verdict=None):
    return {"model_verdict": model_verdict, "user_verdict": user_verdict}


def test_effective_verdict_prefers_user_over_model():
    assert effective_verdict(row(model_verdict="weak", user_verdict="match")) == "match"


def test_effective_verdict_falls_back_to_model_when_no_user_verdict():
    assert effective_verdict(row(model_verdict="weak", user_verdict=None)) == "weak"


def test_effective_verdict_none_when_both_unset():
    assert effective_verdict(row()) is None


def test_derive_requirement_verdict_match_wins_over_weak():
    assert derive_requirement_verdict([row(model_verdict="weak"), row(model_verdict="match")]) == "match"


def test_derive_requirement_verdict_weak_when_no_match():
    assert derive_requirement_verdict([row(model_verdict="none"), row(model_verdict="weak")]) == "weak"


def test_derive_requirement_verdict_gap_when_no_match_or_weak():
    assert derive_requirement_verdict([row(model_verdict="none"), row(model_verdict="none")]) == "gap"


def test_derive_requirement_verdict_gap_when_no_judgments_at_all():
    assert derive_requirement_verdict([]) == "gap"


def test_derive_requirement_verdict_user_correction_can_upgrade_to_match():
    assert derive_requirement_verdict([row(model_verdict="none", user_verdict="match")]) == "match"
