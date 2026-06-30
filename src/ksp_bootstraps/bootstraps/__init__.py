

from .kivy import KivyBootstrap
from ..bootstrap import BootstrapProtocol, ProjectDelegate
from ..pyproject_models.pyproject_toml import PyProjectTomlProtocol

class BootstrapError(Exception):

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)

registered_bootstraps: dict[str, BootstrapProtocol] = {}

def register_bootstrap(name: str, cls: BootstrapProtocol):
    registered_bootstraps[name] = cls

def get_bootstrap(name: str, pyproject: PyProjectTomlProtocol, delegate: ProjectDelegate) -> BootstrapProtocol:

    match name:
        case "kivy":
            return KivyBootstrap(pyproject, delegate)
        case _ if name in registered_bootstraps:
            return registered_bootstraps[name]
        case _:
            raise BootstrapError(f"<{name}> is not a bootstrap")
        
