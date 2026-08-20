from __future__ import annotations
from pathlib import Path

from ksp_bootstraps.bootstrap import XcodeProjectDelegate
from ksp_bootstraps.pyproject_models.pyproject_toml import PyProjectTomlProtocol
from ksp_bootstraps.tools import resolve_module_name

class QtXcodeBuilder:
    delegate: XcodeProjectDelegate

    def __init__(self, pyproject: PyProjectTomlProtocol, delegate: XcodeProjectDelegate) -> None:
        self.pyproject = pyproject
        self.working_dir = delegate.working_dir
        self.delegate = delegate

        self.kivy_school = pyproject.tool.kivy_school
        if self.kivy_school is None:
            raise ValueError("[tool.kivy-school] is missing")
            
        self.app_name = self.kivy_school.app_name or pyproject.project.name
        self.module_name = resolve_module_name(self.pyproject.project.name)
        
        # Setup Qt-specific Apple config here...

    @property
    def project_dir(self) -> Path:
        return self.working_dir / "project_dist" / "xcode"

    def _install_frameworks(self) -> None:
        # Install CPython and copy Qt .xcframework files into Frameworks/
        self.delegate.install_cpython()
        pass

    def sync_site_xcframeworks(self) -> None:
        # Sync logic for XcodeGen
        pass

    def generate(self, platforms: list[str] | None = None) -> Path:
        plats = platforms or ["iOS", "macOS"]
        
        # 1. Create Layout
        # 2. Write Info.plist (Requires Qt specific keys like UIApplicationSceneManifest adjustments)
        # 3. Write main.swift or main.mm (Must initialize QApplication before Python)
        # 4. Generate project.yml and run xcodegen
        
        xcodeproj = self.project_dir / f"{self.app_name}.xcodeproj"
        return xcodeproj