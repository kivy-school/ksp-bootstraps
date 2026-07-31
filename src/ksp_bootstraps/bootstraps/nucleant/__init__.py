from ksp_bootstraps.bootstrap import BootstrapProtocol, ProjectDelegate, XcodeProjectDelegate, GradleProjectDelegate
from .kivy_gradle import KivyGradleBuilder
from .kivy_xcode import KivyXcodeBuilder
from ...platforms import Platform
from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol
from ...pyproject_models.kivy_school.apple import MacOSProtocol, IosProtocol
from ...pyproject_models.kivy_school.gradle import AndroidProtocol
from pathlib import Path



class KivyBootstrap:

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
                        KivyGradleBuilder(self.py_project, delegate).generate(**kw)
                case "apple":
                    if isinstance(delegate, XcodeProjectDelegate):
                        return KivyXcodeBuilder(self.py_project, delegate).generate(**kw)
                case _:
                    raise NotImplementedError(platform)
                
    def sync_site_xcframeworks(self) -> None:
        if isinstance(self.delegate, XcodeProjectDelegate):
            KivyXcodeBuilder(self.py_project, self.delegate).sync_site_xcframeworks()

    def install_frameworks(self) -> None:
        if isinstance(self.delegate, XcodeProjectDelegate):
            KivyXcodeBuilder(self.py_project, self.delegate)._install_frameworks()

    
