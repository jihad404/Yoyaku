from datetime import date, datetime, timedelta

from manager.evaluate import evaluate, initial_state

NOW = datetime(2026, 10, 6, 12, 0)
D = lambda day: date(2026, 10, day)  # noqa: E731


def later(hours):
    return NOW + timedelta(hours=hours)


# --- earliest --------------------------------------------------------------

def test_earliest_reports_earlier_day():
    state = initial_state("earliest", None, [D(14), D(15)], NOW)
    d = evaluate("earliest", None, state, [D(9), D(14)], later(1))
    assert d.kind == "earlier" and d.days == [D(9)] and d.previous == D(14)
    assert d.state["earliest"] == "2026-10-09"


def test_earliest_silent_when_not_earlier():
    state = initial_state("earliest", None, [D(14)], NOW)
    assert evaluate("earliest", None, state, [D(14), D(20)], later(1)).kind is None
    d = evaluate("earliest", None, state, [D(20)], later(1))
    assert d.kind is None and d.state["earliest"] == "2026-10-20"


def test_earliest_reports_after_earliest_vanished_and_returns():
    state = initial_state("earliest", None, [D(14)], NOW)
    state = evaluate("earliest", None, state, [D(20)], later(1)).state
    d = evaluate("earliest", None, state, [D(15), D(20)], later(3))
    assert d.kind == "earlier" and d.days == [D(15)]


def test_earliest_reports_when_appointments_appear_after_none():
    state = initial_state("earliest", None, [], NOW)
    d = evaluate("earliest", None, state, [D(22)], later(1))
    assert d.kind == "earlier" and d.days == [D(22)] and d.previous is None


def test_earliest_does_not_repeat_same_day_within_two_hours():
    state = initial_state("earliest", None, [D(14)], NOW)
    state = evaluate("earliest", None, state, [D(9), D(14)], later(0.1)).state   # gemeldet
    state = evaluate("earliest", None, state, [D(14)], later(0.2)).state          # 9. weg
    assert evaluate("earliest", None, state, [D(9), D(14)], later(0.3)).kind is None
    assert evaluate("earliest", None, state, [D(9), D(14)], later(2.5)).kind == "earlier"


def test_earliest_ignores_past_days():
    state = initial_state("earliest", None, [D(14)], NOW)
    assert evaluate("earliest", None, state, [D(1), D(14)], later(1)).kind is None


def test_uninitialized_state_reports_current_earliest():
    d = evaluate("earliest", None, {}, [D(14), D(15)], NOW)
    assert d.kind == "earlier" and d.days == [D(14)]


# --- until -----------------------------------------------------------------

def test_until_reports_only_new_days_before_deadline():
    state = initial_state("until", D(20), [D(14)], NOW)
    d = evaluate("until", D(20), state, [D(10), D(14), D(18), D(25)], later(1))
    assert d.kind == "new_days" and d.days == [D(10), D(18)]


def test_until_silent_without_new_days_and_for_removed():
    state = initial_state("until", D(20), [D(14), D(15)], NOW)
    assert evaluate("until", D(20), state, [D(14)], later(1)).kind is None
    assert evaluate("until", D(20), state, [D(25)], later(1)).kind is None


def test_until_expires_after_deadline():
    state = initial_state("until", D(7), [], NOW)
    d = evaluate("until", D(7), state, [], datetime(2026, 10, 8, 0, 1))
    assert d.kind == "expired" and d.end


def test_until_deadline_day_itself_counts():
    state = initial_state("until", D(20), [], NOW)
    assert evaluate("until", D(20), state, [D(20)], later(1)).days == [D(20)]


# --- day -------------------------------------------------------------------

def test_day_available_then_gone():
    state = initial_state("day", D(14), [D(15)], NOW)
    d = evaluate("day", D(14), state, [D(14), D(15)], later(1))
    assert d.kind == "day_available" and d.days == [D(14)]
    d = evaluate("day", D(14), d.state, [D(15)], later(2))
    assert d.kind == "day_gone"


def test_day_gone_only_if_previously_available():
    state = initial_state("day", D(14), [], NOW)
    assert evaluate("day", D(14), state, [D(15)], later(1)).kind is None


def test_day_flapping_rate_limited():
    state = initial_state("day", D(14), [], NOW)
    state = evaluate("day", D(14), state, [D(14)], later(0.1)).state   # gemeldet
    state = evaluate("day", D(14), state, [], later(0.2)).state         # weg (gemeldet)
    assert evaluate("day", D(14), state, [D(14)], later(0.3)).kind is None


def test_day_expires():
    state = initial_state("day", D(6), [D(6)], NOW)
    d = evaluate("day", D(6), state, [], datetime(2026, 10, 7, 8, 0))
    assert d.kind == "expired" and d.end


def test_initial_state_marks_shown_days_as_notified():
    state = initial_state("until", D(20), [D(14)], NOW)
    assert "2026-10-14" in state["notified"]
    assert initial_state("day", D(14), [D(14)], NOW)["day_available"] is True


def test_old_notified_entries_are_pruned():
    state = initial_state("until", D(30), [D(7)], NOW)
    d = evaluate("until", D(30), state, [D(9)], datetime(2026, 10, 8, 12))
    assert "2026-10-07" not in d.state["notified"]
