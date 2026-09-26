"""The ``[tool.kivy-school.nucleant]`` section, read by the bootstrap itself.

Every other part of the project model reaches a bootstrap through
``PyProjectTomlProtocol`` — a structural contract whose concrete implementation
lives in ksproject. This section deliberately does not go through it: what a
Nucleant app's native side is made of is *this* bootstrap's business, not
something every bootstrap has in common (the kivy one has no Swift at all), and
putting it in the shared protocol would oblige ksproject's model to grow fields
only one bootstrap reads.

So it is parsed here, straight out of the project's own pyproject.toml with
``tomllib``. ksproject stays untouched, and another bootstrap that wants a
different native layout can parse its own section without negotiating with this
one.

Example::

    [tool.kivy-school.nucleant]
    # Where the Main Swift Package lives, relative to the project. Generated
    # there when absent; used as-is when it already exists.
    swift_main = "swift"
    # The NucleantApp-conforming type whose main() the Activity runs.
    entry = "DemoApp"
    # The app's own Swift, copied into the generated target.
    sources = ["src/swift"]

    [[tool.kivy-school.nucleant.dependencies]]
    name = "NucleantSwiftUI"
    path = "../NucleantSwiftUI"
    products = ["NucleantSwiftUI"]

A dependency takes either ``path`` (relative to the project directory, or
absolute) or ``url`` plus one of ``branch`` / ``from`` / ``exact``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Where the Main Swift Package goes when the project does not say.
DEFAULT_SWIFT_MAIN = "swift"


@dataclass(frozen=True)
class SwiftDependency:
    """One package the Main Swift Package depends on."""

    name: str
    path: Path | None = None
    url: str | None = None
    branch: str | None = None
    version_from: str | None = None
    exact: str | None = None
    products: tuple[str, ...] = ()

    def as_package_dependency(self, relative_to: Path | None = None) -> str:
        """The ``.package(...)`` line for Package.swift.

        ``relative_to`` is the generated package's own directory: SwiftPM
        resolves a path dependency relative to the manifest, so an absolute
        path is rewritten to a relative one where possible. That keeps the
        generated tree movable, and readable in a diff.
        """
        if self.path is not None:
            target = self.path
            if relative_to is not None:
                try:
                    target = Path(os_relpath(self.path, relative_to))
                except ValueError:
                    target = self.path
            return f'.package(path: "{target.as_posix()}")'
        if self.url is None:
            raise NucleantConfigError(
                f"nucleant dependency {self.name!r} has neither 'path' nor 'url'"
            )
        if self.branch:
            return f'.package(url: "{self.url}", branch: "{self.branch}")'
        if self.exact:
            return f'.package(url: "{self.url}", exact: "{self.exact}")'
        if self.version_from:
            return f'.package(url: "{self.url}", from: "{self.version_from}")'
        raise NucleantConfigError(
            f"nucleant dependency {self.name!r} gives a url but no "
            "'branch', 'from' or 'exact'"
        )

    def as_target_dependencies(self) -> list[str]:
        """The ``.product(...)`` lines this dependency contributes.

        No products listed means the package name doubles as the product name,
        which is the common case for a package vending one library.
        """
        products = self.products or (self.name,)
        return [f'.product(name: "{p}", package: "{self.name}")' for p in products]


def os_relpath(target: Path, start: Path) -> str:
    """``os.path.relpath``, kept behind a name so the import stays local."""
    import os.path

    return os.path.relpath(target, start)


@dataclass(frozen=True)
class NucleantConfig:
    """``[tool.kivy-school.nucleant]``."""

    #: Absolute path to the Main Swift Package.
    swift_main: Path
    #: True when a Package.swift is there that this generator did not write, so
    #: it belongs to the project and must not be overwritten. A manifest we
    #: generated carries GENERATED_MARKER and is ours to refresh.
    swift_main_is_foreign: bool = False
    entry: str | None = None
    sources: tuple[Path, ...] = ()
    dependencies: tuple[SwiftDependency, ...] = ()
    unsafe_flags: tuple[str, ...] = ()
    #: Environment for the per-ABI `swift build`. Some choices in the
    #: Nucleant graph are made in Package.swift, which can only read
    #: the environment — NUCLEANT_ANDROID_USE_AHARDWAREBUFFER is one,
    #: and it has to reach NucleantVulkan and NucleantThorVG alike or
    #: their import paths disagree.
    env: tuple[tuple[str, str], ...] = ()

    @property
    def has_app(self) -> bool:
        """Whether an app entry point was configured at all.

        Without one the package still builds — it is then just the JNI bridge
        and whatever the dependencies bring, which is a useful thing to be able
        to compile on its own.
        """
        return self.entry is not None


class NucleantConfigError(Exception):
    pass


def load_nucleant_config(project_dir: Path) -> NucleantConfig:
    """Parse ``[tool.kivy-school.nucleant]`` from ``project_dir/pyproject.toml``.

    A missing file or section is not an error: the defaults put the Main Swift
    Package at ``<project>/swift`` with no app entry, and the caller decides
    whether that is usable.
    """
    section: dict = {}
    pyproject = project_dir / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
        tool = data.get("tool", {})
        # Both spellings: TOML keys are literal, and both show up in projects
        # depending on which generator wrote the file.
        kivy_school = tool.get("kivy-school") or tool.get("kivy_school") or {}
        section = kivy_school.get("nucleant") or {}

    swift_main = _resolve(
        project_dir, section.get("swift_main", DEFAULT_SWIFT_MAIN)
    )

    sources = tuple(
        _resolve(project_dir, s) for s in section.get("sources", []) or []
    )
    for src in sources:
        if not src.is_dir():
            raise NucleantConfigError(
                f"[tool.kivy-school.nucleant] sources: {src} is not a directory"
            )

    dependencies = tuple(
        _dependency(project_dir, entry)
        for entry in section.get("dependencies", []) or []
    )

    return NucleantConfig(
        swift_main=swift_main,
        swift_main_is_foreign=_is_foreign_package(swift_main),
        entry=section.get("entry"),
        sources=sources,
        dependencies=dependencies,
        unsafe_flags=tuple(section.get("unsafe_flags", []) or []),
        env=tuple((str(k), str(v)) for k, v in (section.get("env", {}) or {}).items()),
    )


def _resolve(project_dir: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (project_dir / p).resolve()


def _dependency(project_dir: Path, entry: dict) -> SwiftDependency:
    name = entry.get("name")
    if not name:
        raise NucleantConfigError(
            "[[tool.kivy-school.nucleant.dependencies]] entry has no 'name'"
        )

    raw_path = entry.get("path")
    path = _resolve(project_dir, raw_path) if raw_path else None
    if path is not None and not path.is_dir():
        raise NucleantConfigError(
            f"nucleant dependency {name!r}: path {path} does not exist"
        )

    return SwiftDependency(
        name=name,
        path=path,
        url=entry.get("url"),
        branch=entry.get("branch"),
        version_from=entry.get("from"),
        exact=entry.get("exact"),
        products=tuple(entry.get("products", []) or []),
    )


#: Written into every generated Package.swift so a later run can tell its own
#: output from a manifest the project wrote by hand.
GENERATED_MARKER = "ksproject:generated-main-swift-package"


def _is_foreign_package(swift_main: Path) -> bool:
    """Whether ``swift_main`` holds a Package.swift this generator did not write.

    Existence alone cannot answer this: the generator's own output exists from
    the second run onwards, and treating that as the project's would freeze the
    manifest at whatever the first run produced — so a changed dependency or a
    toolchain pin would never reach it.
    """
    manifest = swift_main / "Package.swift"
    if not manifest.is_file():
        return False
    return GENERATED_MARKER not in manifest.read_text(encoding="utf-8")
