from typing import Protocol, Generic
from pathlib import Path

from .kivy_school.apple import MacOSProtocol, IosProtocol
from .kivy_school.gradle import AndroidProtocol

class PyProjectProtocol(Protocol):

    @property
    def name(self) -> str: ...


class KivySchoolProtocol(Protocol):

    @property
    def app_name(self) -> str | None: ...

    @property
    def android(self) -> AndroidProtocol | None: ...

    @property
    def ios(self) -> IosProtocol | None: ...

    @property
    def macos(self) -> MacOSProtocol | None: ...



class ToolProtocol(Protocol):

    @property
    def kivy_school(self) -> KivySchoolProtocol | None: ...




class PyProjectTomlProtocol(Protocol):

    @property
    def project(self) -> PyProjectProtocol: ...

    @property
    def tool(self) -> ToolProtocol: ...
    
    