from typing import Protocol
from pathlib import Path


class AppleProtocol(Protocol):
    
    @property
    def bundle_id(self) -> str: ...
    
    @property
    def info_plist(self) -> dict: ...
    
    @property
    def entitlements(self) -> dict: ...
    
    @property
    def permissions(self) -> list[str]: ...
    
    @property
    def developer_team(self) -> str | None: ...

    @property
    def pre_build(self) -> Path | None: ...

    @property
    def post_build(self) -> Path | None: ...


class IosProtocol(AppleProtocol):

    @property
    def frameworks(self) -> list[str]: ...
    
    @property
    def site_frameworks(self) -> list[str]: ...
    
    

class MacOSProtocol(AppleProtocol):
    ...

