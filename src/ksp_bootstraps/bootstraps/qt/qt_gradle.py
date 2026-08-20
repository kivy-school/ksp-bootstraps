from __future__ import annotations

import shutil
from pathlib import Path
from enum import StrEnum

from ...platforms import AndroidPlatform
from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol
from ...pyproject_models.kivy_school.gradle import AndroidProtocol
from ...bootstrap import GradleProjectDelegate
from .gradle_build_files import QtGradleBuildFiles


def _merge_unique(base: list[str], extra: list[str]) -> list[str]:
    return list(dict.fromkeys(base + extra))


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


def _discover_and_install_qt_jars(app_dir: Path, prefix: Path) -> list[str]:
    libs_dir = app_dir / "libs"
    libs_dir.mkdir(parents=True, exist_ok=True)
    discovered: list[str] = []
    site_packages = prefix / "lib"
    if not site_packages.exists():
        return discovered
    for archive in site_packages.rglob("*"):
        if archive.suffix.lower() in {".jar", ".aar"}:
            dst = libs_dir / archive.name
            if not dst.exists():
                shutil.copy2(archive, dst)
            discovered.append(archive.name)
    return discovered


def _discover_qt_libs(prefix: Path, py_version: str) -> list[str]:
    qt_libs: list[str] = ["c++_shared"]
    search_paths = [prefix / "lib", prefix / f"lib/python{py_version}/site-packages"]
    found_libs = set()
    for base in search_paths:
        if not base.exists():
            continue
        for so in base.rglob("libQt*.so"):
            name = so.name
            if name.startswith("lib") and name.endswith(".so"):
                clean_name = name[3:-3]
                found_libs.add(clean_name)
    core_lib = [lib for lib in found_libs if "Core" in lib]
    other_libs = sorted(list(found_libs - set(core_lib)))
    return qt_libs + core_lib + other_libs


class QtGradleBuilder:

    delegate: GradleProjectDelegate

    def __init__(
        self, pyproject: PyProjectTomlProtocol, delegate: GradleProjectDelegate
    ):
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
            else f"org.kivyschool.{pyproject.project.name.lower()}"
        )
        self.archs = (
            self.android.archs
            if self.android and self.android.archs
            else list[StrEnum]()
        )
        self.ks_root: Path = self.android.kivyschool_root(delegate.working_dir)

    def _resolve_asset(self, name: str) -> Path:
        user_value: str | None = (
            getattr(self.android, name, None) if self.android else None
        )
        if user_value:
            p = Path(user_value)
            if not p.is_absolute():
                p = self.working_dir / p
            return p
        templates = Path(__file__).parent.parent / "kivy" / "templates"
        for ext in ("png", "jpg", "gif", "json"):
            candidate = templates / f"{name}.{ext}"
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"No template found for '{name}' in {templates}")

    def generate(
        self,
        sdk_path: str,
        aar: bool = False,
        extra_gradle_dependencies: list[str] | None = None,
        extra_permissions: list[str] | None = None,
    ) -> None:
        dist_dir = self.working_dir / "project_dist" / "gradle"
        dist_dir.mkdir(parents=True, exist_ok=True)

        base_deps = self.android.gradle_dependencies if self.android else []
        base_perms = self.android.permissions if self.android else []
        base_plugins = (
            getattr(self.android, "gradle_plugins", []) if self.android else []
        )

        merged_deps = _merge_unique(base_deps, extra_gradle_dependencies or [])
        merged_perms = _merge_unique(base_perms, extra_permissions or [])

        v_code = getattr(self.android, "version_code", 1) if self.android else 1
        v_name = getattr(self.android, "version_name", "1.0") if self.android else "1.0"

        QtGradleBuildFiles.write_root_build_gradle(dist_dir, base_plugins)
        QtGradleBuildFiles.write_settings_gradle(dist_dir, self.app_name)
        QtGradleBuildFiles.write_gradle_properties(dist_dir)
        QtGradleBuildFiles.write_local_properties(dist_dir, sdk_path)

        delegate = self.delegate
        default_api_ver = delegate.default_api_version
        py_version = delegate.py_version
        app_dir = dist_dir / "app"
        app_dir.mkdir(parents=True, exist_ok=True)

        QtGradleBuildFiles.write_app_build_gradle(
            project_dir=self.working_dir,
            app_dir=app_dir,
            package_name=self.package_name,
            archs=self.archs,
            compile_sdk=(
                self.android.api
                if self.android and self.android.api
                else default_api_ver
            ),
            min_sdk=(
                self.android.min_api if self.android and self.android.min_api else 26
            ),
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
            post_build=self.android.post_build if self.android else None,
            byte_compile_default=(
                self.android.byte_compile_python if self.android else True
            ),
            uv_python=getattr(delegate, "uv_py_version", None),
        )

        main_dir = app_dir / "src" / "main"
        main_dir.mkdir(parents=True, exist_ok=True)
        QtGradleBuildFiles.write_android_manifest(
            main_dir,
            package_name=self.package_name,
            project_dir=self.working_dir,
            app_name=self.app_name,
            permissions=merged_perms,
            meta_data=self.android.meta_data if self.android else {},
            services=self.android.services if self.android else [],
        )

        res_dir = main_dir / "res"
        try:
            QtGradleBuildFiles.write_icon(res_dir, self._resolve_asset("icon"))
        except FileNotFoundError:
            pass

        presplash_type = None
        presplash_name = None
        presplash_color = (
            getattr(self.android, "presplash_color", "#FFFFFF")
            if self.android
            else "#FFFFFF"
        )

        try:
            asset_src = self._resolve_asset("presplash")
            drawable_dir = res_dir / "drawable"
            drawable_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset_src, drawable_dir / asset_src.name)
            presplash_type = "image"
            presplash_name = asset_src.stem
        except FileNotFoundError:
            pass

        QtGradleBuildFiles.write_main_activity(
            main_dir=main_dir,
            package_name=self.package_name,
            python_version=py_version,
            python_module=self.pyproject.project.name,
            presplash_type=presplash_type,
            presplash_name=presplash_name,
            presplash_color=presplash_color,
        )

        QtGradleBuildFiles.write_qt_python_service(main_dir)
        if self.android and self.android.services:
            for svc in self.android.services:
                QtGradleBuildFiles.write_custom_service(
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

        cpp_dir = main_dir / "cpp"
        project_name = (
            self.pyproject.project.name.strip().replace("-", "_").replace(" ", "_")
        )
        QtGradleBuildFiles.write_main_c(cpp_dir, py_version, project_name)
        QtGradleBuildFiles.write_service_main_c(cpp_dir, project_name)
        QtGradleBuildFiles.write_cmake_lists(cpp_dir)

        QtGradleBuildFiles.write_gradle_wrapper(dist_dir, delegate.java_path)

        delegate.install_cpython()

        first_arch_val = self.archs[0].value if self.archs else ""
        if first_arch_val:
            prefix = delegate.android_prefix(
                self.ks_root, first_arch_val, delegate.android_py_version
            )
            _discover_and_install_qt_jars(app_dir, prefix)
            qt_libs = _discover_qt_libs(prefix, delegate.android_py_version)
            QtGradleBuildFiles.write_qt_libs_xml(main_dir, qt_libs)

        for arch in self.archs:
            prefix = delegate.android_prefix(
                self.ks_root, arch.value, delegate.android_py_version
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

            py_inc_src = prefix / f"include/python{py_version}"
            py_inc_dst = main_dir / "cpp" / "python_include" / arch.value
            if py_inc_src.exists() and not py_inc_dst.exists():
                shutil.copytree(py_inc_src, py_inc_dst)

        first_prefix = delegate.android_prefix(
            self.ks_root, self.archs[0].value, delegate.android_py_version
        )
        stdlib_src = first_prefix / f"lib/python{py_version}"
        assets_dir = main_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        stdlib_dst = assets_dir / f"python{py_version}"
        if not stdlib_dst.exists() and stdlib_src.exists():
            _copy_pure_python(stdlib_src, stdlib_dst)

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

        if self.android and self.android.include_files:
            for dest_str, sources in self.android.include_files:
                dest_base = self.working_dir / "project_dist"
                target_dir = dest_base / dest_str
                target_dir.mkdir(parents=True, exist_ok=True)

                for src_str in sources:
                    if "*" in src_str or "?" in src_str:
                        if Path(src_str).is_absolute():
                            import glob

                            paths_to_copy = [Path(p) for p in glob.glob(src_str)]
                        else:
                            paths_to_copy = list(self.working_dir.glob(src_str))

                        if not paths_to_copy:
                            continue
                    else:
                        src_path = Path(src_str)
                        if not src_path.is_absolute():
                            src_path = self.working_dir / src_path

                        if not src_path.exists():
                            continue
                        paths_to_copy = [src_path]

                    for path in paths_to_copy:
                        if path.is_dir():
                            shutil.copytree(
                                path, target_dir / path.name, dirs_exist_ok=True
                            )
                        else:
                            shutil.copy2(path, target_dir / path.name)
