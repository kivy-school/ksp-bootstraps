app_py = """\
import skia

from nucleant.app import App
from nucleant.canvas import SkiaCanvasBase
from nucleant.widget import PyWidgetBase
from nucleant.window import WindowBase


class IntroWidget(PyWidgetBase):

    def __init__(self, width: float, height: float):
        super().__init__()
        self.canvas = self.Canvas(width, height)

    class Canvas(SkiaCanvasBase):

        def __init__(self, width: float, height: float):
            super().__init__()
            # SkiaCanvasBase sizes off the widget's frame, which isn't exposed
            # to Python, so the size is passed down from the window.
            self.w = float(width)
            self.h = float(height)
            self.t = 0.0
            # Python-side objects are fine to build once; only the GPU surface
            # must be re-taken each frame.
            self.font = skia.Font(skia.Typeface("Roboto-Regular"), 28.0)
            self.font.setEdging(skia.Font.Edging.kAntiAlias)

        def resize(self, w: float, h: float) -> None:
            self.w = w
            self.h = h

        def update_canvas(self, dt: float):
            self.t += dt

            # Re-take the surface every frame and never cache it: a resize
            # rebuilds the render node and destroys the old one. Don't flush or
            # submit here either -- the engine owns that.
            surface = skia.Surface.FromCapsule(self.skia_surface_capsule())
            canvas = surface.getCanvas()

            canvas.clear(skia.Color4f(0.05, 0.05, 0.08, 1.0).toColor())

            paint = skia.Paint(
                AntiAlias=True,
                Color=skia.Color4f(0.25, 0.7, 1.0, 1.0).toColor(),
            )
            canvas.drawString("Hello from Nucleant", 32.0, 64.0, self.font, paint)


class IntroWindow(WindowBase):

    # 0, 0 and a nominal size: x/y are ignored where the platform owns the
    # frame (Android is always fullscreen), and on_size below is what the
    # content actually follows.
    def __init__(self, x: int = 0, y: int = 0, w: int = 800, h: int = 600):
        super().__init__(x, y, w, h)
        self.widget = IntroWidget(w, h)

    def on_build(self) -> PyWidgetBase:
        return self.widget

    def on_size(self, w: float, h: float) -> None:
        # Fires with the real surface size once the window is on screen, and
        # again on every rotation/resize.
        self.widget.canvas.resize(w, h)

    def on_frame(self, dt: float) -> None: ...

    def on_touch_down(self, id: int, x: float, y: float) -> None: ...
    def on_touch_moved(self, id: int, x: float, y: float) -> None: ...
    def on_touch_up(self, id: int, x: float, y: float) -> None: ...
    def on_touch_cancelled(self, id: int, x: float, y: float) -> None: ...

    def on_mouse_down(self, x: float, y: float) -> None: ...
    def on_mouse_up(self, x: float, y: float) -> None: ...
    def on_mouse_moved(self, x: float, y: float) -> None: ...
    def on_mouse_dragged(self, x: float, y: float) -> None: ...
    def on_right_mouse_down(self, x: float, y: float) -> None: ...
    def on_right_mouse_up(self, x: float, y: float) -> None: ...
    def on_scroll(self, dx: float, dy: float) -> None: ...
    def on_key_down(self, keyCode: int, characters: str | None) -> None: ...
    def on_key_up(self, keyCode: int, characters: str | None) -> None: ...


class IntroApp(App):

    def __init__(self, threads: int = 4) -> None:
        super().__init__(threads)
        self.window = IntroWindow()

    def on_start(self) -> None:
        self.window.present()


def main():
    app = IntroApp()
    app.run()
"""
