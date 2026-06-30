from typing import Generic, Protocol
from pathlib import Path

from .platforms import Platform




class ProjectDelegate(Protocol):
    
    def install_cpython(self, platform: Platform): ...

    def android_prefix(self, ks_root: Path, arch: str, android_version: str) -> Path: ...

    @property
    def android_default_api_version(self) -> int: ...

    @property
    def android_sdk_path(self) -> str: ...
    
    @property
    def android_ndk_version(self) -> str: ...
    
    @property
    def android_ndk_path(self) -> str: ...
    
    @property
    def android_java_path(self) -> str: ...
    
    @property
    def android_py_version(self) -> str: ...

    

    @property
    def py_version(self) -> str: ...



    @property
    def working_dir(self) -> Path: ...
    
    


class BootstrapProtocol(Protocol):


    #delegate: ProjectDelegate
    @property
    def delegate(self) -> ProjectDelegate:
        ...

    def generate(self, **kw: object): ...

