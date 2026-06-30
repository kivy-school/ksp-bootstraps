from ksp_bootstraps.bootstrap import ProjectTest, BootstrapProtocol
from ksp_bootstraps.pyproject_models.pyproject_toml import KivySchoolProtocol, AndroidProtocol
from ksproject_utils.pyproject_toml import PyProjectToml

from ksp_bootstraps.bootstraps.kivy import KivyBootstrap

py_project = PyProjectToml("")
_ks_data = py_project.tool.kivy_school
if _ks_data: 
    and_data = _ks_data.android
    if and_data:
        android_data: AndroidProtocol = and_data

ks_data: KivySchoolProtocol = py_project.tool.kivy_school

bootstrap: BootstrapProtocol = KivyBootstrap(py_project, ProjectTest())