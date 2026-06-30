from ksp_bootstraps.bootstrap import BootstrapProtocol, ProjectDelegate
from .kivy_gradle import KivyGradleBuilder
from .kivy_xcode import KivyXcode
from ...platforms import Platform
from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol

class KivyBootstrap:

    delegate: ProjectDelegate
    builder: KivyGradleBuilder

    def __init__(self, py_project: PyProjectTomlProtocol, delegate: ProjectDelegate):
        self.delegate = delegate
        self.builder = KivyGradleBuilder(py_project, delegate)

    def generate(self, **kw):
        platform: Platform = kw.pop("platform")
        if platform:
            ...
    


if __name__ == "__main__":
    from ...bootstrap import ProjectTest
    bootstrap: BootstrapProtocol = KivyBootstrap(ProjectTest())