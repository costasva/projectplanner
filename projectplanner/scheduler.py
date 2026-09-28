"""Whole-week, resource-constrained activity scheduling with OR-Tools CP-SAT."""
from __future__ import annotations

from dataclasses import dataclass

from ortools.sat.python import cp_model

from .store import Activity


class ScheduleError(ValueError):
    """The activities cannot be represented by the whole-week scheduler."""


@dataclass(frozen=True)
class ScheduledActivity:
    activity: Activity
    start_week: int
    end_week: int


@dataclass(frozen=True)
class ProjectSchedule:
    activities: list[ScheduledActivity]
    makespan_weeks: int
    resource_load: list[int]


def schedule_activities(activities: list[Activity], available_people: int) -> ProjectSchedule:
    """Minimize project finish week without exceeding the available people."""
    if available_people < 1:
        raise ScheduleError("Available people must be at least 1.")
    if not activities:
        return ProjectSchedule([], 0, [])

    durations: dict[int, int] = {}
    known_ids = {activity.id for activity in activities}
    for activity in activities:
        if activity.id is None:
            raise ScheduleError("Every activity must be saved before it can be scheduled.")
        if activity.duration_weeks < 0 or not float(activity.duration_weeks).is_integer():
            raise ScheduleError(f"Activity {activity.id} must have a whole-week duration.")
        durations[activity.id] = int(activity.duration_weeks)
        unknown = set(activity.depends_on) - known_ids
        if unknown:
            raise ScheduleError(f"Activity {activity.id} depends on an unknown activity.")

    horizon = max(1, sum(durations.values()))
    model = cp_model.CpModel()
    starts: dict[int, cp_model.IntVar] = {}
    ends: dict[int, cp_model.IntVar] = {}
    intervals: list[cp_model.IntervalVar] = []
    for activity in activities:
        activity_id = activity.id
        starts[activity_id] = model.NewIntVar(0, horizon, f"start_{activity_id}")
        ends[activity_id] = model.NewIntVar(0, horizon, f"end_{activity_id}")
        intervals.append(
            model.NewIntervalVar(starts[activity_id], durations[activity_id], ends[activity_id], f"task_{activity_id}")
        )
    for activity in activities:
        activity_id = activity.id
        for prerequisite in activity.depends_on:
            model.Add(starts[activity_id] >= ends[prerequisite])

    model.AddCumulative(intervals, [1] * len(intervals), available_people)
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    # Preserve minimum makespan while preferring an earlier, stable placement of tasks.
    model.Minimize(makespan * (horizon * len(activities) + 1) + sum(starts.values()))

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise ScheduleError("No schedule satisfies the dependency and resource constraints.")

    scheduled = [
        ScheduledActivity(activity, solver.Value(starts[activity.id]), solver.Value(ends[activity.id]))
        for activity in activities
    ]
    finish_week = solver.Value(makespan)
    resource_load = [
        sum(item.start_week <= week < item.end_week for item in scheduled)
        for week in range(finish_week)
    ]
    return ProjectSchedule(scheduled, finish_week, resource_load)
