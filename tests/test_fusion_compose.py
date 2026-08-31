"""compose_mode fusion/cover helpers."""

from workflow.publish import _assignment_compose_mode, _split_fusion_assignments


def test_compose_from_layout():
    assert _assignment_compose_mode({"scene_layout": "glass_card"}) == "fusion"
    assert _assignment_compose_mode({"scene_layout": "plain_text"}) == "fusion"
    assert _assignment_compose_mode({"compose_mode": "cover", "scene_layout": "kinetic"}) == "cover"
    assert _assignment_compose_mode({"auto_hyperframe": True, "scene_layout": "kinetic"}) == "cover"


def test_split_fusion():
    opaque, fusion = _split_fusion_assignments(
        [
            {"media_path": "a.mp4", "compose_mode": "cover"},
            {"media_path": "b.mp4", "compose_mode": "fusion"},
            {"media_path": "c.mp4", "scene_layout": "plain_text"},
        ]
    )
    assert len(opaque) == 1
    assert len(fusion) == 2
