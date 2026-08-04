"""Writes Gradle project files (Kotlin DSL / .kts) for the Nucleant bootstrap.

Unlike the Kivy bootstrap this generates no SDL2, no CMake, and no p4a
compatibility layer.  A Nucleant app is a plain ``android.app.Activity`` hosting
a ``SurfaceView``, and everything below the Java line is Swift: Gradle
cross-compiles the SwiftPM package in ``app/swift/`` once per ABI (the pattern
from swiftlang/swift-android-examples), copies the products and the Swift
runtime into ``jniLibs/<abi>/``, and adds the Java that swift-java's jextract
generated to the app's source set.
"""

from __future__ import annotations

import shutil
import urllib.request
import zlib
from pathlib import Path
from enum import StrEnum

from ...pyproject_models.pyproject_toml import AndroidProtocol
from .swift_package_files import (
    JAVA_PACKAGE,
    PYTHON_INCLUDE_DIR,
    SWIFT_PACKAGE_DIR,
    SWIFT_TARGET_NAME,
)

_GRADLE_VERSION = "9.5.0"
# Gradle commits the wrapper jar to their own repo; download it directly so
# ksproject never needs a system-installed `gradle`.
_GRADLE_WRAPPER_JAR_URL = (
    "https://raw.githubusercontent.com/gradle/gradle"
    f"/refs/tags/v{_GRADLE_VERSION}/gradle/wrapper/gradle-wrapper.jar"
)

# Android ABI -> (Swift target triple stem, Swift SDK resource dir, NDK triple).
# The Swift Android SDK lays its runtime out by its own arch names
# (swift-aarch64) and the NDK by triple (aarch64-linux-android), neither of
# which matches Gradle's ABI directory names — this table is the join.
# 64-bit only, matching the two Android platforms ksp_bootstraps defines
# (AndroidArm64Platform, AndroidX86_64Platform). There is no 32-bit entry
# because nothing can request one.
_SWIFT_ABIS: dict[str, tuple[str, str, str]] = {
    "arm64-v8a": ("aarch64-unknown-linux-android", "swift-aarch64", "aarch64-linux-android"),
    "x86_64": ("x86_64-unknown-linux-android", "swift-x86_64", "x86_64-linux-android"),
}

# Swift runtime shared libraries copied out of the SDK into jniLibs.  Android
# has no system Swift runtime, so anything the app touches has to ship with it.
_SWIFT_RUNTIME_LIBS = [
    "swiftCore",
    "swift_Concurrency",
    "swift_StringProcessing",
    "swift_RegexParser",
    "swift_Builtin_float",
    "swift_math",
    "swiftAndroid",
    "dispatch",
    "BlocksRuntime",
    "swiftSwiftOnoneSupport",
    "swiftDispatch",
    # @Observable — the whole Swift graph uses Observation, so every app links
    # it whether or not its own code names it.
    "swiftObservation",
    "Foundation",
    "FoundationEssentials",
    "FoundationInternationalization",
    "_FoundationICU",
    "swiftSynchronization",
]


class GradleBuildError(Exception):
    pass


# Templates a project can edit are written once and then read back, so a change
# to the defaults below does not reach a project that already has one. Each
# carries a version marker; when the default's version is newer, the project's
# copy is replaced and the old one kept beside it. Bump these whenever the
# corresponding default template changes in a way an app needs.
_TEMPLATE_VERSION_MARKER = "ksproject-template:"
_BUILD_GRADLE_TEMPLATE_VERSION = 5
_MANIFEST_TEMPLATE_VERSION = 2


def _template_version(text: str) -> int:
    """The version a template declares, or 0 if it predates the marker."""
    for line in text.splitlines()[:5]:
        if _TEMPLATE_VERSION_MARKER in line:
            digits = line.split(_TEMPLATE_VERSION_MARKER, 1)[1]
            digits = "".join(c for c in digits if c.isdigit())
            if digits:
                return int(digits)
    return 0


def _ensure_template(path: Path, default: str, version: int) -> str:
    """Return the template to use, refreshing the project's copy if it is stale.

    A stale copy is moved aside rather than deleted: it may carry hand edits, and
    silently discarding those would be worse than the staleness this fixes.
    """
    if not path.exists():
        print(f"{path.name} not found... Continuing with default template...")
        path.write_text(default, encoding="utf-8")
        return default

    existing = path.read_text(encoding="utf-8")
    found = _template_version(existing)
    if found >= version:
        return existing

    backup = path.with_suffix(path.suffix + f".v{found}.bak")
    backup.write_text(existing, encoding="utf-8")
    path.write_text(default, encoding="utf-8")
    print(
        f"[ksproject] {path.name} was version {found}, the generator needs "
        f"{version} — replaced it. Your copy is at {backup.name}; re-apply any "
        "edits from it."
    )
    return default



class GradleBuildFiles:

    # -------------------------------------------------------------------------
    # Root project files
    # -------------------------------------------------------------------------

    @staticmethod
    def write_root_build_gradle(dir: Path, plugins_list: list[str]) -> None:
        plugins = f"\n    ".join(plugins_list)
        content = f"""\
// Top-level build file - generated by ksproject
plugins {{
    id("com.android.application") version "8.9.1" apply false
    id("com.android.library") version "8.9.1" apply false
    {plugins}
}}
"""
        (dir / "build.gradle.kts").write_text(content, encoding="utf-8")

    @staticmethod
    def write_settings_gradle(dir: Path, app_name: str) -> None:
        content = f"""\
pluginManagement {{
    repositories {{
        google()
        mavenCentral()
        gradlePluginPortal()
    }}
}}

dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}

rootProject.name = "{app_name}"
include(":app")
"""
        (dir / "settings.gradle.kts").write_text(content, encoding="utf-8")

    @staticmethod
    def write_gradle_properties(dir: Path) -> None:
        content = (
            "# Project-wide Gradle settings - generated by ksproject\n"
            "org.gradle.jvmargs=-Xmx1g -Dfile.encoding=UTF-8\n"
            # The Swift build tasks shell out and read the environment at
            # execution time, which the configuration cache rejects.
            "org.gradle.configuration-cache=false\n"
            "android.useAndroidX=true\n"
            "android.nonTransitiveRClass=true\n"
            "\n"
            "# Swift toolchain used to cross-compile app/swift/ for Android.\n"
            "# Override either here or via the matching environment variable.\n"
            "# swift.path=/path/to/swift          (env: SWIFT_PATH)\n"
            "# swift.sdk=swift-6.3-RELEASE_android  (env: SWIFT_ANDROID_SDK)\n"
            "# swift.config=release               (env: SWIFT_BUILD_CONFIG)\n"
        )
        (dir / "gradle.properties").write_text(content, encoding="utf-8")

    @staticmethod
    def write_local_properties(dir: Path, sdk_path: str) -> None:
        sdk_path = str(sdk_path).replace("\\", "/")
        (dir / "local.properties").write_text(f"sdk.dir={sdk_path}\n", encoding="utf-8")

    # -------------------------------------------------------------------------
    # Gradle wrapper
    # -------------------------------------------------------------------------

    @staticmethod
    def write_gradle_wrapper(dir: Path, java_path: str) -> None:
        wrapper_dir = dir / "gradle" / "wrapper"
        wrapper_dir.mkdir(parents=True, exist_ok=True)

        properties = (
            "distributionBase=GRADLE_USER_HOME\n"
            "distributionPath=wrapper/dists\n"
            f"distributionUrl=https\\://services.gradle.org/distributions/gradle-{_GRADLE_VERSION}-bin.zip\n"
            "networkTimeout=10000\n"
            "validateDistributionUrl=true\n"
            "zipStoreBase=GRADLE_USER_HOME\n"
            "zipStorePath=wrapper/dists\n"
        )
        (wrapper_dir / "gradle-wrapper.properties").write_text(
            properties, encoding="utf-8"
        )

        jar_path = wrapper_dir / "gradle-wrapper.jar"
        gradlew_path = dir / "gradlew"
        if jar_path.exists() and gradlew_path.exists():
            return

        _gh = f"https://raw.githubusercontent.com/gradle/gradle/refs/tags/v{_GRADLE_VERSION}"
        print(f"[ksproject] Downloading Gradle {_GRADLE_VERSION} wrapper files...")
        urllib.request.urlretrieve(_GRADLE_WRAPPER_JAR_URL, jar_path)
        urllib.request.urlretrieve(f"{_gh}/gradlew", gradlew_path)
        gradlew_path.chmod(0o755)
        urllib.request.urlretrieve(f"{_gh}/gradlew.bat", dir / "gradlew.bat")

    # -------------------------------------------------------------------------
    # App module
    # -------------------------------------------------------------------------

    @staticmethod
    def write_app_build_gradle(
        project_dir: Path,
        app_dir: Path,
        package_name: str,
        archs: list[StrEnum],
        compile_sdk: int,
        min_sdk: int,
        target_sdk: int,
        python_version: str = "3.13",
        ndk_version: str | None = None,
        ndk_path: str | None | Path = None,
        aar: bool = False,
        gradle_dependencies: list[str] | None = None,
        version_name: str = "1.0",
        version_code: int = 1,
        post_build: Path | None = None,
        byte_compile_default: bool = False,
        uv_python: str | None = None,
        app_module: str = "",
    ) -> None:

        arch_values = [a.value for a in archs]
        abi_filters = ", ".join(f'"{a}"' for a in arch_values)
        arch_list_kts = abi_filters
        ndk_line = f'    ndkVersion = "{ndk_version}"\n' if ndk_version else ""
        plugin_id = "com.android.library" if aar else "com.android.application"

        app_id_lines = (
            ""
            if aar
            else f'        applicationId = "{package_name}"\n'
            f"        versionCode = {version_code}\n"
            f'        versionName = "{version_name}"\n'
        )

        extra_deps = "".join(
            f'    implementation("{dep}")\n' for dep in (gradle_dependencies or [])
        )

        ndk_path_str = str(ndk_path).replace("\\", "/") if ndk_path else ""
        # The Swift Android SDK's artifact bundles only carry triples from API
        # 28 up; a lower minSdk is fine for the Java side but has no Swift
        # runtime to build against.
        # The bootstrap AAR declares minSdkVersion 28 (the Swift Android SDK's
        # floor), and AGP enforces it, so a lower min_api fails the build with a
        # message naming the AAR rather than crashing on a device.
        if min_sdk < 28:
            print(
                f"[ksproject] min_api {min_sdk} is below the bootstrap AAR's "
                "minSdkVersion 28; the Gradle build will reject it."
            )
        # No Swift is *compiled* here — the bootstrap ships prebuilt in the AAR —
        # but the Swift runtime is still staged from the installed SDK, because
        # the app's own Swift libraries (the nucleant wheel's .so) need it and
        # the AAR deliberately does not carry a second copy.
        swift_config = GradleBuildFiles._swift_runtime_config()
        build_tasks = GradleBuildFiles._swift_runtime_tasks(arch_values)
        build_tasks += GradleBuildFiles._site_packages_tasks(
            arch_list_kts, python_version, byte_compile_default, uv_python, app_module
        )
        build_tasks += GradleBuildFiles._post_build_task(post_build)

        template_path = project_dir / "build.tmpl.gradle.kts"

        default_template = """\
// ksproject-template: 5 — do not remove; the generator replaces this file when
// its own default is newer, keeping your copy as build.tmpl.gradle.kts.vN.bak.
plugins {
    id("{{ plugin_id }}")
}

{{ swift_config }}

android {
    namespace = "{{ package_name }}"
    compileSdk = {{ compile_sdk }}
{{ ndk_line }}    ndkPath = "{{ ndk_path }}"

    defaultConfig {
{{ app_id_lines }}        minSdk = {{ min_sdk }}
        targetSdk = {{ target_sdk }}

        ndk {
            abiFilters += setOf({{ abi_filters }})
        }
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("main") {
            assets.srcDir(layout.buildDirectory.dir("generated/python_assets").get().asFile)
            jniLibs.srcDir(layout.buildDirectory.dir("generated/jniLibs").get().asFile)
        }
    }

    // CPython stdlib and packages contain underscore-prefixed directories
    // (e.g. zipfile/_path) that AGP's default aapt ignore pattern strips.
    // Override to keep them.
    androidResources {
        ignoreAssetsPatterns.clear()
        ignoreAssetsPatterns.addAll(listOf(
            "!.svn", "!.git", "!.ds_store", "!*.scc",
            "!CVS", "!thumbs.db", "!picasa.ini", "!*~",
            "python*", "lib-dynload", "site-packages"
        ))
    }
}

dependencies {
    // libs/ carries the Nucleant bootstrap AAR: the JNI bridge, the CPython
    // launcher, org.nucleantui.NucleantActivity, and the Swift runtime this
    // app's Swift wheels need. Built separately — see the bootstrap library —
    // and destined to become a Maven coordinate.
    implementation(fileTree("libs") { include("*.aar", "*.jar") })
    // No swiftkit-core dependency: org.swift.swiftkit:swiftkit-core is not
    // published to any repository, so the classes jextract's output needs are
    // compiled into the bootstrap AAR itself.
{{ extra_deps }}
}

{{ build_tasks }}
"""
        template_content = _ensure_template(
            template_path, default_template, _BUILD_GRADLE_TEMPLATE_VERSION
        )

        build_content = template_content.replace("{{ plugin_id }}", plugin_id)
        build_content = build_content.replace("{{ package_name }}", package_name)
        build_content = build_content.replace("{{ compile_sdk }}", str(compile_sdk))
        build_content = build_content.replace("{{ ndk_line }}", ndk_line)
        build_content = build_content.replace("{{ ndk_path }}", ndk_path_str)
        build_content = build_content.replace("{{ app_id_lines }}", app_id_lines)
        build_content = build_content.replace("{{ min_sdk }}", str(min_sdk))
        build_content = build_content.replace("{{ target_sdk }}", str(target_sdk))
        build_content = build_content.replace("{{ abi_filters }}", abi_filters)
        build_content = build_content.replace("{{ extra_deps }}", extra_deps)
        build_content = build_content.replace("{{ swift_config }}", swift_config)
        build_content = build_content.replace("{{ build_tasks }}", build_tasks)

        (app_dir / "build.gradle.kts").write_text(build_content, encoding="utf-8")
        (app_dir / "libs").mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Swift build tasks
    # -------------------------------------------------------------------------

    @staticmethod
    def _swift_runtime_config() -> str:
        """Locates the installed Swift Android SDK.

        The app compiles no Swift, but it packages Swift libraries — the
        nucleant wheel's — and Android has no system Swift runtime, so the
        runtime has to come from somewhere. It comes from here, the same place it
        always did. The bootstrap AAR deliberately does not carry a second copy:
        with one toolchain installed, two copies is just two copies.

        Kotlin script top-level vals initialize in source order, so this has to
        precede the tasks that use it.
        """
        return """\
// ── Swift runtime ────────────────────────────────────────────────────────────
// Staged out of the installed Swift Android SDK into jniLibs. Nothing here is
// compiled; the bootstrap itself is a prebuilt AAR in libs/.

data class SwiftAbi(val runtimeDir: String, val ndkTriple: String)

val generatedJniLibsDir = layout.buildDirectory.dir("generated/jniLibs")

/**
 * Root holding the installed Android Swift SDK artifact bundles. Checked in the
 * order SwiftPM itself checks, so an SDK installed with `swift sdk install` is
 * found without configuration.
 */
fun swiftSdkRoot(): File {
    val configured =
        (project.findProperty("swift.sdk.path") as String?) ?: System.getenv("SWIFT_SDK_PATH")
    if (configured != null) return File(configured)

    val home = System.getProperty("user.home")
    val candidates = listOf(
        File(home, "Library/org.swift.swiftpm/swift-sdks"),
        File(home, ".config/swiftpm/swift-sdks"),
        File(home, ".swiftpm/swift-sdks")
    )
    return candidates.firstOrNull { it.isDirectory }
        ?: throw GradleException(
            "No Swift SDK directory found. Install the Android Swift SDK with " +
                "`swift sdk install <url>`, or set swift.sdk.path / SWIFT_SDK_PATH."
        )
}

/**
 * The SDK bundle to take the runtime from. Bundle names are date-stamped, so
 * lexicographic sort puts the newest last — the rule pyswiftkit-builder applies.
 *
 * It must be the toolchain that built the Swift libraries in the wheels and in
 * the bootstrap AAR: Swift's ABI is stable on Darwin only.
 */
fun swiftSdkBundle(): File {
    val root = swiftSdkRoot()
    val configured =
        (project.findProperty("swift.sdk") as String?) ?: System.getenv("SWIFT_ANDROID_SDK")
    if (configured != null) {
        val named = File(root, "$configured.artifactbundle")
        if (!named.isDirectory) {
            throw GradleException("Swift Android SDK not found: $named")
        }
        return named
    }
    val bundles = (root.listFiles() ?: emptyArray())
        .filter { it.isDirectory && it.name.endsWith("_android.artifactbundle") }
        .sortedBy { it.name }
    return bundles.lastOrNull()
        ?: throw GradleException(
            "No *_android.artifactbundle in $root. Install one with " +
                "`swift sdk install <url>`, or set swift.sdk / SWIFT_ANDROID_SDK."
        )
}

// Resolved lazily: without this a missing Swift SDK would fail *configuration*,
// so even `./gradlew tasks` would break on a machine that only wants to look.
val swiftSdkBundleProvider = providers.provider { swiftSdkBundle() }
// ─────────────────────────────────────────────────────────────────────────────"""

    @staticmethod
    def _swift_runtime_tasks(arch_values: list[str]) -> str:
        """Copy the Swift runtime into jniLibs/<abi>, once per ABI."""
        unsupported = [a for a in arch_values if a not in _SWIFT_ABIS]
        if unsupported:
            raise GradleBuildError(
                f"No Swift Android SDK runtime for arch(es) {unsupported}. "
                f"Supported: {sorted(_SWIFT_ABIS)}"
            )

        abi_entries = "\n".join(
            f'    "{abi}" to SwiftAbi("{_SWIFT_ABIS[abi][1]}", "{_SWIFT_ABIS[abi][2]}"),'
            for abi in arch_values
        )
        runtime_libs = ", ".join(f'"{lib}"' for lib in _SWIFT_RUNTIME_LIBS)

        return """
// ── Swift runtime staging ────────────────────────────────────────────────────

val swiftRuntimeAbis = mapOf(
{abi_entries}
)

val swiftRuntimeLibs = listOf({runtime_libs})

val copySwiftRuntime = tasks.register<Copy>("copySwiftRuntime") {
    group = "swift"
    description = "Stage the Swift runtime from the installed SDK into jniLibs/<abi>"

    duplicatesStrategy = DuplicatesStrategy.INCLUDE

    swiftRuntimeAbis.forEach { (abi, info) ->
        // filter{exists}: which runtime libs a bundle ships moves between
        // snapshots, and a missing one is not fatal here — it would have failed
        // at link time wherever it was actually needed.
        from(
            swiftSdkBundleProvider.map { bundle ->
                swiftRuntimeLibs.map { lib ->
                    File(
                        bundle,
                        "swift-android/swift-resources/usr/lib/${info.runtimeDir}/android/lib$lib.so"
                    )
                }.filter { it.exists() }
            }
        ) {
            into(abi)
        }

        // libc++_shared is an NDK library, not a Swift one, but the Swift
        // runtime links against it and Android ships no system copy.
        from(
            swiftSdkBundleProvider.map { bundle ->
                File(
                    bundle,
                    "swift-android/ndk-sysroot/usr/lib/${info.ndkTriple}/libc++_shared.so"
                )
            }
        ) {
            into(abi)
        }
    }

    into(generatedJniLibsDir)
}

tasks.named("preBuild") {
    dependsOn(copySwiftRuntime)
}

tasks.configureEach {
    if (name.startsWith("merge") && name.endsWith("JniLibFolders")) {
        dependsOn(copySwiftRuntime)
    }
}
// ─────────────────────────────────────────────────────────────────────────────
""".replace("{abi_entries}", abi_entries).replace("{runtime_libs}", runtime_libs)

    @staticmethod
    def _post_build_task(post_build: Path | None) -> str:
        """Gradle Exec task that runs the user's post_build hook against the
        staged app tree, after the staging tasks have populated
        src/main/{assets,jniLibs} and build/generated, but before AGP
        merges/packages it.

        This is the Gradle-native equivalent of the xcode post-build run_script
        phase: it executes inside the build process, not in the Python CLI.
        """
        if post_build is None:
            return ""

        script = str(post_build).replace("\\", "/")
        if post_build.suffix == ".py":
            command_line = f'commandLine("uv", "run", postBuildScript.absolutePath)'
        else:
            command_line = f"commandLine(postBuildScript.absolutePath)"

        return f"""
// ── post_build hook ──────────────────────────────────────────────────────────
// Runs the user's android.post_build script on the staged app content before
// AGP merges/packages it — the last point at which app content can be modified.
val ksprojectPostBuild = tasks.register<Exec>("ksprojectPostBuild") {{
    group = "python"
    description = "Run user post_build hook on staged app content before packaging"
    val appSrcRoot = rootProject.projectDir.parentFile.parentFile
    val postBuildScript = file("$appSrcRoot/{script}")
    workingDir = appSrcRoot
    environment("WHEELHOUSE", file("$appSrcRoot/wheelhouse").absolutePath)
    environment("APP_MAIN", file("src/main").absolutePath)
    {command_line}

    // Content must be fully staged before the hook runs.
    dependsOn(zipPythonAssets)
    dependsOn(copySwiftJniLibs)
    copySitePackagesNativeLibsTasks.forEach {{ dependsOn(it) }}
    dependsOn("copySitePackagesJava")
    dependsOn("copySitePackagesKotlin")
}}

// Make the packaging-input merge tasks wait for the hook, so its edits land
// inside the APK/AAR.
tasks.configureEach {{
    if (name.startsWith("merge") &&
        (name.endsWith("Assets") || name.endsWith("JniLibFolders"))) {{
        dependsOn(ksprojectPostBuild)
    }}
}}
// ─────────────────────────────────────────────────────────────────────────────"""

    @staticmethod
    def _site_packages_tasks(
        arch_list_kts: str,
        python_version: str,
        byte_compile_default: bool,
        uv_python: str | None = None,
        app_module: str = "",
    ) -> str:
        kt_bool = str(byte_compile_default).lower()
        # Byte-compile with a uv-managed interpreter pinned to the bundled
        # runtime's version so .pyc magic numbers match; bare python3 would
        # use whatever the host happens to have.
        uv_py = uv_python or python_version
        return f"""\
abstract class OptimizePythonTask : DefaultTask() {{
    @get:Input
    abstract val shouldCompile: Property<Boolean>

    @get:Input
    abstract val targetPath: Property<String>

    @get:Input
    abstract val ndkDir: Property<String>

    // The app's own top-level package. junkDirs below is a size heuristic aimed
    // at dependencies, and it matches on bare directory name anywhere in the
    // tree — so an app package with an `examples/` (or `tests/`, `bin/`, ...)
    // subpackage would have its own source deleted and fail at import. Nothing
    // under this directory is ever "junk".
    @get:Input
    abstract val protectedPackage: Property<String>

    @TaskAction
    fun runOptimization() {{
        val path = targetPath.get()
        val dir = File(path)
        if (!dir.exists()) return

        val doCompile = shouldCompile.get()

        if (doCompile) {{
            ProcessBuilder("uv", "run", "--no-project", "--python", "{uv_py}", "python", "-m", "compileall", "-b", "-o", "2", "-j", "0", "-q", path)
                .redirectErrorStream(true)
                .start()
                .waitFor()
        }}

        val junkExts = mutableListOf(".pyi", ".c", ".cpp", ".h", ".pyx", ".pxd", ".md", ".rst")
        if (doCompile) {{
            junkExts.add(".py")
        }}

        val junkDirs = setOf("tests", "test", "docs", "doc", "examples", "example", "tutorials", "benchmarks", "perf", ".mypy_cache", ".pytest_cache", "__pycache__", "bin", "unittest")
        val allFiles = dir.walkBottomUp().toList()

        allFiles.parallelStream().forEach {{ f ->
            if (f.isFile && junkExts.any {{ ext -> f.name.endsWith(ext) }}) {{
                f.delete()
            }}
        }}

        // Matched on ancestry rather than a fixed root: this task's directory is
        // the staging root, and the app package sits under
        // site-packages/<abi>/ inside it, not directly beneath.
        val protectedName = protectedPackage.get()

        allFiles.forEach {{ f ->
            if (f.isDirectory && junkDirs.contains(f.name) && f.exists()) {{
                val isAppOwn = protectedName.isNotEmpty() &&
                    generateSequence(f.parentFile) {{ it.parentFile }}
                        .any {{ it.name == protectedName }}
                if (!isAppOwn) {{
                    f.deleteRecursively()
                }}
            }}
        }}

        val os = org.gradle.internal.os.OperatingSystem.current()
        val hostTag = if (os.isWindows) "windows-x86_64" else if (os.isMacOsX) "darwin-x86_64" else "linux-x86_64"
        val stripExe = if (os.isWindows) "llvm-strip.exe" else "llvm-strip"
        val stripTool = File(ndkDir.get(), "toolchains/llvm/prebuilt/$hostTag/bin/$stripExe")

        if (stripTool.exists()) {{
            val soFiles = dir.walkTopDown().filter {{ it.isFile && it.name.endsWith(".so") }}.toList()
            soFiles.parallelStream().forEach {{ f ->
                ProcessBuilder(stripTool.absolutePath, "--strip-unneeded", f.absolutePath)
                    .start()
                    .waitFor()
            }}
        }}
    }}
}}

val sitePackagesAbis = listOf({arch_list_kts})
val stagingDir = layout.buildDirectory.dir("python_assets_staging").get().asFile
val assetsDir = layout.projectDirectory.dir("src/main/assets")
val generatedAssetsDir = layout.buildDirectory.dir("generated/python_assets").get().asFile

val stagePythonTasks = sitePackagesAbis.map {{ abi ->
    tasks.register<Copy>("stagePython_${{abi}}") {{
        group = "python"

        val sitePackDir = layout.projectDirectory.dir("../site_packages/$abi")
        from(sitePackDir) {{
            exclude(".libs/**", ".java/**", ".kotlin/**", ".gradle/**")
            into("site-packages/$abi")
        }}

        from(assetsDir.dir("python{python_version}")) {{
            into("python{python_version}")
        }}

        from(assetsDir.dir("lib-dynload")) {{
            into("lib-dynload")
        }}

        into(stagingDir)
    }}
}}

val optimizeStagedTasks = sitePackagesAbis.map {{ abi ->
    tasks.register<OptimizePythonTask>("optimizeStaged_${{abi}}") {{
        group = "python"
        dependsOn("stagePython_${{abi}}")

        val isCmdLineForced = project.hasProperty("forceCompile")
        val isReleaseBuild = gradle.startParameter.taskNames.any {{
            it.contains("Release", ignoreCase = true)
        }}
        val androidExt = project.extensions.getByType(com.android.build.gradle.BaseExtension::class.java)

        shouldCompile.set(isReleaseBuild || isCmdLineForced || {kt_bool})
        targetPath.set(stagingDir.absolutePath)
        ndkDir.set(androidExt.ndkDirectory.absolutePath)
        protectedPackage.set("{app_module}")
    }}
}}

val zipPythonAssets = tasks.register<Zip>("zipPythonAssets") {{
    group = "python"
    dependsOn(optimizeStagedTasks)

    archiveFileName.set("assets.zip")
    destinationDirectory.set(generatedAssetsDir)

    from(stagingDir) {{
        include("**/*")
    }}

    entryCompression = ZipEntryCompression.DEFLATED
}}

tasks.register<Copy>("copySitePackagesJava") {{
    group = "python"
    description = "Copy .java sources from site-packages into the app java source set"
    val srcDir = sitePackagesAbis.map {{ layout.projectDirectory.dir("../site_packages/$it/.java").asFile }}.firstOrNull {{ it.exists() }}
    if (srcDir != null) {{
        from(srcDir)
        into("src/main/java")
    }}
}}

tasks.register<Copy>("copySitePackagesKotlin") {{
    group = "python"
    description = "Copy .kotlin sources from site-packages into the app kotlin source set"
    val srcDir = sitePackagesAbis.map {{ layout.projectDirectory.dir("../site_packages/$it/.kotlin").asFile }}.firstOrNull {{ it.exists() }}
    if (srcDir != null) {{
        from(srcDir)
        into("src/main/kotlin")
    }}
}}

val copySitePackagesNativeLibsTasks = sitePackagesAbis.map {{ abi ->
    tasks.register<Copy>("copySitePackagesNativeLibs_${{abi}}") {{
        group = "python"
        description = "Copy .libs/$abi native libraries into jniLibs/$abi"
        val srcPath = layout.projectDirectory.dir("../site_packages/$abi/.libs/$abi").asFile.absolutePath
        onlyIf {{ File(srcPath).exists() }}
        from(srcPath) {{
            include("*.so")
        }}
        into("src/main/jniLibs/$abi")
    }}
}}

tasks.named("preBuild") {{
    dependsOn(zipPythonAssets)
    copySitePackagesNativeLibsTasks.forEach {{ dependsOn(it) }}
    dependsOn("copySitePackagesJava")
    dependsOn("copySitePackagesKotlin")
}}

tasks.configureEach {{
    if (name.contains("Assets") && name != "zipPythonAssets") {{
        dependsOn(zipPythonAssets)
    }}
}}
"""

    # -------------------------------------------------------------------------
    # AndroidManifest
    # -------------------------------------------------------------------------

    @staticmethod
    def write_android_manifest(
        main_dir: Path,
        package_name: str,
        project_dir: Path,
        app_name: str,
        permissions: list[str] | None = None,
        meta_data: dict[str, str] | None = None,
        services: list["AndroidProtocol.ServiceData"] | None = None,
        entrypoint: str | None = None,
        presplash_name: str | None = None,
        presplash_type: str | None = None,
        presplash_color: str | None = None,
    ) -> None:
        """The manifest, including the meta-data the bootstrap AAR reads.

        ``org.nucleantui.NucleantActivity`` is compiled once for every app, so
        what is per-app reaches it as manifest meta-data rather than as generated
        constants — the same arrangement SDL uses.  MainActivity overrides
        ``getEntryPoint()`` as well, and that wins; the meta-data is what a
        subclass gets for free if it does not.
        """
        activity_meta = {}
        if entrypoint:
            activity_meta["org.nucleantui.entrypoint"] = entrypoint
        if presplash_name:
            activity_meta["org.nucleantui.presplash"] = presplash_name
            activity_meta["org.nucleantui.presplash.type"] = presplash_type or "image"
            activity_meta["org.nucleantui.presplash.color"] = presplash_color or "#FFFFFF"
        activity_meta_lines = "".join(
            f'\n            <meta-data android:name="{k}" android:value="{v}" />'
            for k, v in activity_meta.items()
        )

        perm_lines = "\n".join(
            f'    <uses-permission android:name="android.permission.{p}" />'
            for p in (permissions or ["INTERNET"])
        )

        meta_lines = "".join(
            f'\n        <meta-data android:name="{k}" android:value="{v}" />'
            for k, v in (meta_data or {}).items()
        )

        service_lines = ""
        if services:
            for svc in services:
                fg_type = (
                    f'\n            android:foregroundServiceType="{svc.foreground_service_type}"'
                    if svc.foreground_service_type
                    else ""
                )
                service_lines += f"""
        <service
            android:name=".{svc.name}"
            android:exported="false"
            android:process=":{svc.name.lower()}"{fg_type}>
        </service>"""

        template_path = project_dir / "AndroidManifest.tmpl.xml"

        default_template = """\
<?xml version="1.0" encoding="utf-8"?>
<!-- ksproject-template: 2 — do not remove; the generator replaces this file when
     its own default is newer, keeping your copy as AndroidManifest.tmpl.xml.vN.bak. -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

{{ permissions }}

    <!-- Vulkan 1.1 is the floor Nucleant renders against; below it the app has
         no rendering path at all, so keep it off those devices in the store. -->
    <uses-feature android:name="android.hardware.vulkan.version"
        android:version="0x401000"
        android:required="true" />

    <application
        android:label="{{ app_name }}"
        android:icon="@mipmap/ic_launcher"
        android:allowBackup="true"
        android:supportsRtl="true"
        android:hardwareAccelerated="true"
        android:theme="@android:style/Theme.DeviceDefault.NoActionBar">{{ meta_data }}
{{ services }}
        <activity
            android:name=".MainActivity"
            android:label="{{ app_name }}"
            android:configChanges="mcc|mnc|locale|touchscreen|keyboard|keyboardHidden|navigation|orientation|screenLayout|fontScale|uiMode|screenSize|smallestScreenSize|layoutDirection|density|colorMode|fontWeightAdjustment|grammaticalGender"
            android:theme="@android:style/Theme.DeviceDefault.NoActionBar"
            android:exported="true">{{ activity_meta_data }}
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""
        template_content = _ensure_template(
            template_path, default_template, _MANIFEST_TEMPLATE_VERSION
        )

        manifest_content = template_content.replace("{{ app_name }}", app_name)
        manifest_content = manifest_content.replace("{{ permissions }}", perm_lines)
        manifest_content = manifest_content.replace("{{ meta_data }}", meta_lines)
        manifest_content = manifest_content.replace("{{ services }}", service_lines)
        if "{{ activity_meta_data }}" in manifest_content:
            manifest_content = manifest_content.replace(
                "{{ activity_meta_data }}", activity_meta_lines
            )
        elif activity_meta_lines:
            # A template written before the bootstrap moved into the AAR. The
            # entry point still works (MainActivity overrides getEntryPoint),
            # but anything read only from meta-data — the presplash — will not.
            print(
                "[ksproject] AndroidManifest.tmpl.xml has no {{ activity_meta_data }} "
                "placeholder; add it inside the <activity> tag to configure the "
                "bootstrap (presplash) from the manifest."
            )

        (main_dir / "AndroidManifest.xml").write_text(
            manifest_content, encoding="utf-8"
        )

    # -------------------------------------------------------------------------
    # Icon
    # -------------------------------------------------------------------------

    @staticmethod
    def write_icon(res_dir: Path, icon_src: Path) -> None:
        mipmap_dir = res_dir / "mipmap"
        mipmap_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, mipmap_dir / "ic_launcher.png")

    # -------------------------------------------------------------------------
    # MainActivity.java — a subclass of the AAR's NucleantActivity
    # -------------------------------------------------------------------------

    @staticmethod
    def write_main_activity(
        main_dir: Path,
        package_name: str,
        python_module: str,
    ) -> None:
        """A thin subclass of the bootstrap AAR's Activity.

        Everything that used to be generated here — asset unpacking, the
        environment exports, the presplash, the Python thread — now lives in
        ``org.nucleantui.NucleantActivity``, compiled once into the bootstrap
        AAR the way ``org.libsdl.app.SDLActivity`` is.  What is left is a place
        for an app's own Java, and the entry point.

        The entry point is stated twice on purpose: as manifest meta-data, which
        is what the base class reads by default, and as an override here, which
        is what an app author sees on opening the file.  The override wins, so
        editing this one file is enough.
        """
        java_dir = main_dir / "java" / Path(*package_name.split("."))
        java_dir.mkdir(parents=True, exist_ok=True)

        module_name = (
            str(python_module).strip().replace("-", "_").replace(".", "_").replace(" ", "_")
        )

        content = f"""\
package {package_name};

import org.nucleantui.NucleantActivity;

/**
 * This app's Activity.
 *
 * <p>Everything that starts a Nucleant app — unpacking the Python tree, the
 * environment, the render surface, the interpreter thread — lives in
 * {{@link NucleantActivity}}, which ships prebuilt in the bootstrap AAR. This
 * class exists so there is somewhere to put Java of your own.
 *
 * <p>Regenerating the project overwrites this file. Every startup step is a
 * protected hook on the base class:
 *
 * <pre>{{@code
 * protected void onPythonStarting() {{
 *     super.onPythonStarting();
 *     // permissions, billing, anything that must happen before Python runs
 * }}
 *
 * protected void onSetupEnvironment(File appDir) {{
 *     super.onSetupEnvironment(appDir);
 *     setEnv("MY_FLAG", "1");
 * }}
 * }}</pre>
 *
 * <p>See also onCreateSurfaceView(), onCreatePresplashView() and
 * onPythonExited(int).
 */
public class MainActivity extends NucleantActivity {{

    /**
     * The Python module run as {{@code __main__}}, from pyproject's project
     * name. The manifest carries the same value as
     * {{@code org.nucleantui.entrypoint}} meta-data; this override is the one
     * that wins.
     */
    @Override
    protected String getEntryPoint() {{
        return "{module_name}";
    }}
}}
"""
        (java_dir / "MainActivity.java").write_text(content, encoding="utf-8")


    # -------------------------------------------------------------------------
    # Per-service subclasses generated from pyproject
    # -------------------------------------------------------------------------

    @staticmethod
    def write_custom_service(
        main_dir: Path,
        package_name: str,
        service_name: str,
        python_version: str,
        entrypoint: str,
        foreground: bool,
        start_type: str = "START_NOT_STICKY",
        notification_title: str | None = "",
        notification_text: str | None = "",
        notification_icon: str = "stat_notify_sync",
    ) -> None:
        java_dir = main_dir / "java" / Path(*package_name.split("."))
        java_dir.mkdir(parents=True, exist_ok=True)

        start_type_constant = start_type.upper()
        is_sticky_bool_str = (
            "true" if start_type_constant == "START_STICKY" else "false"
        )
        foreground_str = "true" if foreground else "false"

        title = notification_title or f"{service_name} is running"
        text = notification_text or "Background task active"

        # A stable, unique notification id per service, fixed at generation
        # time so a restart reuses the same notification instead of stacking.
        unique_service_id = (
            zlib.crc32(service_name.lower().encode("utf-8")) % 10000
        ) + 1

        foreground_logic = ""
        if foreground:
            foreground_logic = f"""
        String channelId = "{package_name}.{service_name}";
        NotificationChannel channel = new NotificationChannel(
            channelId,
            "{service_name} Channel",
            NotificationManager.IMPORTANCE_LOW
        );
        NotificationManager manager =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {{
            manager.createNotificationChannel(channel);
        }}

        int iconId = getResources().getIdentifier("{notification_icon}", "drawable", "android");
        if (iconId == 0) {{
            iconId = android.R.drawable.stat_notify_sync;
        }}

        // A title passed in the Intent (started from Python) wins over the
        // generated default, which is what the system's own restart uses.
        String finalTitle = intent.hasExtra("serviceTitle")
                ? intent.getStringExtra("serviceTitle") : "{title}";
        String finalText = intent.hasExtra("serviceDescription")
                ? intent.getStringExtra("serviceDescription") : "{text}";

        Notification notification = new Notification.Builder(this, channelId)
            .setContentTitle(finalTitle)
            .setContentText(finalText)
            .setSmallIcon(iconId)
            .build();

        startForeground({unique_service_id}, notification);

        // Already foregrounded here; stop the base class doing it again.
        intent.putExtra("serviceStartAsForeground", "false");
"""

        content = f"""\
package {package_name};

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import org.nucleantui.NucleantService;

public class {service_name} extends NucleantService {{

    @Override
    public int startType() {{
        return {start_type_constant};
    }}

    @Override
    protected int getServiceId() {{
        return {unique_service_id};
    }}

    @Override
    protected Intent getThisDefaultIntent(Context ctx, String pythonServiceArgument) {{
        Intent intent = new Intent(ctx, {service_name}.class);
        intent.putExtra("androidPrivate", ctx.getFilesDir().getAbsolutePath());
        intent.putExtra("serviceEntrypoint", "{entrypoint}");
        intent.putExtra("pythonVersion", "{python_version}");
        intent.putExtra("pythonName", "{service_name.lower()}");
        intent.putExtra("pythonServiceArgument", pythonServiceArgument);

        // Fallbacks for when the system auto-restarts the service and there is
        // no caller to supply them.
        intent.putExtra("serviceTitle", "{title}");
        intent.putExtra("serviceDescription", "{text}");
        intent.putExtra("serviceStartAsForeground", "{foreground_str}");

        return intent;
    }}

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {{
        if (intent == null || intent.getExtras() == null || !intent.hasExtra("serviceEntrypoint")) {{
            intent = getThisDefaultIntent(getApplicationContext(), "");
        }} else {{
            if (!intent.hasExtra("serviceTitle")) {{
                intent.putExtra("serviceTitle", "{title}");
            }}
            if (!intent.hasExtra("serviceDescription")) {{
                intent.putExtra("serviceDescription", "{text}");
            }}
        }}
        {foreground_logic}
        setAutoRestartService({is_sticky_bool_str});

        return super.onStartCommand(intent, flags, startId);
    }}

    /** Start with the generated notification defaults. */
    public static void start(Context ctx, String pythonServiceArgument) {{
        start(ctx, "{notification_icon}", "{title}", "{text}", pythonServiceArgument);
    }}

    /** Start with a caller-supplied icon, title and text. */
    public static void start(Context ctx, String smallIconName, String contentTitle,
                             String contentText, String pythonServiceArgument) {{
        Intent intent = new Intent(ctx, {service_name}.class);
        intent.putExtra("androidPrivate", ctx.getFilesDir().getAbsolutePath());
        intent.putExtra("serviceEntrypoint", "{entrypoint}");
        intent.putExtra("pythonVersion", "{python_version}");
        intent.putExtra("pythonName", "{service_name.lower()}");
        intent.putExtra("serviceTitle", contentTitle);
        intent.putExtra("serviceDescription", contentText);
        intent.putExtra("smallIconName", smallIconName);
        intent.putExtra("pythonServiceArgument", pythonServiceArgument);
        intent.putExtra("serviceStartAsForeground", "{foreground_str}");

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            ctx.startForegroundService(intent);
        }} else {{
            ctx.startService(intent);
        }}
    }}

    public static void stop(Context ctx) {{
        ctx.stopService(new Intent(ctx, {service_name}.class));
    }}
}}
"""
        (java_dir / f"{service_name}.java").write_text(content, encoding="utf-8")
