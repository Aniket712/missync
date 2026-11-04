from missync.analysis import severity as s


def test_escalation_caps_at_critical():
    assert s.escalate("high", True) == "critical"
    assert s.escalate("critical", True) == "critical"
    assert s.escalate("medium", False) == "medium"
    assert s.escalate("info", True) == "info"


def test_rules():
    assert s.severity_for_type_change("widening") == "low"
    assert s.severity_for_type_change("narrowing") == "high"
    assert s.severity_for_row_loss(100, 85) == "high"
    assert s.severity_for_row_loss(100, 98) == "medium"
    assert s.severity_for_row_loss(100, 100) == "info"
    assert s.severity_for_missing_records(5, 100) == "high"
    assert s.severity_for_missing_records(1, 100) == "medium"
    assert s.severity_for_null_increase(0.25) == "high"
    assert s.severity_for_null_increase(0.06) == "medium"
    assert s.severity_for_null_increase(0.005) == "low"
    assert s.severity_for_null_increase(0.0001) == "info"
    assert s.severity_for_metric_drift(0.5, 1.0) == "info"
    assert s.severity_for_metric_drift(3, 1.0) == "medium"
    assert s.severity_for_metric_drift(-12, 1.0) == "high"
    assert s.worst(["low", "high", "medium"]) == "high"
