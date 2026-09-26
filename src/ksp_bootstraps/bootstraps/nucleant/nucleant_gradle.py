"""Orchestrates Gradle project generation for the Nucleant bootstrap.

Where the Kivy bootstrap downloads SDL2 and builds a C ``SDL_main`` under CMake,
this one generates a plain ``Activity`` hosting a ``SurfaceView`` and a SwiftPM
package that Gradle cross-compiles for each ABI — app, framework and JNI bridge
in one library. There is no Python runtime to stage: an app's native side is
entirely Swift now, and CPython returns only when the optional Python layer
does.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from enum import StrEnum

from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol
from ...bootstrap import GradleProjectDelegate
from .gradle_build_files import GradleBuildFiles
from .nucleant_config import load_nucleant_config
from .swift_package_files import write_swift_package


class NucleantGradleBuilder:

    delegate: GradleProjectDelegate

    def __init__(self, pyproject: PyProjectTomlProtocol, delegate: GradleProjectDelegate):
        self.pyproject = pyproject
        self.working_dir = delegate.working_dir
        self.delegate = delegate
        kivy_school = pyproject.tool.kivy_school
        if kivy_school is None:
            raise ValueError("[tool.kivy-school] is missing in pyproject.toml")
        if kivy_school.android is None:
            raise ValueError("[tool.kivy-school.android] is missing in pyproject.toml")

        self.kivy_school = kivy_school
        self.android = kivy_school.android
        self.app_name = kivy_school.app_name or pyproject.project.name
        self.package_name = (
            self.android.package_name
            if self.android and self.android.package_name
            else f"org.nucleant.{pyproject.project.name.lower()}"
        )
        self.archs = (
            self.android.archs
            if self.android and self.android.archs
            else list[StrEnum]()
        )
        self.ks_root: Path = self.android.kivyschool_root(delegate.working_dir)

    # ------------------------------------------------------------------
    # Asset resolution
    # ------------------------------------------------------------------

    def _resolve_asset(self, name: str) -> Path:
        """Return the path to a user-supplied asset or the bundled template fallback.

        ``name`` is e.g. ``"icon"`` — looks up ``android.icon`` in pyproject.toml
        and falls back to ``templates/<name>.png`` (then ``.jpg``).
        """
        user_value: str | None = (
            getattr(self.android, name, None) if self.android else None
        )
        if user_value:
            p = Path(user_value)
            if not p.is_absolute():
                p = self.working_dir / p
            return p
        templates = Path(__file__).parent / "templates"
        for ext in ("png", "jpg", "gif", "json"):
            candidate = templates / f"{name}.{ext}"
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"No template found for '{name}' in {templates}")

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        sdk_path: str,
        aar: bool = False,
        extra_gradle_dependencies: list[str] | None = None,
        extra_permissions: list[str] | None = None,
    ) -> None:
        dist_dir = self.working_dir / "project_dist" / "gradle"
        dist_dir.mkdir(parents=True, exist_ok=True)

        # Merge gradle dependencies and permissions from pyproject.toml with
        # those collected from site-packages .gradle/*.json files (ksp-builder).
        base_deps = self.android.gradle_dependencies if self.android else []
        base_perms = self.android.permissions if self.android else []
        base_plugins = (
            getattr(self.android, "gradle_plugins", []) if self.android else []
        )

        merged_deps = _merge_unique(base_deps, extra_gradle_dependencies or [])
        merged_perms = _merge_unique(base_perms, extra_permissions or [])  # type: ignore

        v_code = getattr(self.android, "version_code", 1) if self.android else 1
        v_name = getattr(self.android, "version_name", "1.0") if self.android else "1.0"

        # Root Gradle files
        GradleBuildFiles.write_root_build_gradle(dist_dir, base_plugins)
        GradleBuildFiles.write_settings_gradle(dist_dir, self.app_name)
        GradleBuildFiles.write_gradle_properties(dist_dir)
        GradleBuildFiles.write_local_properties(dist_dir, sdk_path)

        # app module (must exist before `gradle wrapper` evaluates settings.gradle.kts)
        delegate = self.delegate
        default_api_ver = delegate.default_api_version
        py_version = delegate.py_version
        app_dir = dist_dir / "app"
        app_dir.mkdir(parents=True, exist_ok=True)

        min_sdk = (
            self.android.min_api if self.android and self.android.min_api else 24
        )
        # The Main Swift Package is written before the Gradle files that build
        # it, so a first `ksproject android build` needs no separate step.
        nucleant = load_nucleant_config(self.working_dir)
        write_swift_package(nucleant.swift_main, nucleant)

        GradleBuildFiles.write_app_build_gradle(
            project_dir=self.working_dir,
            app_dir=app_dir,
            package_name=self.package_name,
            archs=self.archs,  # type: ignore
            compile_sdk=(
                self.android.api
                if self.android and self.android.api
                else default_api_ver
            ),
            min_sdk=min_sdk,
            target_sdk=(
                self.android.api
                if self.android and self.android.api
                else default_api_ver
            ),
            ndk_version=delegate.ndk_version,
            ndk_path=delegate.ndk_path,
            aar=aar,
            gradle_dependencies=merged_deps,
            version_code=v_code,
            version_name=v_name,
            post_build=(self.android.post_build if self.android else None),
            swift_main=nucleant.swift_main,
            native_lib_dirs=_vendored_native_roots(nucleant),
            nucleant_java_dir=_nucleant_java_root(nucleant),
            swift_env=nucleant.env,
        )

        main_dir = app_dir / "src" / "main"
        main_dir.mkdir(parents=True, exist_ok=True)
        res_dir = main_dir / "res"
        GradleBuildFiles.write_icon(res_dir, self._resolve_asset("icon"))

        presplash_type = None
        presplash_name = None
        presplash_color = (
            getattr(self.android, "presplash_color", "#FFFFFF")
            if self.android
            else "#FFFFFF"
        )

        # Check for Lottie first, then fall back to a standard presplash image/gif
        lottie_path = (
            getattr(self.android, "presplash_lottie", None) if self.android else None
        )

        if lottie_path:
            asset_src = self._resolve_asset("presplash_lottie")
            raw_dir = res_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset_src, raw_dir / asset_src.name)
            presplash_type = "lottie"
            presplash_name = asset_src.stem
            merged_deps.append("com.airbnb.android:lottie:6.0.0")
        else:
            # ALWAYS attempt to resolve "presplash".
            # If the user didn't specify one, _resolve_asset pulls from templates/
            try:
                asset_src = self._resolve_asset("presplash")
                drawable_dir = res_dir / "drawable"
                drawable_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asset_src, drawable_dir / asset_src.name)
                presplash_type = (
                    "gif" if asset_src.suffix.lower() == ".gif" else "image"
                )
                presplash_name = asset_src.stem
            except FileNotFoundError:
                # Failsafe in case the templates folder is missing
                pass

        # After the presplash, because the bootstrap AAR reads it from the
        # manifest rather than from generated constants.
        GradleBuildFiles.write_android_manifest(
            main_dir,
            package_name=self.package_name,
            project_dir=self.working_dir,
            app_name=self.app_name,
            permissions=merged_perms,
            meta_data=(self.android.meta_data if self.android else {}),
            services=(self.android.services if self.android else []),  # type: ignore
            entrypoint=_module_name(self.pyproject.project.name),
            presplash_name=presplash_name,
            presplash_type=presplash_type,
            presplash_color=presplash_color,
        )

        # NucleantActivity, NucleantSurfaceView and NucleantService are compiled
        # into the bootstrap AAR; only this app's subclass is generated.
        GradleBuildFiles.write_main_activity(
            main_dir=main_dir,
            package_name=self.package_name,
            python_module=self.pyproject.project.name,
        )
        if self.android and self.android.services:
            for svc in self.android.services:
                GradleBuildFiles.write_custom_service(
                    main_dir=main_dir,
                    package_name=self.package_name,
                    service_name=svc.name,
                    python_version=py_version,
                    entrypoint=svc.entrypoint,
                    foreground=svc.foreground,
                    start_type=svc.start_type,
                    notification_title=svc.notification_title,
                    notification_text=svc.notification_text,
                    notification_icon=svc.notification_icon,
                )

        # Generate the wrapper now that the app module exists on disk
        GradleBuildFiles.write_gradle_wrapper(dist_dir, delegate.java_path)

        # ------------------------------------------------------------------
        # Process include_files (e.g. google-services.json, *.json)
        # ------------------------------------------------------------------
        if self.android and self.android.include_files:
            for dest_str, sources in self.android.include_files:
                # Resolve destination relative to the project_dist folder
                dest_base = self.working_dir / "project_dist"
                target_dir = dest_base / dest_str
                target_dir.mkdir(parents=True, exist_ok=True)

                for src_str in sources:
                    # Check if the source string contains wildcard characters
                    if "*" in src_str or "?" in src_str:
                        if Path(src_str).is_absolute():
                            import glob

                            paths_to_copy = [Path(p) for p in glob.glob(src_str)]
                        else:
                            paths_to_copy = list(self.working_dir.glob(src_str))

                        if not paths_to_copy:
                            print(
                                f"[ksproject] Warning: No files matched include_file pattern: {src_str}"
                            )
                            continue
                    else:
                        src_path = Path(src_str)
                        if not src_path.is_absolute():
                            src_path = self.working_dir / src_path

                        if not src_path.exists():
                            print(
                                f"[ksproject] Warning: include_file source not found: {src_path}"
                            )
                            continue
                        paths_to_copy = [src_path]

                    for path in paths_to_copy:
                        if path.is_dir():
                            shutil.copytree(
                                path, target_dir / path.name, dirs_exist_ok=True
                            )
                        else:
                            shutil.copy2(path, target_dir / path.name)
                        print(
                            f"[ksproject] Copied include_file: {path.name} -> {target_dir}"
                        )

        print(f"Gradle project generated at: {dist_dir}")
        print(f"  {nucleant.swift_main} — the Main Swift Package, built per ABI by Gradle")
        print("  app/src/main/jniLibs/<abi> — libNucleantMain.so, the Swift runtime")
        print("    and the vendored native libraries, staged at build time")
        print("")


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    """Merge two lists preserving order and removing duplicates."""
    return list(dict.fromkeys(base + extra))


def _module_name(project_name: str) -> str:
    """``my-app`` -> ``my_app`` — the importable name `python -m` is given."""
    return project_name.strip().replace("-", "_").replace(".", "_").replace(" ", "_")



def _nucleant_java_root(nucleant) -> Path | None:
    """NucleantApplication's ``Android/java``, if it can be found.

    ``NucleantSurfaceView`` ships from there rather than being generated: it is
    the Java half of a contract whose Swift half (``AndroidSurfaceBridge``) is in
    the same package, and nothing about it is app-specific. Gradle compiles it
    straight out of the checkout, so there is one copy and an edit in
    NucleantApplication does not need a regenerate to take effect.

    Resolved here rather than in Gradle. The alternative is asking SwiftPM at
    configuration time (``swift package show-dependencies --format json``, which
    is how swift-java's own build logic learns its graph) — correct, but it runs
    SwiftPM on every Gradle invocation and resolves from the network on a cold
    tree, for a path that a filesystem check already answers.

    Two places to look, in order: beside a declared path dependency — the same
    sibling walk `_vendored_native_roots` uses, and true in a development tree —
    then the checkout SwiftPM made under the Main Swift Package, which is where a
    project consuming the packages from git has it. Returns None when neither
    exists, and the caller leaves the source set alone rather than naming a
    directory that is not there.
    """
    candidates: list[Path] = []
    for dep in nucleant.dependencies:
        if dep.path is None:
            continue
        candidates.append(dep.path.parent / "NucleantApplication")
    candidates.append(
        nucleant.swift_main / ".build" / "checkouts" / "NucleantApplication"
    )
    for candidate in candidates:
        java = candidate / "Android" / "java"
        if java.is_dir():
            return java
    return None

def _vendored_native_roots(nucleant) -> list[Path]:
    """Directories holding vendored Android .so files the Swift graph links.

    `libNucleantMain.so` needs ThorVG, wgpu, shaderc and spirv-cross at runtime,
    and none of them belong to the package the project names — they come from
    further down the Swift dependency tree. Rather than ask the project to
    restate its transitive graph, every Nucleant package keeps its Android
    artifacts at ``Dependencies/android/<abi>/lib``, so the siblings of a
    declared path dependency are exactly the right place to look.

    Everything found is staged. Narrowing it to what the linker recorded would
    be a way to ship a smaller APK, not a way to ship a correct one, and it is
    not worth getting wrong before the thing runs at all.
    """
    roots: list[Path] = []
    seen: set[Path] = set()
    for dep in nucleant.dependencies:
        if dep.path is None:
            continue
        # The checkout itself, then its siblings: a package's own artifacts sit
        # under it, and its dependencies' under the neighbours.
        for candidate in [dep.path, *sorted(dep.path.parent.iterdir())]:
            if not candidate.is_dir():
                continue
            android = candidate / "Dependencies" / "android"
            if android.is_dir() and android not in seen:
                seen.add(android)
                roots.append(android)
    return roots
