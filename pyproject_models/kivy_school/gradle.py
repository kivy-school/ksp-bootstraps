from typing import Protocol, Sequence, List
from pathlib import Path
from enum import Enum, StrEnum

class AndroidProtocol(Protocol):

    @property 
    def package_name(self) -> str: ...

    @property 
    def archs(self) ->  Sequence[StrEnum]: ...

    @property 
    def api(self) ->  int | None: ...

    @property 
    def min_api(self) ->  int | None: ...
    
    @property 
    def sdk(self) ->  str | None: ...

    @property
    def ndk(self) ->  str | None: ...
    
    @property 
    def ndk_api(self) ->  int | None: ...

    @property 
    def sdk_path(self) -> Path | None: ...

    @property
    def ndk_path(self) -> Path | None: ...
    
    @property 
    def java_path(self) -> Path | None: ...
    
    @property 
    def global_tools(self) -> bool: ...
    
    @property 
    def global_tools_path(self) -> Path | None: ...
    
    @property 
    def icon(self) -> str | None: ...
    
    @property 
    def presplash(self) -> str | None: ...
    
    @property 
    def presplash_color(self) -> str | None: ...
    
    @property 
    def presplash_lottie(self) -> str | None: ...
    
    @property 
    def permissions(self) -> Sequence[str]: ...
    
    @property 
    def meta_data(self) -> dict[str, str]: ...
    
    @property 
    def gradle_dependencies(self) -> list[str]: ...
    
    @property 
    def gradle_plugins(self) -> list[str]: ...
    
    @property 
    def services(self) -> Sequence["ServiceData"]: ...
    
    @property 
    def version_code(self) -> int: ...
    
    @property 
    def version_name(self) -> str: ...
    
    @property 
    def include_files(self) -> Sequence[tuple[str, list[str]]]: ...

    @property 
    def pre_build(self) -> Path | None: ...
    
    @property 
    def post_build(self) -> Path | None: ...

    @property
    def byte_compile_python(self) -> bool: ...

    def kivyschool_root(self, working_dir: Path) -> Path: ...


    # class Arch(Enum):
    #     ARM64_V8A = "arm64-v8a"
    #     X86_64 = "x86_64"
        

    class ServiceData(Protocol):

        @property
        def name(self) -> str: ...

        @property
        def entrypoint(self) -> str: ...

        @property
        def foreground(self) -> bool: ...

        @property
        def foreground_service_type(self) -> str | None: ...

        @property
        def start_type(self) -> str: ...

        @property
        def notification_title(self) -> str: ...

        @property
        def notification_text(self) -> str: ...

        @property
        def notification_icon(self) -> str: ...
        
        
