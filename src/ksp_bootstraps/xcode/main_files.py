"""Per-platform ``main.swift`` template.

Bakes in the KivyLauncher backend behavior from
``PSProject/Backends/Sources/Backends/backends/KivyLauncher.swift``.
"""
from __future__ import annotations
import textwrap

def render_main_swift(platform: str, run_func: str = "SDLmain") -> str:
    """Return the contents of ``main.swift`` for the given Apple platform.

    ``platform`` is ``"iOS"`` or ``"macOS"``.
    """
    imports = ""
    modules = ""

    match platform:
        case "iOS": ...
        case "macOS": ...
        case _:
            raise ValueError(f"Unsupported platform for main.swift: {platform!r}")
    
    if platform == "iOS":
        imports = "import KivyLauncher\nimport Kivy_iOS_Module"
        modules = ".ios"
    elif platform == "macOS":
        imports = "import KivyLauncher"
        modules = ""
    else:
        raise ValueError(f"Unsupported platform for main.swift: {platform!r}")
    

    return textwrap.dedent(f"""\
    import Foundation

    exit(KivyLauncher.{run_func}())
    """)

def __render_main_swift(
        platform: str, 
        run_func: str = "SDLmain", 
        imports: list[str] = [],
        modules: list[str] = []
    ) -> str:
    """Return the contents of ``main.swift`` for the given Apple platform.

    ``platform`` is ``"iOS"`` or ``"macOS"``.
    """
    if platform == "iOS":
        #_imports = "import KivyLauncher\nimport Kivy_iOS_Module"
        #_modules = ".ios"
        _imports = "\n\t".join(imports)
        _modules = "\n\t".join(imports)
    elif platform == "macOS":
        _imports = "\n\t".join(imports)
        _modules = "\n\t".join(imports)
    else:
        raise ValueError(f"Unsupported platform for main.swift: {platform!r}")

    return f"""import Foundation
import Foundation
import PyNucleantUI


func onPreLaunch() {{

}}

func onPreImport() {{
    PyNucleantUI_Package.addToImports()
    
}}

func onQuit(status: Int32) {{
    exit(status)
}}

NucleantLauncher.runApp(
    on_prelaunch: onPreLaunch,
    on_preimport: onPreImport,
    on_quit: onQuit
)
"""
