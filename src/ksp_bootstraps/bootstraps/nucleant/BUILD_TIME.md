# Cutting the Android bootstrap's build time

Notes on why `app/swift/` is slow to build and what can be done about it, in
rough order of payoff. Written 2026-08-01 against Swift 6.3.3 (host
`x86_64-unknown-linux-gnu`), swift-java 0.4.2, NucleantAppTest.

## Where the time actually goes

Measured from `NucleantAppTest/project_dist/gradle/app/swift/.build` after a
build for one ABI (`aarch64-unknown-linux-android28`):

| directory | size | what it is |
| --- | --- | --- |
| `index-build/` | 859 MB | the editor's background index build — a *second* full build of the graph |
| `x86_64-unknown-linux-gnu/` | 126 MB | **host** build: the jextract plugin executable and swift-syntax |
| `repositories/` | 84 MB | git clones of swift-java, swift-syntax, swift-argument-parser, swift-collections |
| `checkouts/` | 43 MB | working copies of the above |
| `aarch64-unknown-linux-android28/` | 2.2 MB | the actual cross-compiled bootstrap |

The thing being shipped is the 2.2 MB. Everything above it is toolchain.

Three structural facts follow from that table:

1. **The per-ABI cost is not trivial — corrected 2026-08-01.** The *target* build
   is ~2 MB, but the host side is not shared across triples the way the directory
   layout suggests: building `swift/` for arm64 and then x86_64 in one scratch
   directory recompiles swift-syntax, ArgumentParser and JExtractSwiftLib for the
   second destination, observed in a two-ABI run. So the expensive part is paid
   per ABI, not once per package. Building one ABI while iterating is worth real
   minutes.
2. **The package lives inside `project_dist/`**, which is generated output. Wipe
   or regenerate it, or start a new app, and swift-syntax is cloned and rebuilt
   from scratch. This is the "took ages" case.
3. **The editor doubles it.** `index-build/` is SourceKit-LSP preparing the same
   graph for indexing (VS Code's Swift extension does this when a file in the
   package is opened). It is larger than the real build.

`--enable-experimental-prebuilts` is already the default in 6.3.3 and does not
help here: it substitutes prebuilt swift-syntax **for macros**, and jextract
consumes swift-syntax as a plugin *executable* dependency, not a macro.

## Quick wins, no design change

These are all in `gradle_build_files.py` (`_swift_tasks`) unless noted.

- **Share one SwiftPM scratch path across app projects.** Add
  `--scratch-path <shared dir>` to the `swift build` args — e.g.
  `${XDG_CACHE_HOME:-~/.cache}/nucleant/swiftpm/<package-fingerprint>`. The host
  build, checkouts and repositories then survive `project_dist` regeneration and
  are reused by every app on the machine. This is the single biggest lever short
  of shipping binaries, and it is a one-line change. Fingerprint by
  `Package.resolved`'s hash so a dependency bump gets a fresh directory instead
  of a stale one. Path must come from an env var with per-OS probing, never a
  literal.
- **Stop the Gradle build from writing an index store**: pass
  `--disable-index-store`. Gradle never reads it; only the editor does, and the
  editor maintains its own under `index-build/`.
- **Keep the editor off the generated package** if indexing it is not useful —
  it is generated code, and 859 MB of index build is the price of navigating it.
  VS Code: exclude `project_dist/**` from the Swift extension's workspace, or
  don't open files under it.
- **Build only the ABI being debugged.** `swiftAbis` is driven by `abiFilters`;
  a `swift.abis` Gradle property that subsets it for local builds keeps release
  builds fat and dev builds thin.
- **Pin swift-java exactly.** `Package.swift` says `from: "0.1.2"` and
  `Package.resolved` has 0.4.2 — so a dependency the comment describes as 0.1.2
  is silently four minor versions ahead, and any resolution refresh can move it
  again and invalidate the host build. Use `.exact(...)` or
  `upToNextMinor(from:)`, and fix the stale comment on `SWIFT_JAVA_VERSION`.
- **Add `Package.resolved` to the task inputs.** The per-ABI `buildSwift<Abi>`
  tasks already declare `inputs.file(Package.swift)`, `inputs.dir(Sources)` and
  `outputs.dir(.build/<triple>/<config>)`, so they are up-to-date-checked.
  `Package.resolved` is missing from that list, which means a dependency bump
  does not invalidate them. `buildSwiftAll` is an aggregator with only
  `outputs.dir(...)`, which is correct for what it does.

## Route A — prebuilt jextract as an `.artifactbundle`

This is the artifactbundle idea, aimed at the right target: **the tool, not the
library.**

`.artifactbundle` + `.binaryTarget` supports *executables* cross-platform (it is
how swiftlint and swift-format ship as plugins). A plugin's tool may be a
binary target, so:

1. Build swift-java's jextract executable once per host platform
   (`linux-x86_64`, `linux-aarch64`, `macos-arm64`, …).
2. Package them as `jextract.artifactbundle` with an `info.json` mapping each
   variant to its triple.
3. Publish it (GitHub release asset, or vendored under ksp-bootstraps).
4. Declare a local plugin in the generated `Package.swift` whose tool is
   `.binaryTarget(name: "jextract", url:/path:, checksum:)`, invoking it with the
   same arguments `JExtractSwiftPlugin` passes today.

Result: swift-syntax never builds on a user's machine, the swift-java package
dependency (and its three transitive clones) disappears from the graph, and the
generated Java is still generated — no hand-written JNI. The `SwiftJava` runtime
module is still needed for `JavaObject` in `AndroidSurface.swift`, so that one
product dependency stays; it is small and has no swift-syntax edge.

Cost: we own a plugin declaration and a release process for the bundle, and the
bundle must track the swift-java version whose generated code we expect.

**Unverified:** that the generated JNI-mode Java/Swift glue is byte-identical
whichever way jextract is invoked, and the exact argument vector
`JExtractSwiftPlugin` uses. Read the plugin source in
`.build/checkouts/swift-java/Plugins/` before committing to this.

## Route B — ship the bootstrap as a prebuilt AAR

Designed in full in [PREBUILT_BOOTSTRAP.md](PREBUILT_BOOTSTRAP.md); summarised
here for comparison.

The end state: the app's Gradle build compiles **no Swift at all**.

An `.artifactbundle` cannot express this — it carries executables (and
XCFrameworks on Apple), not Android dynamic libraries, and nothing in an app
build links the bootstrap at compile time anyway. The Android form of a prebuilt
is an **AAR**: `jni/<abi>/libNucleantMain.so` plus the Swift runtime `.so`s, plus
the compiled `NucleantMain` class. The app declares
`implementation("org.nucleantui:nucleant-bootstrap-py313:<version>")` and the whole
`app/swift/` tree, the SwiftPM dependency graph and the per-ABI `swift build`
vanish from the app build.

For that to work the bootstrap has to stop being app-specific. Today two things
bake the app into it:

- **The app module name**, via `{{ app_module }}` in `PythonBootstrap.swift`.
  Already solvable: `nucleantSetAppModule` exists, and `MainActivity` exports
  `ANDROID_ENTRYPOINT`. Read it from the environment and drop the baked-in
  default, and the `.so` stops caring which app it is in.
- **The Java package**, via `swift-java.config`'s
  `"javaPackage": "<applicationId>.swift"`, which lands in the generated class's
  name *and* in the JNI symbol names. This must become a fixed package —
  `org.nucleantui` or similar — independent of `applicationId`. Then one
  compiled class and one `.so` serve every app. The generated Java's package is
  the only reason this is app-specific; nothing in the Swift is.

`python_version` also appears in the source, but only as a path fragment
(`python3.13/`) — publish per Python minor, or derive it at runtime from the
unpacked tree.

Everything else the generator writes stays as-is: the AAR is a build artifact of
this same package, produced by CI once per (Nucleant version × Python minor ×
ABI set), and `ksproject` chooses between "consume the AAR" (default) and "build
from source" (a flag, for working on the bootstrap itself).

## Route C — drop jextract, hand-write the JNI

Recorded for completeness; **not** the current direction.

`CAndroidNativeWindow` already includes `<android/native_window_jni.h>`, so
`JNIEnv`/`jobject`/`jstring` are visible in Swift with no extra dependency.
Twelve `@_cdecl("Java_<mangled>_...")` functions plus a hand-written
`NucleantMain.java` of `static native` declarations would replace all of
swift-java, including the runtime module and `swiftkit-core`.

Rejected because it trades the entire generated bridge for a mangled-name
coupling between Java and Swift that nothing checks: rename a method or move the
class and it links fine, then fails at first call. Route A gets the same
build-time win without that.

## Recommended order

1. Shared `--scratch-path` and `--disable-index-store` — an afternoon, and it
   removes the repeated-cost problem, which is the one being felt.
2. Pin swift-java, declare task inputs, ABI subsetting — small, independent.
3. Route A once (1) proves insufficient — removes swift-syntax outright.
4. Route B when the bootstrap is stable enough to version, which is the real
   precondition: a published AAR is a promise about the JNI surface.
