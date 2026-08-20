from __future__ import annotations

import shutil
import urllib.request
import zlib
from pathlib import Path
from enum import StrEnum

from ...pyproject_models.pyproject_toml import PyProjectTomlProtocol, AndroidProtocol

_GRADLE_VERSION = "9.5.0"
_GRADLE_WRAPPER_JAR_URL = (
    "https://raw.githubusercontent.com/gradle/gradle"
    f"/refs/tags/v{_GRADLE_VERSION}/gradle/wrapper/gradle-wrapper.jar"
)


class GradleBuildError(Exception):
    pass


class QtGradleBuildFiles:

    @staticmethod
    def write_root_build_gradle(dir: Path, plugins_list: list[str]) -> None:
        plugins = f"\n    ".join(plugins_list)
        content = f"""\
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
            "org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8\n"
            "org.gradle.configuration-cache=true\n"
            "android.useAndroidX=true\n"
            "android.nonTransitiveRClass=true\n"
        )
        (dir / "gradle.properties").write_text(content, encoding="utf-8")

    @staticmethod
    def write_local_properties(dir: Path, sdk_path: str) -> None:
        sdk_path = str(sdk_path).replace("\\", "/")
        (dir / "local.properties").write_text(f"sdk.dir={sdk_path}\n", encoding="utf-8")

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
        urllib.request.urlretrieve(_GRADLE_WRAPPER_JAR_URL, jar_path)
        urllib.request.urlretrieve(f"{_gh}/gradlew", gradlew_path)
        gradlew_path.chmod(0o755)
        urllib.request.urlretrieve(f"{_gh}/gradlew.bat", dir / "gradlew.bat")

    @staticmethod
    def write_qt_libs_xml(main_dir: Path, qt_libs: list[str]) -> None:
        res_values = main_dir / "res" / "values"
        res_values.mkdir(parents=True, exist_ok=True)
        items = "\n".join(f"        <item>{lib}</item>" for lib in qt_libs)
        content = f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <array name="qt_libs">
{items}
    </array>
    <array name="bundled_libs"/>
</resources>
"""
        (res_values / "qt_libs.xml").write_text(content, encoding="utf-8")

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
    ) -> None:
        abi_filters = ", ".join(f'"{a.value}"' for a in archs)
        arch_list_kts = ", ".join(f'"{a.value}"' for a in archs)
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
        site_packages_tasks = QtGradleBuildFiles._site_packages_tasks(
            arch_list_kts, python_version, byte_compile_default, uv_python
        )
        site_packages_tasks += QtGradleBuildFiles._post_build_task(post_build)

        template_path = project_dir / "build.tmpl.gradle.kts"
        if not template_path.exists():
            default_template = """\
plugins {
    id("{{ plugin_id }}")
}
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
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_STL=c++_shared")
            }
        }
    }
    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }
    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
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
        }
    }
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
    implementation(fileTree("libs") { include("*.aar", "*.jar") })
{{ extra_deps }}
}
{{ site_packages_tasks }}
"""
            template_path.write_text(default_template, encoding="utf-8")

        template_content = template_path.read_text(encoding="utf-8")
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
        build_content = build_content.replace(
            "{{ site_packages_tasks }}", site_packages_tasks
        )
        (app_dir / "build.gradle.kts").write_text(build_content, encoding="utf-8")
        (app_dir / "libs").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _post_build_task(post_build: Path | None) -> str:
        if post_build is None:
            return ""
        script = str(post_build).replace("\\", "/")
        if post_build.suffix == ".py":
            command_line = f'commandLine("uv", "run", postBuildScript.absolutePath)'
        else:
            command_line = f"commandLine(postBuildScript.absolutePath)"
        return f"""
val ksprojectPostBuild = tasks.register<Exec>("ksprojectPostBuild") {{
    group = "python"
    val appSrcRoot = rootProject.projectDir.parentFile.parentFile
    val postBuildScript = file("$appSrcRoot/{script}")
    workingDir = appSrcRoot
    environment("WHEELHOUSE", file("$appSrcRoot/wheelhouse").absolutePath)
    environment("APP_MAIN", file("src/main").absolutePath)
    {command_line}
    copySitePackagesTasks.forEach {{ dependsOn(it) }}
    copySitePackagesNativeLibsTasks.forEach {{ dependsOn(it) }}
    dependsOn("copySitePackagesJava")
    dependsOn("copySitePackagesKotlin")
}}
tasks.configureEach {{
    if (name.startsWith("merge") &&
        (name.endsWith("Assets") || name.endsWith("JniLibFolders"))) {{
        dependsOn(ksprojectPostBuild)
    }}
}}"""

    @staticmethod
    def _site_packages_tasks(
        arch_list_kts: str,
        python_version: str,
        byte_compile_default: bool,
        uv_python: str | None = None,
    ) -> str:
        kt_bool = str(byte_compile_default).lower()
        uv_py = uv_python or python_version
        return f"""\
abstract class OptimizePythonTask : DefaultTask() {{
    @get:Input
    abstract val shouldCompile: Property<Boolean>
    @get:Input
    abstract val targetPath: Property<String>
    @get:Input
    abstract val ndkDir: Property<String>
    @TaskAction
    fun runOptimization() {{
        val path = targetPath.get()
        val dir = File(path)
        if (!dir.exists()) return
        val doCompile = shouldCompile.get()
        if (doCompile) {{
            ProcessBuilder("uv", "run", "--no-project", "--python", "{uv_py}", "python", "-m", "compileall", "-b", "-o", "2", "-j", "0", "-q", path)
                .redirectErrorStream(true).start().waitFor()
        }}
        val junkExts = mutableListOf(".pyi", ".c", ".cpp", ".h", ".pyx", ".pxd", ".md", ".rst")
        if (doCompile) {{ junkExts.add(".py") }}
        val junkDirs = setOf("tests", "test", "docs", "doc", "examples", "example", "tutorials", "benchmarks", "perf", ".mypy_cache", ".pytest_cache", "__pycache__", "bin", "unittest")
        val allFiles = dir.walkBottomUp().toList()
        allFiles.parallelStream().forEach {{ f ->
            if (f.isFile && junkExts.any {{ ext -> f.name.endsWith(ext) }}) {{ f.delete() }}
        }}
        allFiles.forEach {{ f ->
            if (f.isDirectory && junkDirs.contains(f.name) && f.exists()) {{ f.deleteRecursively() }}
        }}
        val os = org.gradle.internal.os.OperatingSystem.current()
        val hostTag = if (os.isWindows) "windows-x86_64" else if (os.isMacOsX) "darwin-x86_64" else "linux-x86_64"
        val stripExe = if (os.isWindows) "llvm-strip.exe" else "llvm-strip"
        val stripTool = File(ndkDir.get(), "toolchains/llvm/prebuilt/$hostTag/bin/$stripExe")
        if (stripTool.exists()) {{
            val soFiles = dir.walkTopDown().filter {{ it.isFile && it.name.endsWith(".so") }}.toList()
            soFiles.parallelStream().forEach {{ f ->
                ProcessBuilder(stripTool.absolutePath, "--strip-unneeded", f.absolutePath).start().waitFor()
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
        from(assetsDir.dir("python{python_version}")) {{ into("python{python_version}") }}
        from(assetsDir.dir("lib-dynload")) {{ into("lib-dynload") }}
        into(stagingDir)
    }}
}}
val optimizeStagedTasks = sitePackagesAbis.map {{ abi ->
    tasks.register<OptimizePythonTask>("optimizeStaged_${{abi}}") {{
        group = "python"
        dependsOn("stagePython_${{abi}}")
        val isCmdLineForced = project.hasProperty("forceCompile")
        val isReleaseBuild = gradle.startParameter.taskNames.any {{ it.contains("Release", ignoreCase = true) }}
        val androidExt = project.extensions.getByType(com.android.build.gradle.BaseExtension::class.java)
        shouldCompile.set(isReleaseBuild || isCmdLineForced || {kt_bool})
        targetPath.set(stagingDir.absolutePath)
        ndkDir.set(androidExt.ndkDirectory.absolutePath)
    }}
}}
val zipPythonAssets = tasks.register<Zip>("zipPythonAssets") {{
    group = "python"
    dependsOn(optimizeStagedTasks)
    archiveFileName.set("assets.zip")
    destinationDirectory.set(generatedAssetsDir)
    from(stagingDir) {{ include("**/*") }}
    entryCompression = ZipEntryCompression.DEFLATED
}}
tasks.register<Copy>("copySitePackagesJava") {{
    group = "python"
    val srcDir = sitePackagesAbis.map {{ layout.projectDirectory.dir("../site_packages/$it/.java").asFile }}.firstOrNull {{ it.exists() }}
    if (srcDir != null) {{ from(srcDir); into("src/main/java") }}
}}
tasks.register<Copy>("copySitePackagesKotlin") {{
    group = "python"
    val srcDir = sitePackagesAbis.map {{ layout.projectDirectory.dir("../site_packages/$it/.kotlin").asFile }}.firstOrNull {{ it.exists() }}
    if (srcDir != null) {{ from(srcDir); into("src/main/kotlin") }}
}}
val copySitePackagesNativeLibsTasks = sitePackagesAbis.map {{ abi ->
    tasks.register<Copy>("copySitePackagesNativeLibs_${{abi}}") {{
        group = "python"
        val srcPath = layout.projectDirectory.dir("../site_packages/$abi/.libs/$abi").asFile.absolutePath
        onlyIf {{ File(srcPath).exists() }}
        from(srcPath) {{ include("*.so") }}
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
    if (name.contains("Assets") && name != "zipPythonAssets") {{ dependsOn(zipPythonAssets) }}
    if (name.startsWith("buildCMake") || name.startsWith("configureCMake") || name.startsWith("generateJsonModel")) {{
        copySitePackagesNativeLibsTasks.forEach {{ dependsOn(it) }}
    }}
}}
"""

    @staticmethod
    def write_android_manifest(
        main_dir: Path,
        package_name: str,
        project_dir: Path,
        app_name: str,
        permissions: list[str] | None = None,
        meta_data: dict[str, str] | None = None,
        services: list["AndroidProtocol.ServiceData"] | None = None,
    ) -> None:
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
        if not template_path.exists():
            default_template = """\
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
{{ permissions }}
    <application
        android:name="org.qtproject.qt.android.bindings.QtApplication"
        android:label="{{ app_name }}"
        android:icon="@mipmap/ic_launcher"
        android:allowBackup="true"
        android:supportsRtl="true"
        android:hardwareAccelerated="true"
        android:extractNativeLibs="true">{{ meta_data }}
{{ services }}
        <activity
            android:name=".MainActivity"
            android:label="{{ app_name }}"
            android:configChanges="mcc|mnc|locale|touchscreen|keyboard|keyboardHidden|navigation|orientation|screenLayout|fontScale|uiMode|screenSize|smallestScreenSize"
            android:theme="@android:style/Theme.DeviceDefault.NoActionBar"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <meta-data android:name="android.app.lib_name" android:value="main" />
            <meta-data android:name="android.app.qt_libs_resource_id" android:resource="@array/qt_libs" />
            <meta-data android:name="android.app.bundled_libs_resource_id" android:resource="@array/bundled_libs" />
            <meta-data android:name="android.app.extract_android_style" android:value="minimal" />
            <meta-data android:name="android.app.background_running" android:value="true" />
        </activity>
    </application>
</manifest>
"""
            template_path.write_text(default_template, encoding="utf-8")
        manifest_content = template_path.read_text(encoding="utf-8")
        manifest_content = manifest_content.replace("{{ app_name }}", app_name)
        manifest_content = manifest_content.replace("{{ permissions }}", perm_lines)
        manifest_content = manifest_content.replace("{{ meta_data }}", meta_lines)
        manifest_content = manifest_content.replace("{{ services }}", service_lines)
        (main_dir / "AndroidManifest.xml").write_text(
            manifest_content, encoding="utf-8"
        )

    @staticmethod
    def write_icon(res_dir: Path, icon_src: Path) -> None:
        mipmap_dir = res_dir / "mipmap"
        mipmap_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_src, mipmap_dir / "ic_launcher.png")

    @staticmethod
    def write_main_activity(
        main_dir: Path,
        package_name: str,
        python_version: str,
        python_module: str,
        presplash_type: str | None = None,
        presplash_name: str | None = None,
        presplash_color: str = "#FFFFFF",
    ) -> None:
        java_dir = main_dir / "java" / Path(*package_name.split("."))
        java_dir.mkdir(parents=True, exist_ok=True)
        content = f"""\
package {package_name};

import android.os.Bundle;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;
import java.io.File;
import org.qtproject.qt.android.bindings.QtActivity;

public class MainActivity extends QtActivity {{
    private static final String TAG = "ksproject-qt";

    @Override
    public void onCreate(Bundle savedInstanceState) {{
        final File appDir = new File(getFilesDir(), "app");
        String appPath = appDir.getAbsolutePath();
        String privatePath = getFilesDir().getAbsolutePath();

        setEnv("ANDROID_APP_PATH", appPath);
        setEnv("ANDROID_ENTRYPOINT", "{str(python_module).strip().replace('-', '_').replace('.', '_').replace(' ', '_')}");
        setEnv("ANDROID_NATIVE_LIB_DIR", getApplicationInfo().nativeLibraryDir);
        setEnv("PYTHONHOME", appPath);
        setEnv("PYTHONNOUSERSITE", "1");
        setEnv("PYTHONUNBUFFERED", "1");
        setEnv("PYTHONOPTIMIZE", "2");

        super.onCreate(savedInstanceState);
    }}

    private static void setEnv(String name, String value) {{
        try {{
            Os.setenv(name, value, true);
        }} catch (ErrnoException e) {{
            Log.e(TAG, "setenv " + name + " failed", e);
        }}
    }}
}}
"""
        dest = java_dir / "MainActivity.java"
        dest.write_text(content, encoding="utf-8")

    @staticmethod
    def write_qt_python_service(main_dir: Path) -> None:
        java_dir = (
            main_dir / "java" / "org" / "qtproject" / "qt" / "android" / "bindings"
        )
        java_dir.mkdir(parents=True, exist_ok=True)
        content = """\
package org.qtproject.qt.android.bindings;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.IBinder;
import android.os.Process;
import android.util.Log;
import android.system.Os;
import android.system.ErrnoException;
import java.lang.reflect.Method;

public class PythonService extends Service implements Runnable {

    private Thread pythonThread = null;
    private String androidPrivate;
    private String serviceEntrypoint;
    private String pythonVersion;
    private String pythonName;
    public static PythonService mService = null;
    private Intent startIntent = null;
    private boolean autoRestartService = false;

    static {
        System.loadLibrary("python3");
        System.loadLibrary("service_main");
    }

    public void setAutoRestartService(boolean restart) {
        autoRestartService = restart;
    }

    public int startType() {
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent arg0) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (pythonThread != null) {
            return startType();
        }
        if (intent == null) {
            Context context = getApplicationContext();
            intent = getThisDefaultIntent(context, "");
        }

        startIntent = intent;
        Bundle extras = intent.getExtras();
        if (extras != null) {
            androidPrivate = extras.getString("androidPrivate");
            serviceEntrypoint = extras.getString("serviceEntrypoint");
            pythonVersion = extras.getString("pythonVersion");
            pythonName = extras.getString("pythonName");
            boolean serviceStartAsForeground = false;
            if (extras.containsKey("serviceStartAsForeground")) {
                serviceStartAsForeground = extras.getString("serviceStartAsForeground").equals("true");
            }
            pythonThread = new Thread(this);
            pythonThread.start();
            if (serviceStartAsForeground) {
                doStartForeground(extras);
            }
        }
        return startType();
    }

    protected int getServiceId() {
        if (pythonName != null && !pythonName.isEmpty()) {
            return Math.abs(pythonName.hashCode()) % 10000 + 1;
        }
        return 1;
    }

    protected Intent getThisDefaultIntent(Context ctx, String pythonServiceArgument) {
        return null;
    }

    protected void doStartForeground(Bundle extras) {
        String serviceTitle = extras.getString("serviceTitle");
        String smallIconName = extras.getString("smallIconName");
        String contentTitle = extras.getString("contentTitle");
        String contentText = extras.getString("contentText");
        Notification notification;
        Context context = getApplicationContext();
        Intent contextIntent = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        PendingIntent pIntent = PendingIntent.getActivity(
                context, 0, contextIntent,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        int smallIconId = context.getApplicationInfo().icon;
        if (smallIconName != null && !smallIconName.equals("")) {
            int resId = getResources().getIdentifier(smallIconName, "mipmap", getPackageName());
            if (resId == 0) {
                resId = getResources().getIdentifier(smallIconName, "drawable", getPackageName());
            }
            if (resId != 0) {
                smallIconId = resId;
            }
        }

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            notification = new Notification(smallIconId, serviceTitle, System.currentTimeMillis());
            try {
                Method func = notification.getClass().getMethod(
                        "setLatestEventInfo", Context.class, CharSequence.class, CharSequence.class, PendingIntent.class);
                func.invoke(notification, context, contentTitle, contentText, pIntent);
            } catch (Exception e) {}
        } else {
            String NOTIFICATION_CHANNEL_ID = "org.qtproject.qt" + getServiceId();
            String channelName = "Background Service" + getServiceId();
            NotificationChannel chan = new NotificationChannel(
                    NOTIFICATION_CHANNEL_ID, channelName, NotificationManager.IMPORTANCE_NONE);
            chan.setLightColor(Color.BLUE);
            chan.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);
            NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            manager.createNotificationChannel(chan);
            Notification.Builder builder = new Notification.Builder(context, NOTIFICATION_CHANNEL_ID);
            builder.setContentTitle(contentTitle);
            builder.setContentText(contentText);
            builder.setContentIntent(pIntent);
            builder.setSmallIcon(smallIconId);
            notification = builder.build();
        }
        startForeground(getServiceId(), notification);
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        pythonThread = null;
        if (autoRestartService && startIntent != null) {
            startService(startIntent);
        }
        Process.killProcess(Process.myPid());
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        if (startType() != START_STICKY) {
            stopSelf();
        }
    }

    @Override
    public void run() {
        try {
            Os.setenv("ANDROID_NATIVE_LIB_DIR", getApplicationInfo().nativeLibraryDir, true);
        } catch (ErrnoException e) {}
        this.mService = this;
        nativeStart(androidPrivate, serviceEntrypoint, pythonVersion);
        stopSelf();
    }

    public static native void nativeStart(String androidPrivate, String entrypoint, String pyVersion);
}
"""
        (java_dir / "PythonService.java").write_text(content, encoding="utf-8")

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
        title = notification_title or f"{service_name} is running"
        text = notification_text or "Background task active"
        unique_service_id = (
            zlib.crc32(service_name.lower().encode("utf-8")) % 10000
        ) + 1

        foreground_imports = ""
        foreground_logic = ""
        if foreground:
            foreground_imports = """
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
"""
            foreground_logic = f"""
        String channelId = "{package_name}.{service_name}";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            NotificationChannel channel = new NotificationChannel(
                channelId,
                "{service_name} Channel",
                NotificationManager.IMPORTANCE_LOW
            );
            NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager != null) {{
                manager.createNotificationChannel(channel);
            }}
        }}

        int iconId = getResources().getIdentifier("{notification_icon}", "drawable", "android");
        if (iconId == 0) {{
            iconId = android.R.drawable.stat_notify_sync;
        }}

        String finalTitle = intent.hasExtra("serviceTitle") ? intent.getStringExtra("serviceTitle") : "{title}";
        String finalText = intent.hasExtra("serviceDescription") ? intent.getStringExtra("serviceDescription") : "{text}";

        Notification notification;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            notification = new Notification.Builder(this, channelId)
                .setContentTitle(finalTitle)
                .setContentText(finalText)
                .setSmallIcon(iconId)
                .build();
        }} else {{
            notification = new Notification.Builder(this)
                .setContentTitle(finalTitle)
                .setContentText(finalText)
                .setSmallIcon(iconId)
                .build();
        }}
        startForeground({unique_service_id}, notification);
        intent.putExtra("serviceStartAsForeground", "false");
"""

        content = f"""\
package {package_name};

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import org.qtproject.qt.android.bindings.PythonService;
import java.io.File;{foreground_imports}

public class {service_name} extends PythonService {{
    
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
        intent.putExtra("serviceTitle", "{title}");
        intent.putExtra("serviceDescription", "{text}");
        intent.putExtra("serviceStartAsForeground", "{'true' if foreground else 'false'}");
        return intent;
    }}

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {{
        if (intent == null || intent.getExtras() == null || !intent.hasExtra("pythonName")) {{
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

    public static void start(Context ctx, String pythonServiceArgument) {{
        start(ctx, "{notification_icon}", "{title}", "{text}", pythonServiceArgument);
    }}

    public static void start(Context ctx, String smallIconName, String contentTitle, String contentText, String pythonServiceArgument) {{
        Intent intent = new Intent(ctx, {service_name}.class);
        intent.putExtra("androidPrivate", ctx.getFilesDir().getAbsolutePath());
        intent.putExtra("serviceEntrypoint", "{entrypoint}");
        intent.putExtra("pythonVersion", "{python_version}");
        intent.putExtra("pythonName", "{service_name.lower()}");
        intent.putExtra("serviceTitle", contentTitle);
        intent.putExtra("serviceDescription", contentText);
        intent.putExtra("smallIconName", smallIconName);
        intent.putExtra("pythonServiceArgument", pythonServiceArgument);
        intent.putExtra("serviceStartAsForeground", "{'true' if foreground else 'false'}");

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
            ctx.startForegroundService(intent);
        }} else {{
            ctx.startService(intent);
        }}
    }}

    public static void stop(Context ctx) {{
        Intent intent = new Intent(ctx, {service_name}.class);
        ctx.stopService(intent);
    }}
}}
"""
        (java_dir / f"{service_name}.java").write_text(content, encoding="utf-8")

    @staticmethod
    def write_main_c(cpp_dir: Path, python_version: str, project_name: str) -> None:
        cpp_dir.mkdir(parents=True, exist_ok=True)
        content = f"""\
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <android/log.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wchar.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  "ksproject-qt", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "ksproject-qt", __VA_ARGS__)

static PyObject *androidembed_log(PyObject *self, PyObject *args) {{
    const char *s;
    if (!PyArg_ParseTuple(args, "s", &s)) return NULL;
    __android_log_write(ANDROID_LOG_INFO, "python", s);
    Py_RETURN_NONE;
}}

static PyMethodDef AndroidEmbedMethods[] = {{
    {{"log", androidembed_log, METH_VARARGS, "log to android logcat"}},
    {{NULL, NULL, 0, NULL}}
}};

static struct PyModuleDef androidembed_mod = {{
    PyModuleDef_HEAD_INIT, "androidembed", NULL, -1, AndroidEmbedMethods
}};

PyMODINIT_FUNC PyInit_androidembed(void) {{
    return PyModule_Create(&androidembed_mod);
}}

static const char *REDIRECT_STDIO =
    "import sys, androidembed\\n"
    "class _LogFile:\\n"
    "    def __init__(self): self._buf = ''\\n"
    "    def write(self, s):\\n"
    "        self._buf += s\\n"
    "        while chr(10) in self._buf:\\n"
    "            i = self._buf.index(chr(10))\\n"
    "            androidembed.log(self._buf[:i])\\n"
    "            self._buf = self._buf[i+1:]\\n"
    "    def flush(self):\\n"
    "        if self._buf:\\n"
    "            androidembed.log(self._buf); self._buf = ''\\n"
    "sys.stdout = sys.stderr = _LogFile()\\n";

int main(int argc, char *argv[]) {{
    const char *app_path = getenv("ANDROID_APP_PATH");
    const char *entrypoint = getenv("ANDROID_ENTRYPOINT");
    const char *native_lib_dir = getenv("ANDROID_NATIVE_LIB_DIR");
    if (!app_path || !entrypoint) {{
        return 1;
    }}
    if (chdir(app_path) != 0) {{}}

    setenv("QT_QPA_PLATFORM", "android", 1);
    if (native_lib_dir) {{
        setenv("QT_PLUGIN_PATH", native_lib_dir, 1);
    }}
    
    char qml_path[1024];
    snprintf(qml_path, sizeof(qml_path), "%s/site-packages/PySide6/qml:%s/site-packages/PyQt6/Qt6/qml", app_path, app_path);
    setenv("QML2_IMPORT_PATH", qml_path, 1);

    PyImport_AppendInittab("androidembed", PyInit_androidembed);

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.parse_argv = 0;
    config.install_signal_handlers = 0;
    config.write_bytecode = 0;
    config.use_environment = 1;

    wchar_t w_stdlib[1024], w_dynload[1024], w_site[1024], w_project_site[1024], w_app[1024];
    swprintf(w_stdlib,  1024, L"%s/python{python_version}", app_path);
    swprintf(w_dynload, 1024, L"%s/python{python_version}/lib-dynload", app_path);
    swprintf(w_site,    1024, L"%s/site-packages", app_path);
    swprintf(w_project_site, 1024, L"%s/site-packages/{project_name}", app_path);
    swprintf(w_app,     1024, L"%s", app_path);

    config.module_search_paths_set = 1;
    PyWideStringList_Append(&config.module_search_paths, w_stdlib);
    PyWideStringList_Append(&config.module_search_paths, w_dynload);
    PyWideStringList_Append(&config.module_search_paths, w_site);
    PyWideStringList_Append(&config.module_search_paths, w_project_site);
    PyWideStringList_Append(&config.module_search_paths, w_app);

    if (native_lib_dir) {{
        wchar_t w_native[1024];
        swprintf(w_native, 1024, L"%s", native_lib_dir);
        PyWideStringList_Append(&config.module_search_paths, w_native);
    }}

    PyStatus status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {{
        return 1;
    }}

    PyRun_SimpleString(REDIRECT_STDIO);

    PyObject *runpy = PyImport_ImportModule("runpy");
    PyObject *func = PyObject_GetAttrString(runpy, "run_module");
    PyObject *args_tuple = PyTuple_Pack(1, PyUnicode_FromString(entrypoint));
    PyObject *kwargs = Py_BuildValue("{{s:s, s:i}}", "run_name", "__main__", "alter_sys", 1);

    PyObject *result = PyObject_Call(func, args_tuple, kwargs);
    int ret = 0;
    if (!result) {{
        PyErr_Print();
        ret = 1;
    }} else {{
        Py_DECREF(result);
    }}

    Py_FinalizeEx();
    return ret;
}}
"""
        (cpp_dir / "main.c").write_text(content, encoding="utf-8")

    @staticmethod
    def write_service_main_c(cpp_dir: Path, project_name: str) -> None:
        cpp_dir.mkdir(parents=True, exist_ok=True)
        content = f"""\
#define PY_SSIZE_T_CLEAN
#include <jni.h>
#include <Python.h>
#include <android/log.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  "ksproject-qt-srv", __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "ksproject-qt-srv", __VA_ARGS__)

static PyObject *androidembed_log(PyObject *self, PyObject *args) {{
    const char *s;
    if (!PyArg_ParseTuple(args, "s", &s)) return NULL;
    __android_log_write(ANDROID_LOG_INFO, "python-service", s);
    Py_RETURN_NONE;
}}

static PyMethodDef AndroidEmbedMethods[] = {{
    {{"log", androidembed_log, METH_VARARGS, "log to android logcat"}},
    {{NULL, NULL, 0, NULL}}
}};

static struct PyModuleDef androidembed_mod = {{
    PyModuleDef_HEAD_INIT, "androidembed", NULL, -1, AndroidEmbedMethods
}};

PyMODINIT_FUNC PyInit_androidembed(void) {{
    return PyModule_Create(&androidembed_mod);
}}

static const char *REDIRECT_STDIO =
    "import sys, androidembed\\n"
    "class _LogFile:\\n"
    "    def __init__(self): self._buf = ''\\n"
    "    def write(self, s):\\n"
    "        self._buf += s\\n"
    "        while chr(10) in self._buf:\\n"
    "            i = self._buf.index(chr(10))\\n"
    "            androidembed.log(self._buf[:i])\\n"
    "            self._buf = self._buf[i+1:]\\n"
    "    def flush(self):\\n"
    "        if self._buf:\\n"
    "            androidembed.log(self._buf); self._buf = ''\\n"
    "sys.stdout = sys.stderr = _LogFile()\\n";

JNIEXPORT jint JNICALL
Java_org_qtproject_qt_android_bindings_PythonService_nativeStart(
    JNIEnv *env, jobject thiz, jstring j_androidPrivate, jstring j_entrypoint, jstring j_pyVersion) {{

    const char *private_path = (*env)->GetStringUTFChars(env, j_androidPrivate, NULL);
    const char *entrypoint = (*env)->GetStringUTFChars(env, j_entrypoint, NULL);
    const char *py_version = (*env)->GetStringUTFChars(env, j_pyVersion, NULL);

    char app_path[1024];
    snprintf(app_path, sizeof(app_path), "%s/app", private_path);
    if (chdir(app_path) != 0) {{}}

    setenv("ANDROID_APP_PATH", app_path, 1);
    setenv("ANDROID_ENTRYPOINT", entrypoint, 1);
    setenv("ANDROID_ARGUMENT", app_path, 1);
    setenv("ANDROID_PRIVATE", private_path, 1);
    setenv("PYTHONHOME", app_path, 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PYTHONOPTIMIZE", "2", 1);
    setenv("PYTHON_SERVICE_ARGUMENT", entrypoint, 1);

    PyImport_AppendInittab("androidembed", PyInit_androidembed);

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.parse_argv = 0;
    config.install_signal_handlers = 0;
    config.write_bytecode = 0;
    config.use_environment = 1;

    wchar_t w_stdlib[1024], w_dynload[1024], w_site[1024], w_project_site[1024], w_app[1024];
    swprintf(w_stdlib,  1024, L"%s/python%s", app_path, py_version);
    swprintf(w_dynload, 1024, L"%s/python%s/lib-dynload", app_path, py_version);
    swprintf(w_site,    1024, L"%s/site-packages", app_path);
    swprintf(w_project_site, 1024, L"%s/site-packages/{project_name}", app_path);
    swprintf(w_app,     1024, L"%s", app_path);

    config.module_search_paths_set = 1;
    PyWideStringList_Append(&config.module_search_paths, w_stdlib);
    PyWideStringList_Append(&config.module_search_paths, w_dynload);
    PyWideStringList_Append(&config.module_search_paths, w_site);
    PyWideStringList_Append(&config.module_search_paths, w_project_site);
    PyWideStringList_Append(&config.module_search_paths, w_app);

    const char *native_lib_dir = getenv("ANDROID_NATIVE_LIB_DIR");
    if (native_lib_dir) {{
        wchar_t w_native[1024];
        swprintf(w_native, 1024, L"%s", native_lib_dir);
        PyWideStringList_Append(&config.module_search_paths, w_native);
    }}

    PyStatus status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {{
        return 1;
    }}

    PyRun_SimpleString(REDIRECT_STDIO);

    PyObject *runpy = PyImport_ImportModule("runpy");
    PyObject *func = PyObject_GetAttrString(runpy, "run_module");
    PyObject *args_tuple = PyTuple_Pack(1, PyUnicode_FromString(entrypoint));
    PyObject *kwargs = Py_BuildValue("{{s:s, s:i}}", "run_name", "__main__", "alter_sys", 1);

    PyObject *result = PyObject_Call(func, args_tuple, kwargs);
    int ret = 0;
    if (!result) {{
        PyErr_Print();
        ret = 1;
    }} else {{
        Py_DECREF(result);
    }}

    Py_FinalizeEx();
    (*env)->ReleaseStringUTFChars(env, j_androidPrivate, private_path);
    (*env)->ReleaseStringUTFChars(env, j_entrypoint, entrypoint);
    (*env)->ReleaseStringUTFChars(env, j_pyVersion, py_version);

    return ret;
}}
"""
        (cpp_dir / "service_main.c").write_text(content, encoding="utf-8")

    @staticmethod
    def write_cmake_lists(cpp_dir: Path) -> None:
        cpp_dir.mkdir(parents=True, exist_ok=True)
        content = """\
cmake_minimum_required(VERSION 3.22)
project(ksproject_main C)

set(CMAKE_C_STANDARD 11)

set(PYTHON_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/python_include/${ANDROID_ABI}")
set(JNI_LIBS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../jniLibs/${ANDROID_ABI}")

add_library(python3 SHARED IMPORTED)
set_target_properties(python3 PROPERTIES IMPORTED_LOCATION "${JNI_LIBS_DIR}/libpython3.so")

add_library(main SHARED main.c)
target_include_directories(main PRIVATE "${PYTHON_INCLUDE_DIR}")
target_link_libraries(main python3 log android)

add_library(service_main SHARED service_main.c)
target_include_directories(service_main PRIVATE "${PYTHON_INCLUDE_DIR}")
target_link_libraries(service_main python3 log android)
"""
        (cpp_dir / "CMakeLists.txt").write_text(content, encoding="utf-8")
