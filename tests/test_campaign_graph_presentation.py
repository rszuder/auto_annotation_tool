"""Regression tests for fixed controls and presentation-only workflow focus."""

import ast
from pathlib import Path
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock

from auto_annotation_tool.campaign_transition_graph import CAMPAIGN_TRANSITION_GRAPH as GRAPH
from auto_annotation_tool.gui.app_theme_definitions import get_theme_palette, THEME_DEFINITIONS
from auto_annotation_tool.gui.campaign_graph_presentation import (
    CanvasWorkflowFocus, GraphToolbar, WorkflowFocus, resolve_workflow_focus,
)


def scope(edge):
    transition = GRAPH.get_edge(edge)
    return WorkflowFocus(frozenset({edge}), frozenset({transition.source, transition.target}))


class WorkflowFocusTests(unittest.TestCase):
    def test_all_routes_and_stages(self):
        for path, step, edge in (
            ("plate_training", 1, "e1_to_e2"),
            ("char_from_images", 1, "e1_to_e2"),
            ("char_from_ready_plates", 1, "e1_to_e3"),
            ("plate_training", 2, "e2_to_e4"),
            ("char_from_images", 2, "e2_to_e3"),
            ("char_from_images", 3, "e3_to_e4"),
            ("char_from_ready_plates", 3, "e3_to_e4"),
            ("plate_training", 4, "e4t_to_e1"),
            ("char_from_images", 4, "e4z_to_e1"),
            ("char_from_ready_plates", 4, "e4z_to_e1"),
        ):
            with self.subTest(path=path, step=step):
                self.assertEqual(resolve_workflow_focus(GRAPH, current_step=step, selected_path=path), scope(edge))

    def test_before_choice_both_entry_gates_remain_visible(self):
        self.assertEqual(resolve_workflow_focus(GRAPH, current_step=1), WorkflowFocus(
            frozenset({"e1_to_e2", "e1_to_e3"}), frozenset({"E1", "E2", "E3"}),
        ))

    def test_explicit_entry_choice(self):
        self.assertEqual(resolve_workflow_focus(GRAPH, current_step=1, selected_edge="e1_to_e3"), scope("e1_to_e3"))

    def test_old_iteration_selection_does_not_focus_old_stage(self):
        self.assertEqual(resolve_workflow_focus(GRAPH, current_step=1,
            selected_edge="e4z_to_e1", selected_path="plate_training"), scope("e1_to_e2"))

    def test_stale_selection_on_another_route(self):
        self.assertEqual(resolve_workflow_focus(GRAPH, current_step=4,
            selected_edge="e4z_to_e1", selected_path="plate_training"), scope("e4t_to_e1"))

    def test_committed_entry_excludes_other_gate(self):
        for active, other in (("e1_to_e2", "e1_to_e3"), ("e1_to_e3", "e1_to_e2")):
            self.assertEqual(resolve_workflow_focus(GRAPH, current_step=1,
                selected_edge=other, operable_edges={active}), scope(active))

    def test_no_available_gate_keeps_current_stage(self):
        self.assertEqual(resolve_workflow_focus(GRAPH, current_step=3, operable_edges=set()),
                         WorkflowFocus(frozenset(), frozenset({"E3"})))


class GraphPresentationTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One interpreter, held on the main thread for the entire test class.
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk unavailable: {exc}")
        cls.root.withdraw()
        source = Path(__file__).resolve().parents[1] / "auto_annotation_tool/gui/campaign_dashboard_ui.py"
        module = ast.parse(source.read_text(encoding="utf-8-sig"))
        cls.renderer = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                            and node.name == "_render_step1_route_actions")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.palette = get_theme_palette()
        self.canvas = tk.Canvas(self.root, width=900, height=700, bg=self.palette["campaign_graph_bg"])
        self.style = CanvasWorkflowFocus(self.canvas, self.palette)
        self.commands = {name: Mock() for name in ("zoom_in", "zoom_out", "reset", "history", "guide")}
        self.toolbar = GraphToolbar(self.canvas, self.palette, self.commands)
        self.toolbar._resize(SimpleNamespace(width=900))
        self.toolbar.sync(1.0, "T04 | E2 -> E4T")

    def tearDown(self):
        self.canvas.destroy()
        self.root.update_idletasks()

    def callback_namespace(self, **extra):
        """Run the actual outer renderer callbacks on a small real graph."""
        namespace = {
            "tk": tk, "canvas": self.canvas, "graph_toolbar": self.toolbar,
            "workflow_focus_style": self.style, "_workflow_focus_scope": lambda: scope("e2_to_e4"),
            "_sync_graph_toolbar": lambda: self.toolbar.sync(1.0, "T04 | E2 -> E4T"),
            "_graph_zoom": lambda: 1.4, "_graph_pan": lambda: (40.0, -20.0),
            "graph_render_helpers": {}, "_raise_graph_interactive_layers": Mock(),
            "_scale_graph_preview_text_items": Mock(),
        }
        wanted = {"_apply_graph_view", "_redraw_graph_fixed_overlay", "_preview_graph_zoom_transform",
                  "_raise_graph_overlay_layers", "_flush_graph_pan_move", "_request_graph_redraw"}
        body = [node for node in self.renderer.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        self.assertEqual(len(body), len(wanted))
        exec(compile(ast.Module(body=body, type_ignores=[]), "graph_callbacks", "exec"), namespace)
        namespace.update(extra)
        return namespace

    def test_toolbar_survives_world_zoom_pan_and_frame_deletion(self):
        node = self.canvas.create_rectangle(100, 100, 180, 170, tags=("node-group:E2",))
        fixed = self.canvas.create_text(10, 680, text="legend", tags=("graph_overlay_fixed",))
        before = self.toolbar.coords("button:reset"), self.toolbar.place_info(), self.toolbar.find_all()
        fixed_coords = self.canvas.coords(fixed)
        ns = self.callback_namespace()
        for _ in range(15):
            ns["_apply_graph_view"](900, 700)
            ns["_preview_graph_zoom_transform"](450, 350, 1.035)
            ns["_raise_graph_overlay_layers"]()
        self.assertNotEqual(self.canvas.coords(node), [100, 100, 180, 170])
        self.assertEqual(self.canvas.coords(fixed), fixed_coords)
        self.assertEqual((self.toolbar.coords("button:reset"), self.toolbar.place_info(), self.toolbar.find_all()), before)
        self.canvas.addtag_withtag("graph_redraw_previous_frame", "all")
        self.canvas.delete("graph_redraw_previous_frame")
        self.canvas.delete("all")
        self.assertEqual(self.toolbar.find_all(), before[2])
        self.assertEqual(self.toolbar.winfo_manager(), "place")
        self.toolbar.invoke("history")
        self.commands["history"].assert_called_once()

    def test_partial_overlay_redraw_uses_registered_legend(self):
        old = self.canvas.create_text(10, 680, text="old", tags=("graph_overlay_fixed",))
        def legend():
            self.canvas.create_text(10, 680, text="new", tags=("graph_overlay_fixed",))
        ns = self.callback_namespace(graph_render_helpers={"draw_fixed_legend": legend})
        ns["_redraw_graph_fixed_overlay"]()
        self.assertNotIn(old, self.canvas.find_all())
        items = self.canvas.find_withtag("graph_overlay_fixed")
        self.assertEqual(len(items), 1)
        self.assertEqual(self.canvas.itemcget(items[0], "text"), "new")
        ns["_raise_graph_interactive_layers"].assert_called_once()

    def test_pan_only_moves_world_items(self):
        node = self.canvas.create_rectangle(100, 100, 180, 170, tags=("node-group:E2",))
        legend = self.canvas.create_text(10, 680, text="legend", tags=("graph_overlay_fixed",))
        ns = self.callback_namespace(graph_pan_state={"active": True, "start_x": 100, "start_y": 80,
            "pending_x": 120, "pending_y": 110, "orig_x": 40, "orig_y": -20},
            gate_drag_state={}, node_drag_state={}, graph_view={})
        ns["_flush_graph_pan_move"]()
        self.assertEqual(self.canvas.coords(node), [120, 130, 200, 200])
        self.assertEqual(self.canvas.coords(legend), [10, 680])

    def test_fading_preserves_geometry_bindings_and_visibility(self):
        for theme in THEME_DEFINITIONS:
            with self.subTest(theme=theme):
                self.canvas.delete("all")
                palette = get_theme_palette(theme)
                style = CanvasWorkflowFocus(self.canvas, palette)
                inactive = self.canvas.create_rectangle(20, 30, 200, 90, fill=palette["campaign_gate_surface"],
                    outline=palette["campaign_card_text"], tags=("gate-group:e3_to_e4",))
                label = self.canvas.create_text(40, 50, text="T05", fill=palette["campaign_card_text"],
                    font=("Segoe UI", 12), tags=("gate-group:e3_to_e4",))
                active = self.canvas.create_rectangle(300, 40, 400, 80, fill=palette["campaign_gate_surface"],
                    tags=("gate-group:e2_to_e4",))
                self.canvas.tag_bind("gate-group:e3_to_e4", "<Button-1>", lambda _e: None)
                before = (self.canvas.coords(inactive), self.canvas.itemcget(label, "font"),
                          self.canvas.tag_bind("gate-group:e3_to_e4", "<Button-1>"))
                style.apply(scope("e2_to_e4"))
                dim = self.canvas.itemcget(inactive, "fill")
                self.assertNotEqual(dim, palette["campaign_gate_surface"])
                self.assertEqual(self.canvas.itemcget(active, "fill"), palette["campaign_gate_surface"])
                for _ in range(5):
                    style.apply(scope("e2_to_e4"), refresh_links=True)
                self.assertEqual(self.canvas.itemcget(inactive, "fill"), dim)
                self.assertEqual(self.canvas.itemcget(inactive, "state"), "")
                self.assertEqual((self.canvas.coords(inactive), self.canvas.itemcget(label, "font"),
                    self.canvas.tag_bind("gate-group:e3_to_e4", "<Button-1>")), before)
                style.apply(scope("e3_to_e4"))
                self.assertEqual(self.canvas.itemcget(inactive, "fill"), palette["campaign_gate_surface"])
                self.assertEqual(self.canvas.itemcget(label, "fill"), palette["campaign_card_text"])

    def test_partial_link_redraw_and_new_elements_are_dimmed(self):
        color = self.palette["campaign_edge"]
        line = self.canvas.create_line(10, 50, 500, 50, fill=color, tags=("edge-line:e3_to_e4", "edge_line"))
        self.style.apply(scope("e2_to_e4"))
        expected = self.canvas.itemcget(line, "fill")
        self.canvas.itemconfigure(line, fill=color)
        arrow = self.canvas.create_polygon(490, 40, 500, 50, 490, 60, fill=color,
            tags=("graph_edge_arrow:e3_to_e4", "graph_edge_arrow"))
        self.style.apply(scope("e2_to_e4"), refresh_links=True)
        self.assertEqual(self.canvas.itemcget(line, "fill"), expected)
        self.assertEqual(self.canvas.itemcget(arrow, "fill"), expected)
        self.style.apply(scope("e3_to_e4"))
        self.assertEqual(self.canvas.itemcget(line, "fill"), color)

    def test_return_edge_is_bright_only_for_training_transition(self):
        color = self.palette["campaign_edge"]
        trunk = self.canvas.create_line(10, 50, 500, 50, fill=color, tags=("graph_return_trunk",))
        self.style.apply(scope("e3_to_e4"))
        self.assertNotEqual(self.canvas.itemcget(trunk, "fill"), color)
        for edge in ("e4t_to_e1", "e4z_to_e1"):
            self.style.apply(scope(edge))
            self.assertEqual(self.canvas.itemcget(trunk, "fill"), color)

    def test_workflow_layer_allows_explicit_drag_to_front(self):
        focused = self.canvas.create_rectangle(10, 10, 200, 100, tags=("gate-group:e2_to_e4",))
        other = self.canvas.create_rectangle(10, 10, 200, 100, tags=("gate-group:e3_to_e4",))
        self.style.raise_scope(scope("e2_to_e4"))
        self.assertEqual(self.canvas.find_all()[-1], focused)
        self.canvas.tag_raise("gate-group:e3_to_e4")
        self.callback_namespace()["_raise_graph_overlay_layers"]()
        self.assertEqual(self.canvas.find_all()[-1], other)

    def test_compact_and_full_toolbar_bounds_and_no_callback_growth(self):
        self.assertGreater(len(self.toolbar.find_withtag("history")), 3)
        initial_commands = len(self.toolbar._tclCommands)
        for width in (300, 400, 600, 900, 1600) * 3:
            self.toolbar._resize(SimpleNamespace(width=width))
            for action in self.commands:
                bounds = self.toolbar.bbox(action)
                self.assertGreaterEqual(bounds[0], 0)
                self.assertLessEqual(bounds[2], self.toolbar._layout_width)
                self.assertLessEqual(bounds[3], self.toolbar._height)
        self.assertEqual(len(self.toolbar._tclCommands), initial_commands)

    def test_toolbar_zoom_does_not_rebuild_icons(self):
        original = self.toolbar.find_all()
        for zoom in (0.65, 1.1, 1.035, 1.8, 2.4):
            self.toolbar.sync(zoom, self.toolbar.context)
            self.assertEqual(self.toolbar.find_all(), original)
            self.assertEqual(self.toolbar.itemcget("zoom_value", "text"), f"{zoom:.0%}")

    def test_toolbar_commands_and_zoom_limits(self):
        for action in self.commands:
            self.assertEqual(self.toolbar.invoke(action), "break")
            self.commands[action].assert_called_once()
        self.toolbar.sync(0.65, self.toolbar.context)
        self.toolbar.invoke("zoom_out")
        self.commands["zoom_out"].assert_called_once()
        self.toolbar.sync(2.4, self.toolbar.context)
        self.toolbar.invoke("zoom_in")
        self.commands["zoom_in"].assert_called_once()

    def test_resize_updates_toolbar_but_destroy_leaves_parent_binding(self):
        callback = Mock()
        binding = self.canvas.bind("<Configure>", callback, add="+")
        self.toolbar.destroy()
        self.assertIn(binding, self.canvas.bind("<Configure>"))

    def test_sidebar_slide_defers_graph_render_until_settled(self):
        owner = SimpleNamespace(_project_sidebar_animating=True)
        draw = Mock()
        redraw_state = {"after_id": None}
        ns = self.callback_namespace(graph_redraw_state=redraw_state,
            graph_pan_state={}, gate_drag_state={}, node_drag_state={},
            _graph_modal_activity_active=lambda: False, _draw=draw, _bind_gate_tags=Mock())
        ns["self"] = owner
        for _ in range(5):
            ns["_request_graph_redraw"](delay_ms=1)
            self.root.tk.call("after", 5)
            self.root.update()
        draw.assert_not_called()
        self.assertIsNone(redraw_state["after_id"])
        owner._project_sidebar_animating = False
        ns["_request_graph_redraw"](delay_ms=1)
        self.root.tk.call("after", 5)
        self.root.update()
        draw.assert_called_once()


if __name__ == "__main__":
    unittest.main()
