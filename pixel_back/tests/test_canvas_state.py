import unittest

from app.canvas.state import CanvasState


class CanvasStateTests(unittest.TestCase):
    def test_committed_pixel_updates_head_and_color(self):
        state = CanvasState(3, 2)
        state.initialize_white()
        state.apply_committed_pixel(2, 1, '#aabbcc', 7)
        self.assertEqual('#AABBCC', state.get_pixel(2, 1))
        self.assertEqual(7, state.head_event_id)

    def test_revision_is_independent_copy(self):
        state = CanvasState(1, 1)
        state.initialize_white()
        revision = state.capture_revision()
        state.apply_committed_pixel(0, 0, '#000000', 1)
        self.assertEqual(255, revision.pixels[0, 0, 0])

    def test_out_of_bounds_is_rejected(self):
        state = CanvasState(1, 1)
        state.initialize_white()
        with self.assertRaises(ValueError):
            state.get_pixel(1, 0)
