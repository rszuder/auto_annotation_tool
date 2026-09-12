import unittest

from auto_annotation_tool.gui import z4_tab_shell
from auto_annotation_tool.gui.tab_training import TrainingTab


class TrainingTracksTabDelegationTests(unittest.TestCase):
    def test_tracks_placeholder_delegates_to_tab_shell(self):
        sentinel = object()
        original = z4_tab_shell._build_tracks_tab_placeholder
        try:
            z4_tab_shell._build_tracks_tab_placeholder = (
                lambda self, *args, **kwargs: sentinel
            )
            result = TrainingTab._build_tracks_tab_placeholder(
                object()
            )
        finally:
            z4_tab_shell._build_tracks_tab_placeholder = original

        self.assertIs(result, sentinel)

    def test_tracks_lazy_builder_delegates_to_tab_shell(self):
        sentinel = object()
        original = z4_tab_shell._ensure_step4_tracks_tab_built
        try:
            z4_tab_shell._ensure_step4_tracks_tab_built = (
                lambda self, *args, **kwargs: sentinel
            )
            result = TrainingTab._ensure_step4_tracks_tab_built(
                object()
            )
        finally:
            z4_tab_shell._ensure_step4_tracks_tab_built = original

        self.assertIs(result, sentinel)


if __name__ == "__main__":
    unittest.main()
