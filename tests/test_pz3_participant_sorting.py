import unittest
from types import SimpleNamespace

from auto_annotation_tool.gui.pz3_participant_audit import (
    participant_model_sort_key,
)


def model(
    model_id,
    *,
    family="YOLO26",
    scale="n",
    run_id="RUN-1",
    dataset_id="DS-1",
    provenance_status="complete",
):
    return SimpleNamespace(
        model_id=model_id,
        family=family,
        scale=scale,
        run_id=run_id,
        dataset_id=dataset_id,
        provenance_status=provenance_status,
    )


class ParticipantModelSortingTests(unittest.TestCase):
    def test_scale_uses_yolo_size_order(self):
        items = [
            model("M-X", scale="x"),
            model("M-N", scale="n"),
            model("M-M", scale="m"),
            model("M-S", scale="s"),
        ]
        result = sorted(
            items,
            key=lambda item: participant_model_sort_key(
                item, "scale"
            ),
        )
        self.assertEqual(
            [item.scale for item in result],
            ["n", "s", "m", "x"],
        )

    def test_training_history_orders_best_known_state_first(self):
        items = [
            model("M-U", provenance_status="legacy_unknown"),
            model("M-P", provenance_status="partial"),
            model("M-K", provenance_status="known"),
            model("M-C", provenance_status="complete"),
        ]
        result = sorted(
            items,
            key=lambda item: participant_model_sort_key(
                item, "prov"
            ),
        )
        self.assertEqual(
            [item.provenance_status for item in result],
            ["complete", "known", "partial", "legacy_unknown"],
        )

    def test_participating_models_sort_first(self):
        items = [
            model("MODEL-2"),
            model("MODEL-1"),
            model("MODEL-3"),
        ]
        result = sorted(
            items,
            key=lambda item: participant_model_sort_key(
                item,
                "sel",
                {"MODEL-3", "MODEL-1"},
            ),
        )
        self.assertEqual(
            [item.model_id for item in result],
            ["MODEL-1", "MODEL-3", "MODEL-2"],
        )

    def test_model_id_uses_natural_numeric_order(self):
        items = [
            model("MODEL-10"),
            model("MODEL-2"),
            model("MODEL-1"),
        ]
        result = sorted(
            items,
            key=lambda item: participant_model_sort_key(
                item, "model"
            ),
        )
        self.assertEqual(
            [item.model_id for item in result],
            ["MODEL-1", "MODEL-2", "MODEL-10"],
        )

    def test_participant_sort_by_dataset(self):
        items = [model("M10", dataset_id="DS-10"), model("M2", dataset_id="DS-2"),
                 model("M0", dataset_id=""), model("M1", dataset_id="DS-1")]
        result = sorted(items, key=lambda item: participant_model_sort_key(item, "dataset"))
        self.assertEqual([item.dataset_id for item in result], ["DS-1", "DS-2", "DS-10", ""])


if __name__ == "__main__":
    unittest.main()
