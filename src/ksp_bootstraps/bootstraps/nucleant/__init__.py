from pathlib import Path

from ...bootstrap import ProjectDelegate, XcodeProjectDelegate, GradleProjectDelegate
from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol
from .nucleant_gradle import NucleantGradleBuilder
from .nucleant_xcode import NucleantXcodeBuilder


class NucleantBootstrap:
    """Nucleant's project bootstrap: a Vulkan surface hosted by the platform's
    own view class, with Swift between it and Python.

    On Apple that is a UIView/NSView backed by CAMetalLayer; on Android a plain
    Activity's SurfaceView. Neither goes through SDL.
    """

    delegate: ProjectDelegate
    py_project: PyProjectTomlProtocol

    def __init__(self, py_project: PyProjectTomlProtocol, delegate: ProjectDelegate):
        self.delegate = delegate
        self.py_project = py_project

    def generate(self, **kw) -> Path | None:
        platform: str = kw.pop("platform")
        delegate = self.delegate
        if platform:
            match platform:
                case "android":
                    if isinstance(delegate, GradleProjectDelegate):
                        NucleantGradleBuilder(self.py_project, delegate).generate(**kw)
                case "apple":
                    if isinstance(delegate, XcodeProjectDelegate):
                        return NucleantXcodeBuilder(self.py_project, delegate).generate(**kw)
                case _:
                    raise NotImplementedError(platform)

    def sync_site_xcframeworks(self) -> None:
        if isinstance(self.delegate, XcodeProjectDelegate):
            NucleantXcodeBuilder(self.py_project, self.delegate).sync_site_xcframeworks()

    def install_frameworks(self) -> None:
        if isinstance(self.delegate, XcodeProjectDelegate):
            NucleantXcodeBuilder(self.py_project, self.delegate)._install_frameworks()
