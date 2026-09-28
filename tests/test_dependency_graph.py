from projectplanner.dependency_graph import build_dot
from projectplanner.store import Activity


def test_build_dot_separates_nodes_and_draws_prerequisite_arrows():
    source = build_dot(
        [
            Activity(id=1, title="Prepare site"),
            Activity(id=2, title="Build structure", depends_on=[1]),
        ],
        selected_id=2,
    )

    assert "rankdir=LR" in source
    assert 'activity_1 [label="1: Prepare site", fillcolor="#fff3cd"]' in source
    assert 'activity_2 [label="2: Build structure", fillcolor="#d9ead3"]' in source
    assert "activity_1 -> activity_2;" in source
