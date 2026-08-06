import unittest

from ksp_bootstraps.bootstraps.kivy.gradle_build_files import GradleBuildFiles


class GradleBuildFilesTest(unittest.TestCase):
    def test_bytecode_task_fails_before_deleting_sources(self):
        generated = GradleBuildFiles._site_packages_tasks(
            '"arm64-v8a"',
            '3.13',
            True,
        )

        self.assertIn('val compileProcess = ProcessBuilder(', generated)
        self.assertIn('val compileExitCode = compileProcess.waitFor()', generated)
        self.assertIn('Python bytecode compilation failed with exit code', generated)
