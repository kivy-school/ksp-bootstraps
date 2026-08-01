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
        run_func: str = "runApp",
        imports: list[str] | None = None,
        modules: list[str] | None = None,
    ) -> str:
    """Return the contents of ``main.swift`` for a Nucleant app.

    ``platform`` is ``"iOS"`` or ``"macOS"``.  Both get the same body:
    ``NucleantLauncher`` declares ``runApp`` on either platform (differing only
    in whether it hands the process to ``UIApplicationMain``), so the entry
    point is one call regardless.

    ``imports`` adds modules beyond the two always needed; ``modules`` adds
    extra ``addToImports()`` registrations inside ``onPreImport``, which is the
    hook that runs after the interpreter is configured but before the app
    module is imported.
    """
    if platform not in ("iOS", "macOS"):
        raise ValueError(f"Unsupported platform for main.swift: {platform!r}")

    extra_imports = "".join(f"import {name}\n" for name in (imports or []))
    extra_modules = "".join(
        f"    {name}.addToImports()\n" for name in (modules or [])
    )

    return f"""import Foundation
import PyNucleantUI
{extra_imports}

func onPreLaunch() {{

}}

func onPreImport() {{
    PyNucleantUI_Package.addToImports()
{extra_modules}}}

func onQuit(status: Int32) {{
    exit(status)
}}

NucleantLauncher.{run_func}(
    on_prelaunch: onPreLaunch,
    on_preimport: onPreImport,
    on_quit: onQuit
)
"""
