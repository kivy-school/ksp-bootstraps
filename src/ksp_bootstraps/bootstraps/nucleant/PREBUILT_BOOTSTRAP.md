# Shipping the bootstrap as a prebuilt AAR

The bootstrap package is a SurfaceView handoff and a Python launcher — two
source files, ~2 MB of compiled output. Getting them currently costs every app
project a full SwiftPM graph: swift-java, swift-syntax, swift-argument-parser,
swift-collections, a host build of the jextract plugin, and one cross-compile
per ABI. See [BUILD_TIME.md](BUILD_TIME.md) for the measurements.

This document is the design for building it **once** and publishing an AAR, so
an app's Gradle build compiles no Swift at all.

Written 2026-08-01 against Swift 6.3.3, swift-java 0.4.2.

## Why an AAR and not a Swift `.artifactbundle`

The deciding fact: **nothing in an app build links `libNucleantMain.so` at
compile time.** Gradle copies it into `jniLibs/<abi>/`, `MainActivity` reaches it
through `System.loadLibrary`, and the Nucleant wheel finds its hooks with `dlsym`
at runtime (see the host-seam comment in `AndroidSurface.swift`). No Swift
compiler and no linker on the consuming side ever opens it.

So the bundle needs no `.swiftmodule`, `.swiftinterface`, module map, or headers.
It carries runtime artifacts and one Java class — and its consumer is AGP, not
SwiftPM.

That rules out `.binaryTarget`, which accepts an XCFramework (Apple only) or an
`.artifactbundle` of **executables**; there is no artifact type for an Android
dynamic library and no way to say "link this prebuilt `.so`" from
`Package.swift`. An artifactbundle *layout* would work as a plain zip we unpack
ourselves, but it earns nothing here: we would be hand-writing variant
selection, caching, and checksum verification that Gradle already does. Keep the
artifactbundle reader for Swift SDK bundles, where it is actually required.

An AAR gives, for free, four things the zip would cost us code:

- `jni/<abi>/*.so` is merged into the APK by AGP, honouring the app's
  `abiFilters` — no copy task, no `jniLibs.srcDir` wiring, no variant selection.
- `classes.jar` carries the `NucleantMain` class — no `java.srcDir` pointed into
  a plugin output directory, no `outputs.dir` dance to stop `compileJava` racing
  the Swift build.
- Maven coordinates give version resolution, caching, and checksum verification.
- The AAR's own `AndroidManifest.xml` can carry `<uses-sdk
  android:minSdkVersion="28">`, and **AGP enforces it**. The Swift Android SDK's
  API-28 floor stops being a comment in `write_app_build_gradle` and becomes a
  build error naming the offending module.

Not Prefab: that exists so a native build can compile *against* a prebuilt
(headers + link libs), which nothing here does. Plain `jni/` is correct.

## Contents

Per ABI (`arm64-v8a` and `x86_64` — the only two ksp_bootstraps defines):

- `libNucleantMain.so` — the bootstrap, with jextract's JNI glue compiled in.
- The Swift runtime set from `_SWIFT_RUNTIME_LIBS`: `libswiftCore`,
  `libswift_Concurrency`, `libswift_StringProcessing`, `libswift_RegexParser`,
  `libswift_Builtin_float`, `libswift_math`, `libswiftAndroid`, `libdispatch`,
  `libBlocksRuntime`, `libswiftSwiftOnoneSupport`, `libswiftDispatch`,
  `libFoundation`, `libFoundationEssentials`,
  `libFoundationInternationalization`, `lib_FoundationICU`,
  `libswiftSynchronization`.
- `libc++_shared.so` — NDK, not Swift, but the runtime links it and Android ships
  no system copy.

Once, ABI-independent:

- The compiled `NucleantMain` class. Generated from Swift *declarations*, so it
  is identical for every ABI.

Not in the AAR: `python_include/` (build-time only), `libpython3.so` (the app
ships CPython), sources, `Package.swift`.

### The runtime ships inside the AAR — not sourced locally

Swift's ABI is stable on Darwin only. On Android there is no stable ABI and no
system runtime, so `libNucleantMain.so` must be paired with the exact runtime it
was compiled against. Do not publish the `.so` and let the app copy runtime
libraries out of whatever Swift SDK bundle happens to be installed locally —
that is a symbol-version crash waiting for a toolchain bump. The AAR owns both
halves, and the source-build path is the only one that reads a local SDK.

Ship stripped `.so`s; publish the unstripped ones as a separate
`-symbols` artifact for symbolication.

## Layout

```
nucleant-bootstrap-<version>.aar
  AndroidManifest.xml        package + <uses-sdk minSdkVersion="28"/>, nothing else
  classes.jar                org/nucleantui/NucleantMain.class
  jni/
    arm64-v8a/               libNucleantMain.so + runtime + libc++_shared.so
    x86_64/…
```

The manifest is otherwise empty: no permissions, no components. The Activity,
SurfaceView and Service stay generated into the app, because they are the part
users are expected to read and modify. Only the JNI bridge is prebuilt.

## Coordinates and compatibility

`libNucleantMain.so` resolves CPython symbols at load time against whatever
`libpython3.so` the app ships, and it is bound to the Swift toolchain that built
it. Neither is expressible as a Gradle version constraint, so both go in the
identity:

```
org.nucleantui:nucleant-bootstrap-py313:<nucleant version>
```

Python minor in the artifactId — a 3.14 app then gets a "not found" at
resolution instead of a `dlopen` failure on device. Swift toolchain and ABI set
go in the POM/module metadata as informational attributes; the AAR is rebuilt on
a toolchain bump and gets a new version.

Full compatibility key, for anything that needs to check it:
`nucleant version × python minor × swift toolchain × min API level × ABI set`.

## What has to stop being app-specific

Three values are baked into generated source today. Until they are out, one AAR
cannot serve two apps.

| what | where | fix |
| --- | --- | --- |
| Java package | `swift-java.config`: `"javaPackage": "<applicationId>.swift"` | **the blocker.** It lands in the generated class name *and* in every JNI symbol (`Java_org_example_nucleantapptest_swift_NucleantMain_…`). Pin it to a constant — `org.nucleantui` — independent of `applicationId`. |
| app module | `{{ app_module }}` in `PythonBootstrap.swift` | read `ANDROID_ENTRYPOINT`, which `MainActivity` already exports; keep `nucleantSetAppModule` as the override. Drop the baked default. |
| Python version | `{{ python_version }}`, used only as the `python3.13/` path fragment | keyed by artifactId (above), or derive at runtime by globbing `<appPath>/python3.*`. |

Nothing else in the Swift is app-specific: `appPath` already arrives from Java,
and the surface and input entry points are pure.

Fixing the Java package changes the generated Java's imports from
`<applicationId>.swift.NucleantMain` to `org.nucleantui.NucleantMain` in
`MainActivity`, `NucleantSurfaceView` and `NucleantService` — a template change
in `gradle_build_files.py`, and worth doing on its own merits: today, renaming an
app changes the identity of its Java bridge.

## Production

One CI job per release, matrix over ABI:

1. `swift build -c release --swift-sdk <triple> -Xcc -I<python_include>/<abi> -Xswiftc -L<libpython dir>` — the invocation `_swift_tasks` builds today.
2. Take `libNucleantMain.so` from `.build/<triple>/release/`, strip it.
3. Take the runtime set from the Swift SDK bundle
   (`swift-android/swift-resources/usr/lib/<runtimeDir>/android/`) and
   `libc++_shared.so` from `swift-android/ndk-sysroot/usr/lib/<ndkTriple>/` — the
   paths `copySwiftJniLibs` already uses.
4. Take jextract's Java from
   `.build/plugins/outputs/swift/NucleantMain/destination/JExtractSwiftPlugin/src/generated/java/`
   once, from any ABI, and compile it into `classes.jar`.
5. Assemble the AAR, publish.

CPython enters at step 1: the link needs `libpython3.so` per ABI, so CI stages
the CPython Android build it links against — and that build's ABI is part of the
AAR's identity, which is what the artifactId encodes.

The cleanest way to build the AAR is a Gradle `com.android.library` module that
consumes the outputs of steps 2-4, since that produces a correct AAR and POM
without hand-assembling a zip. That module is the one place the current
`_swift_config` / `_swift_tasks` Kotlin keeps living.

## Consumption

`ksproject` gains a bootstrap-source selector, defaulting to prebuilt:

- **prebuilt (default)** — no `app/swift/` tree is generated at all. The app
  module gets one line:

  ```kotlin
  implementation("org.nucleantui:nucleant-bootstrap-py313:<version>")
  ```

  and `buildSwiftAll`, `copySwiftJniLibs`, `swiftGeneratedJavaDir`,
  `swiftSdkBundleProvider` and the whole `{{ swift_config }}` block drop out of
  the generated `build.gradle.kts`. The Swift Android SDK stops being a
  prerequisite for building an app.
- **from source (a flag)** — what happens today: generate the package, build it
  per ABI. Required for anyone changing the bootstrap, and it is the reference
  the prebuilt is checked against.

Fall back to the source build, loudly, when no AAR matches — an unsupported ABI,
a Python minor with no release yet, an air-gapped machine. The source path is
guaranteed to exist, since it is how the AAR was produced.

Worth having as a CI check, because the whole scheme rests on the prebuilt being
substitutable: build both ways and compare the exported symbol tables of the two
`libNucleantMain.so` (`nm -D --defined-only`). They should differ only in
build-id.

## What is left in the app build

Gradle resolves one dependency, AGP merges its `jni/` into the APK, and the
Python side (assets, wheels, site-packages staging) runs unchanged. No SwiftPM,
no swift-syntax, no jextract, no `--swift-sdk` cross-compile, no swift-java
clone, no Swift toolchain requirement.
