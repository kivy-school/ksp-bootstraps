from typing import Protocol, Sequence
from pathlib import Path



class IosProtocol(Protocol):

    @property
    def bundle_id(self) -> str: ...
    
    @property
    def info_plist(self) -> dict: ...
    
    @property
    def entitlements(self) -> dict: ...
    
    @property
    def permissions(self) -> Sequence[str]: ...
    
    @property
    def developer_team(self) -> str | None: ...

    @property
    def pre_build(self) -> Path | None: ...

    @property
    def post_build(self) -> Path | None: ...

    @property
    def frameworks(self) -> Sequence[str]: ...
    
    @property
    def site_frameworks(self) -> Sequence[str]: ...
    
    

class MacOSProtocol(Protocol):
    
    @property
    def bundle_id(self) -> str: ...
    
    @property
    def info_plist(self) -> dict: ...
    
    @property
    def entitlements(self) -> dict: ...
    
    @property
    def permissions(self) -> Sequence[str]: ...
    
    @property
    def developer_team(self) -> str | None: ...

    @property
    def pre_build(self) -> Path | None: ...

    @property
    def post_build(self) -> Path | None: ...

