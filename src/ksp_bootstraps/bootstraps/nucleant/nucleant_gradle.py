"""Orchestrates Gradle project generation for the Nucleant bootstrap.

Where the Kivy bootstrap downloads SDL2 and builds a C ``SDL_main`` under CMake,
this one generates a plain ``Activity`` hosting a ``SurfaceView`` and a SwiftPM
package that Gradle cross-compiles for each ABI.  The Python runtime staging
(libpython, lib-dynload, stdlib, per-arch sysconfig data) is unchanged — that
part was never SDL's.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from enum import StrEnum

from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol
from ...bootstrap import GradleProjectDelegate
from .gradle_build_files import GradleBuildFiles


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
            python_version=py_version,
            ndk_version=delegate.ndk_version,
            ndk_path=delegate.ndk_path,
            aar=aar,
            gradle_dependencies=merged_deps,
            version_code=v_code,
            version_name=v_name,
            post_build=(self.android.post_build if self.android else None),
            byte_compile_default=(
                self.android.byte_compile_python if self.android else True
            ),
            uv_python=getattr(delegate, "uv_py_version", None),
            app_module=_module_name(self.pyproject.project.name),
        )

        _install_bootstrap_aar(app_dir)

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

        # Build CPython for Android (cached in <ks_root>/Python-<ver>/)
        delegate.install_cpython()

        # Copy libpython + arch-specific extension modules to jniLibs per ABI
        for arch in self.archs:
            prefix = delegate.android_prefix(
                self.ks_root,
                arch.value,
                delegate.android_py_version
            )
            jni_abi = main_dir / "jniLibs" / arch.value
            jni_abi.mkdir(parents=True, exist_ok=True)

            lib_src_dir = prefix / "lib"
            src_lib = lib_src_dir / f"libpython{py_version}.so"
            if src_lib.exists():
                dst_lib = jni_abi / "libpython3.so"
                if not dst_lib.exists():
                    shutil.copy2(src_lib, dst_lib)
            for so_file in lib_src_dir.glob("lib*.so"):
                if so_file.name == f"libpython{py_version}.so":
                    continue
                dst = jni_abi / so_file.name
                if not dst.exists():
                    shutil.copy2(so_file, dst)

            lib_dynload = prefix / f"lib/python{py_version}/lib-dynload"
            if lib_dynload.exists():
                dynload_dst = main_dir / "assets" / "lib-dynload" / arch.value
                dynload_dst.mkdir(parents=True, exist_ok=True)
                for so_file in lib_dynload.iterdir():
                    if so_file.suffix == ".so":
                        dst = dynload_dst / so_file.name
                        if not dst.exists():
                            shutil.copy2(so_file, dst)

        # Copy pure Python stdlib once (no .so, no lib-dynload)
        first_prefix = delegate.android_prefix(
            self.ks_root, self.archs[0].value, delegate.android_py_version
        )
        stdlib_src = first_prefix / f"lib/python{py_version}"
        assets_dir = main_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stdlib_dst = assets_dir / f"python{py_version}"
        if not stdlib_dst.exists() and stdlib_src.exists():
            _copy_pure_python(stdlib_src, stdlib_dst)

        # _sysconfigdata / _sysconfig_vars are arch-specific (arch-suffixed
        # filenames, so they coexist); the stdlib above only carries the first
        # arch's copy. Python 3.14 imports them via ctypes -> sysconfig at
        # startup, so every ABI needs its own.
        if stdlib_dst.exists():
            for arch in self.archs:
                arch_prefix = delegate.android_prefix(
                    self.ks_root, arch.value, delegate.android_py_version
                )
                arch_stdlib = arch_prefix / f"lib/python{py_version}"
                for pattern in ("_sysconfigdata__*", "_sysconfig_vars__*"):
                    for cfg_file in arch_stdlib.glob(pattern):
                        dst = stdlib_dst / cfg_file.name
                        if not dst.exists():
                            shutil.copy2(cfg_file, dst)

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
        print("  app/libs/ — the prebuilt Nucleant bootstrap AAR (no Swift is built here)")
        print(f"  app/src/main/jniLibs/<abi> — libpython + extension .so per ABI")
        print(f"  app/src/main/assets/python{py_version}/ — pure Python stdlib")
        print(
            "  site-packages copied at build time via Gradle "
            "stagePython/zipPythonAssets tasks"
        )
        print("")


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    """Merge two lists preserving order and removing duplicates."""
    return list(dict.fromkeys(base + extra))


def _module_name(project_name: str) -> str:
    """``my-app`` -> ``my_app`` — the importable name `python -m` is given."""
    return project_name.strip().replace("-", "_").replace(".", "_").replace(" ", "_")


def _copy_pure_python(src: Path, dst: Path) -> None:
    _SKIP_DIRS = {"lib-dynload", "test", "tests", "__pycache__", "site-packages"}
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.is_dir():
            if child.name in _SKIP_DIRS:
                continue
            _copy_pure_python(child, dst / child.name)
        elif child.suffix not in {".so", ".pyc"}:
            shutil.copy2(child, dst / child.name)


def _install_bootstrap_aar(app_dir: Path) -> None:
    """Put the prebuilt Nucleant bootstrap AAR where Gradle will find it.

    The AAR carries the JNI bridge, the CPython launcher,
    ``org.nucleantui.NucleantActivity`` and the Swift runtime, so an app builds
    no Swift at all.  ``app/build.gradle.kts`` globs ``libs/*.aar``, so copying
    it in is the whole wiring.

    Local file for now, keyed by ``NUCLEANT_BOOTSTRAP_AAR`` — a path to the AAR
    or to a directory holding one.  When the AAR is published this becomes a
    Maven coordinate and this function goes away.
    """
    configured = os.environ.get("NUCLEANT_BOOTSTRAP_AAR")
    libs_dir = app_dir / "libs"
    libs_dir.mkdir(parents=True, exist_ok=True)

    if not configured:
        print(
            "[ksproject] NUCLEANT_BOOTSTRAP_AAR is not set — no bootstrap AAR "
            "installed. Build one and point that variable at it, or drop the "
            f".aar into {libs_dir} yourself; the Java will not compile without it."
        )
        return

    source = Path(configured).expanduser()
    if source.is_dir():
        candidates = sorted(source.glob("nucleant-bootstrap-*.aar"))
        if not candidates:
            print(f"[ksproject] no nucleant-bootstrap-*.aar in {source}")
            return
        source = max(candidates, key=lambda p: p.stat().st_mtime)
    if not source.is_file():
        print(f"[ksproject] NUCLEANT_BOOTSTRAP_AAR does not exist: {source}")
        return

    # One bootstrap at a time: two in libs/ means two copies of every .so, which
    # AGP reports as a duplicate-path packaging failure.
    for stale in libs_dir.glob("nucleant-bootstrap-*.aar"):
        if stale.name != source.name:
            stale.unlink()
    shutil.copy2(source, libs_dir / source.name)
    print(f"[ksproject] bootstrap AAR: {source.name}")
