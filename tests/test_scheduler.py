import pytest

from projectplanner.scheduler import ScheduleError, schedule_activities
from projectplanner.schedule_view import gantt_order, map_scroll_position
from projectplanner.store import Activity


def test_schedule_respects_dependencies_and_resource_capacity():
    design = Activity(id=1, title="Design", duration_weeks=2)
    build = Activity(id=2, title="Build", duration_weeks=3, depends_on=[1])
    test = Activity(id=3, title="Test", duration_weeks=2)

    schedule = schedule_activities([design, build, test], available_people=2)
    timings = {item.activity.id: (item.start_week, item.end_week) for item in schedule.activities}

    assert timings[2][0] >= timings[1][1]
    assert schedule.makespan_weeks == 5
    assert max(schedule.resource_load) <= 2


def test_schedule_serializes_independent_work_when_only_one_person_is_available():
    schedule = schedule_activities(
        [Activity(id=1, duration_weeks=2), Activity(id=2, duration_weeks=3)],
        available_people=1,
    )

    assert schedule.makespan_weeks == 5
    assert schedule.resource_load == [1, 1, 1, 1, 1]


def test_schedule_allows_a_dependency_with_a_higher_activity_id():
    dependent = Activity(id=1, title="Dependent", duration_weeks=2, depends_on=[2])
    prerequisite = Activity(id=2, title="Prerequisite", duration_weeks=3)

    schedule = schedule_activities([dependent, prerequisite], available_people=2)
    timings = {item.activity.id: (item.start_week, item.end_week) for item in schedule.activities}

    assert timings[1][0] >= timings[2][1]


def test_schedule_rejects_fractional_week_duration():
    with pytest.raises(ScheduleError, match="whole-week"):
        schedule_activities([Activity(id=1, duration_weeks=1.5)], available_people=2)


def test_gantt_order_uses_start_week_before_activity_id():
    schedule = schedule_activities(
        [
            Activity(id=1, duration_weeks=2, depends_on=[2]),
            Activity(id=2, duration_weeks=3),
            Activity(id=3, duration_weeks=1),
        ],
        available_people=2,
    )

    ordered = gantt_order(schedule)
    assert [item.start_week for item in ordered] == sorted(item.start_week for item in ordered)
    assert ordered[-1].activity.id == 1


def test_scroll_mapping_keeps_bottom_endpoints_aligned():
    assert map_scroll_position(100, 0, 100, 0, 97) == 97
    assert map_scroll_position(0, 0, 100, 0, 97) == 0
