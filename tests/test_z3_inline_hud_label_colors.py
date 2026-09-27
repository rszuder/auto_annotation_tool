from types import SimpleNamespace

from auto_annotation_tool.gui import z3_inline_hud


class _Font:
    def measure(self, text):
        return len(str(text)) * 7

    def metrics(self, _key):
        return 16


def test_top_hud_uses_one_label_color_and_independent_value_colors(monkeypatch):
    host = SimpleNamespace(
        frame=object(),
        app=SimpleNamespace(
            palette={
                "muted": "#LABEL",
                "fg": "#FG",
                "accent_alt": "#GT",
                "warning": "#WARN",
                "success": "#OK",
                "error": "#ERR",
            }
        ),
        _preview_inline_hud_fonts=(_Font(), _Font()),
        _get_current_preview_list_index=lambda: 0,
        _listbox_pid_by_index=["p1"],
        _get_preview_ground_truth_text=lambda _data=None: "",
    )

    monkeypatch.setattr(
        z3_inline_hud,
        "resolve_inline_hud_plate_status",
        lambda _host, _data: ("DO KONTROLI", "#WARN"),
    )

    status_layout = {
        "neutral_badges": [
            {"text": "Odczyt: [ABC123]", "outline": "#READ"},
            {"text": "Ramki: 6", "outline": "#BOX"},
            {"text": "Układ: 1R", "outline": "#LAYOUT"},
        ],
        "badges": [
            {"text": "Decyzja: DO KONTROLI", "outline": "#WARN"},
        ],
    }

    plan = z3_inline_hud.plan_inline_hud(
        host,
        1200,
        {
            "source_image": "plate.jpg",
            "ground_truth_text": "",
            "ground_truth_source": "",
            "review_state": {"status": "in_progress"},
        },
        status_layout,
    )

    label_lines = [
        row for row in plan["lines"]
        if "preview_inline_hud_label" in row[5]
    ]
    value_lines = [
        row for row in plan["lines"]
        if "preview_inline_hud_value" in row[5]
    ]

    assert [row[0] for row in label_lines] == [
        "Tablica:",
        "GT z Z2:",
        "Odczyt:",
        "Ramki:",
        "Układ:",
        "Decyzja:",
    ]
    assert {row[4] for row in label_lines} == {"#LABEL"}

    values = {row[0]: row[4] for row in value_lines}
    assert values["1/1"] == "#FG"
    assert values["brak"] == "#GT"
    assert values["[ABC123]"] == "#READ"
    assert values["6"] == "#BOX"
    assert values["1R"] == "#LAYOUT"
    assert values["DO KONTROLI"] == "#WARN"
