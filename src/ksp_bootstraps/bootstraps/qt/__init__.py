from pathlib import Path
from ksp_bootstraps.bootstrap import BootstrapProtocol, ProjectDelegate, XcodeProjectDelegate, GradleProjectDelegate
from .qt_gradle import QtGradleBuilder
from .qt_xcode import QtXcodeBuilder
from ...platforms import Platform
from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol


class QtBootstrap:  # <-- Removed (BootstrapProtocol)
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
                        QtGradleBuilder(self.py_project, delegate).generate(**kw)
                case "apple":
                    if isinstance(delegate, XcodeProjectDelegate):
                        return QtXcodeBuilder(self.py_project, delegate).generate(**kw)
                case _:
                    raise NotImplementedError(f"Platform {platform} not implemented for Qt bootstrap")

    def sync_site_xcframeworks(self) -> None:
        if isinstance(self.delegate, XcodeProjectDelegate):
            QtXcodeBuilder(self.py_project, self.delegate).sync_site_xcframeworks()

    def install_frameworks(self) -> None:
        if isinstance(self.delegate, XcodeProjectDelegate):
            QtXcodeBuilder(self.py_project, self.delegate)._install_frameworks()