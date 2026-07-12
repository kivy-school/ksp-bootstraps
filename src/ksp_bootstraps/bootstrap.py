from typing import Generic, Protocol, runtime_checkable
from pathlib import Path

from .platforms import Platform




class ProjectDelegate(Protocol):

    @property
    def py_version(self) -> str: ...

    @property
    def working_dir(self) -> Path: ...
    
    def install_cpython(self): ...

@runtime_checkable
class GradleProjectDelegate(Protocol):

    @property
    def py_version(self) -> str: ...

    @property
    def working_dir(self) -> Path: ...
    
    def install_cpython(self): ...

    def android_prefix(self, ks_root: Path, arch: str, android_version: str) -> Path: ...

    @property
    def default_api_version(self) -> int: ...

    @property
    def sdk_path(self) -> str: ...
    
    @property
    def ndk_version(self) -> str: ...
    
    @property
    def ndk_path(self) -> str: ...
    
    @property
    def java_path(self) -> str: ...

    @property
    def android_py_version(self) -> str: ...

    @property
    def uv_py_version(self) -> str: ...

@runtime_checkable
class XcodeProjectDelegate(Protocol):

    @property
    def py_version(self) -> str: ...

    @property
    def uv_py_version(self) -> str: ...

    @property
    def working_dir(self) -> Path: ...

    def install_cpython(self): ...

    def xcode_generate(self, **kw): ...

    

    
    
    


class BootstrapProtocol(Protocol):


    #delegate: ProjectDelegate
    @property
    def delegate(self) -> ProjectDelegate:
        ...

    def generate(self, **kw: object) -> Path | None: ...

    def sync_site_xcframeworks(self) -> None: ...

    def install_frameworks(self) -> None: ...

