"""Writes the Main Swift Package that Gradle cross-compiles for Android.

One package is the whole native side of a Nucleant app: the app's own Swift, the
framework it is written against, and the JNI edge the Activity calls through.
Gradle builds it once per ABI with ``swift build --swift-sdk <triple>`` (the
pattern from swiftlang/swift-android-examples) and drops the resulting ``.so``
plus the Swift runtime into ``jniLibs/<abi>/``.

Android has no ``main()`` to hook — the Activity is the entry point — so this is
a *dynamic library* whose exported Swift functions are called from Java through
swift-java's jextract in JNI mode. For that reason the entry source is
``NucleantMain.swift`` and **must not** be named ``main.swift``: SwiftPM infers
target kind from that one filename, so a ``main.swift`` makes the target an
executable and the build fails with "library product 'NucleantMain' should not
contain executable targets".

Why the app's framework *is* a dependency here
----------------------------------------------
The Python-era bootstrap deliberately depended on nothing: NucleantApplication
and the rest of the stack shipped inside the ``nucleant`` wheel, arriving as a
separate ``_nucleant.so`` that Python dlopened, so the two halves had no
link-time relationship and could only meet over a dlsym'd C ABI. Every surface
event had to be looked up lazily, and a surface created before the wheel loaded
was lost — which is what ``nucleant_refresh_host_hooks`` existed to repair.

With Python gone there is one binary. NucleantSwiftUI, NucleantApplication and
Platform_Android link straight into ``libNucleantMain.so``, so the surface
entry points in ``AndroidSurfaceHost`` are ordinary Swift functions in the same
image, and the replay path is gone along with the window during which they were
absent.

How little is generated
-----------------------
Because of that, almost nothing here is app-specific. The surface, input and
lifecycle work lives in NucleantApplication — ``Platform_Android``'s
``AndroidSurfaceBridge``, next to the ``AndroidSurfaceHost`` it drives, with the
``CAndroidNativeWindow`` shim beside it. What is generated is:

* ``Package.swift`` — swift-java plus whatever the project declared;
* ``NucleantMain.swift`` — one-line forwards into that bridge, which exist only
  because jextract reads *syntax* and so generates Java for the ``public func``s
  in the target its plugin is attached to;
* ``swift-java.config`` — the fixed ``org.nucleantui`` package and JNI mode.

The app's own Swift is copied in verbatim. Nothing rewrites it: an earlier
version stripped a top-level ``@main``, believing the attribute illegal in a
library target. It is not — SwiftPM infers an executable from a file *named*
``main.swift``, not from the attribute — so ``@main struct MyApp: NucleantApp``
is one spelling that serves desktop and Android alike.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .nucleant_config import GENERATED_MARKER, NucleantConfig

# swift-java, pinned rather than floored. 0.1.2 introduced the `SwiftJava`
# product name and jextract's `"mode": "jni"` config, but does not compile on
# Swift 6.3.3 — `JNISwift2JavaGenerator+JavaTranslation.swift` fails type
# checking. 0.4.2 is the release the prebuilt bootstrap was built with against
# this toolchain, so it is the one asked for here.
#
# It needs swift-syntax 603, which means any package in the graph pinning
# swift-syntax `exact:` to 602 will resolve swift-java back down to 0.1.2 and
# reintroduce that failure — the pin has to agree across the whole graph.
SWIFT_JAVA_VERSION = "0.4.2"

# Name of the SwiftPM package directory inside the app module, and of its one
# library target. The directory name is load-bearing: JExtractSwiftPlugin writes
# its generated Java under a path keyed by the package directory's lowercased
# name, which the Gradle task globs for.
SWIFT_PACKAGE_DIR = "swift"

# The generated target, and the dynamic product it is shipped as.
#
# Deliberately different names. The *product* decides the file name, and
# `libNucleantMain.so` is what `NucleantActivity`'s `System.loadLibrary` asks
# for, so it is fixed. The *target* decides the Swift module name, and therefore
# the name of the Java class jextract generates from it — `org.nucleantui.AppMain`
# — which has to not collide with `org.nucleantui.NucleantBridge`, the class
# NucleantApplication generates for the surface/input/lifecycle edge.
#
# Neither is derived from the app: one compiled Activity has to serve every app,
# so nothing an app chooses may reach a class name or a JNI symbol.
SWIFT_TARGET_NAME = "AppMain"
SWIFT_PRODUCT_NAME = "NucleantMain"

# The Java package jextract emits into. Fixed, never derived from applicationId:
# it lands in the generated class name *and* in every JNI symbol
# (`Java_org_nucleantui_NucleantMain_…`), so deriving it from the app would make
# the bridge un-shareable — the reason a prebuilt bootstrap was impossible
# before. Same fixed identity as `org.libsdl.app`.
JAVA_PACKAGE = "org.nucleantui"

# Where the app's own Swift is copied to inside the generated target.
APP_SOURCES_SUBDIR = "App"


def write_swift_package(
    swift_dir: Path,
    config: NucleantConfig,
) -> None:
    """Materialize the Main Swift Package at ``swift_dir``.

    When the project already has a ``Package.swift`` there, that manifest is
    left alone — ``swift_main`` pointed at a package the project owns, and
    overwriting it would discard hand-written targets. The bridge sources are
    still refreshed into it, because those are the half this bootstrap is
    responsible for and they have to match the Java it also generates.
    """
    target_dir = swift_dir / "Sources" / SWIFT_TARGET_NAME
    target_dir.mkdir(parents=True, exist_ok=True)

    if config.swift_main_is_foreign:
        print(
            f"[ksproject] {swift_dir / 'Package.swift'} exists — leaving it as "
            "the project's own; refreshing the generated bridge sources only."
        )
    else:
        _write_package_swift(swift_dir, config)

    _write_swift_java_config(target_dir)
    _write_nucleant_main_swift(target_dir, config)
    _copy_app_sources(target_dir, config)
    _remove_stale_bridge_sources(swift_dir, target_dir)


# ---------------------------------------------------------------------------
# Package.swift
# ---------------------------------------------------------------------------


def _write_package_swift(swift_dir: Path, config: NucleantConfig) -> None:
    """Emit Package.swift: swift-java, plus whatever the project declared."""
    package_deps = [
        f'        .package(url: "https://github.com/swiftlang/swift-java", from: "{SWIFT_JAVA_VERSION}"),'
    ]
    target_deps = [
        '                .product(name: "SwiftJava", package: "swift-java"),',
    ]
    for dep in config.dependencies:
        package_deps.append(f"        {dep.as_package_dependency(swift_dir)},")
        for product in dep.as_target_dependencies():
            target_deps.append(f"                {product},")

    unsafe = ""
    if config.unsafe_flags:
        flags = ", ".join(f'"{f}"' for f in config.unsafe_flags)
        unsafe = f"\n                .unsafeFlags([{flags}]),"

    content = f"""\
// swift-tools-version: 6.2
//
// {GENERATED_MARKER}
//
// The Main Swift Package — generated by ksproject. Built by Gradle, once per
// ABI, via `swift build --swift-sdk <triple>`; the product lands in
// jniLibs/<abi>/ and the jextract-generated Java lands in the app's java source
// set. Treat it as generated output — regenerating overwrites it.
//
// This is the whole native side of the app: the app's own Swift (under
// Sources/{SWIFT_TARGET_NAME}/{APP_SOURCES_SUBDIR}/), the framework it is written against, and the
// JNI edge the Activity calls. One binary, so the surface hooks in
// Platform_Android are reached as ordinary Swift calls rather than through a
// dlsym'd C ABI.

import PackageDescription

let package = Package(
    name: "{SWIFT_PRODUCT_NAME}",
    products: [
        // .dynamic: Gradle copies the built lib{SWIFT_PRODUCT_NAME}.so straight into
        // jniLibs/<abi>/, and the JNI shims jextract generates are compiled into
        // it — a static product would have nothing to load at runtime.
        .library(
            name: "{SWIFT_PRODUCT_NAME}",
            type: .dynamic,
            targets: ["{SWIFT_TARGET_NAME}"]
        )
    ],
    dependencies: [
{chr(10).join(package_deps)}
    ],
    targets: [
        .target(
            name: "{SWIFT_TARGET_NAME}",
            dependencies: [
{chr(10).join(target_deps)}
            ],
            swiftSettings: [
                .swiftLanguageMode(.v5),{unsafe}
            ],
            plugins: [
                // Generates the Java class the Activity calls, plus the JNI
                // glue that lands in lib{SWIFT_TARGET_NAME}.so. Configured by
                // Sources/{SWIFT_TARGET_NAME}/swift-java.config.
                .plugin(name: "JExtractSwiftPlugin", package: "swift-java")
            ]
        )
    ]
)
"""
    (swift_dir / "Package.swift").write_text(content, encoding="utf-8")


def _write_swift_java_config(target_dir: Path) -> None:
    """jextract's per-target config: which Java package to emit into, JNI mode
    (rather than the FFM mode, which Android's JVM does not have), and which
    native library the generated class should load.

    The package is ``JAVA_PACKAGE``, not the app's — see the constant.

    ``nativeLibraryName`` matters because the target and the product are named
    differently. The generated Java's static initializer calls
    ``System.loadLibrary`` with the *module* name unless told otherwise, and
    there is no ``libAppMain.so`` — the module is linked into the one dynamic
    product, ``lib{SWIFT_PRODUCT_NAME}.so``. NucleantApplication's own bridge
    target sets the same value for the same reason.
    """
    content = f"""\
{{
  "javaPackage": "{JAVA_PACKAGE}",
  "mode": "jni",
  "nativeLibraryName": "{SWIFT_PRODUCT_NAME}"
}}
"""
    (target_dir / "swift-java.config").write_text(content, encoding="utf-8")


def _remove_stale_bridge_sources(swift_dir: Path, target_dir: Path) -> None:
    """Delete generated sources earlier versions of this file wrote.

    ``CAndroidNativeWindow``, ``AndroidSurface.swift`` and the whole Java edge
    moved into NucleantApplication, where the code that uses them lives. A
    regenerated tree that still has them would compile both copies — two modules
    declaring the same C shim, and two definitions of every surface entry point,
    which jextract would then emit two conflicting Java classes for.

    Only ever removes output this generator used to own, so a project that has
    its own target of the same name under ``swift_main`` keeps it.
    """
    stale_window = swift_dir / "Sources" / "CAndroidNativeWindow"
    if (stale_window / "module.modulemap").is_file():
        shutil.rmtree(stale_window)
    for stale in ("AndroidSurface.swift", "NucleantMain.swift"):
        path = target_dir / stale
        if path.is_file():
            path.unlink()
    # The target was called NucleantMain before the Java edge moved into
    # NucleantApplication; its old directory would otherwise stay in Sources/
    # with a duplicate copy of the app's own Swift beside it.
    legacy_target = swift_dir / "Sources" / "NucleantMain"
    if legacy_target.is_dir() and legacy_target != target_dir:
        for orphan in ("NucleantMain.swift", "AndroidSurface.swift", "swift-java.config"):
            path = legacy_target / orphan
            if path.is_file():
                path.unlink()


# ---------------------------------------------------------------------------
# The app's own Swift
# ---------------------------------------------------------------------------


def _copy_app_sources(target_dir: Path, config: NucleantConfig) -> None:
    """Copy the project's Swift into the generated target.

    Copied rather than referenced: SwiftPM will not take sources from outside
    the package directory, and a symlink out of a generated tree breaks as soon
    as the project moves. The destination is wiped first so a source deleted in
    the project does not survive in the build.

    Copied *verbatim*. An earlier version rewrote a top-level ``@main`` into a
    comment, on the belief that the attribute is legal only in an executable and
    so would fail in this library target. It does not: a package whose only
    product is a `.library` builds fine with a `@main` type — what SwiftPM infers
    an executable from is a file *named* ``main.swift``, which is also the real
    source of the "library product should not contain executable targets" error.
    So an app's ``@main struct MyApp: NucleantApp`` is one portable spelling —
    the entry point on macOS and Linux, an unused static member here — and
    nothing needs to edit the author's code on the way into the build.
    """
    dest = target_dir / APP_SOURCES_SUBDIR
    if dest.exists():
        shutil.rmtree(dest)
    if not config.sources:
        return
    dest.mkdir(parents=True, exist_ok=True)

    for src in config.sources:
        for item in src.rglob("*.swift"):
            relative = item.relative_to(src)
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


# ---------------------------------------------------------------------------
# AppMain.swift — the app's entry point
#
# Not "main.swift": SwiftPM treats that filename as top-level code and infers an
# executable target from it, which a `.library` product may not contain. (The
# `@main` *attribute* is fine in a library — only the filename is special, which
# is why the app's own source keeps its `@main` untouched.)
#
# One function. Everything else that crosses to Java — surface, input,
# lifecycle — is `org.nucleantui.NucleantBridge`, generated by NucleantApplication
# from a module that ships with it. Only this one cannot live there: it builds
# the app's `NucleantApp` type, which comes from NucleantSwiftUI, a layer *above*
# NucleantApplication. `NucleantActivity.startApp` is the hand-off.
# ---------------------------------------------------------------------------


def _write_nucleant_main_swift(target_dir: Path, config: NucleantConfig) -> None:
    # The entry names types from the app's framework — the `NucleantApp`
    # conformer and the `AppRuntime` that drives it — so each configured
    # product is imported by name.
    product_imports = "".join(
        f"import {product}\n"
        for dep in config.dependencies
        for product in (dep.products or (dep.name,))
    )
    if config.has_app:
        body = f"""\
    // Deliberately *not* `{config.entry}.main()`, even though the app type
    // carries `@main` for the sake of desktop builds.
    //
    // That entry is for a process the app owns: it builds an `AppRuntime` in a
    // local, calls `setup()` and then `run()` — and on macOS and iOS `run()`
    // never returns, so the local lives as long as the process. On Android
    // `run()` fires `onStart()` and comes straight back, because the Activity
    // owns the UI thread and the main looper and the render loop belongs to
    // PlatformWindow. `main()` would then return, releasing the runtime and
    // with it the windows, the platform window, and the render thread's only
    // strong reference — the app would build a window, attach a canvas, and be
    // torn down again before a single frame was drawn.
    //
    // So the runtime is built here and held for the life of the process. The
    // Activity started long before any of this and outlives it; nothing on this
    // side is an entry point.
    //
    // `MainActor.assumeIsolated` rather than an `await`: Android has no main
    // queue anyone drains — Java's Looper owns the main thread — so there is
    // nothing to hop onto and a hop would deadlock. It holds because the
    // Activity calls this on the thread that owns the app, and everything the
    // runtime touches afterwards stays on it. The same assertion HostingWindow
    // makes on every platform callback.
    MainActor.assumeIsolated {{
        let runtime = AppRuntime(app: {config.entry}())
        nucleantAppRuntime = runtime
        runtime.setup()
        runtime.run()
    }}
    return 0"""
    else:
        body = """\
    // No `entry` in [tool.kivy-school.nucleant], so there is no app to start.
    // The package still builds — useful for checking that the bridge and the
    // Swift SDK agree — but an APK built this way shows nothing.
    return 0"""

    content = f"""\
//
//  {SWIFT_TARGET_NAME}.swift
//  The app's Android entry point — generated by ksproject.
//
//  jextract turns `nucleantRunMain` into a static method on
//  `{JAVA_PACKAGE}.{SWIFT_TARGET_NAME}`, which the generated `MainActivity`
//  calls from `NucleantActivity.startApp`. Everything else that crosses to
//  Java — surface, input, lifecycle — is `{JAVA_PACKAGE}.NucleantBridge`, which
//  ships with NucleantApplication and is not generated per app.
//

// Android: chdir/setenv/errno — Foundation does not re-export them here.
import Android
import Foundation
import NucleantBridge
import Platform_Android
{{product_imports}}
/// The running app, held for the life of the process.
///
/// Nothing else owns it: the Activity is Java, and the Swift side is entered
/// through a JNI call that returns. See `nucleantRunMain`.
nonisolated(unsafe) var nucleantAppRuntime: AnyObject?

/// Start the app. Returns once it is running, not when it exits.
///
/// `appPath` is the unpacked asset directory, handed over by Java rather than
/// derived here: only the Activity knows where it put things.
public func nucleantRunMain(appPath: String) -> Int32 {{
    // stdout/stderr to logcat, before anything has a chance to print.
    nucleantPrepareProcess(appPath: appPath)

    // Resources the Swift graph loads by path — SwiftPM resource bundles
    // included — resolve relative to the working directory, and a fresh Android
    // process starts in "/".
    if chdir(appPath) != 0 {{
        nucleantLogError("chdir(\\(appPath)) failed: \\(String(cString: strerror(errno)))")
    }}
    setenv("NUCLEANT_APP_PATH", appPath, 1)

{{body}}
}}
"""
    content = content.replace("{product_imports}", product_imports)
    content = content.replace("{body}", body)
    (target_dir / f"{SWIFT_TARGET_NAME}.swift").write_text(content, encoding="utf-8")
