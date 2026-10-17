"""Scripts de empaquetado: licencias de terceros, versión del instalador y datos para SignPath."""

import importlib.util
import re
import xml.etree.ElementTree as ET

from conftest import ROOT


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


portable = load("build_portable")
installer = load("build_installer")


def test_package_license_prefers_license_expression():
    meta = "Metadata-Version: 2.4\nName: demo\nVersion: 1.2\nLicense-Expression: MIT\nLicense: viejo\n"
    assert portable.package_license(meta) == ("demo", "1.2", "MIT")


def test_package_license_falls_back_to_classifiers():
    meta = ("Name: demo\nVersion: 3\nClassifier: License :: OSI Approved :: BSD License\n"
            "Classifier: Programming Language :: Python\n")
    assert portable.package_license(meta) == ("demo", "3", "BSD License")


def test_third_party_licenses_include_each_library_and_its_text(tmp_path):
    info = tmp_path / "demo-1.0.dist-info"
    (info / "licenses").mkdir(parents=True)
    (info / "METADATA").write_text("Name: demo\nVersion: 1.0\nLicense: MIT\n", encoding="utf-8")
    (info / "licenses" / "LICENSE.txt").write_text("Texto de la licencia MIT", encoding="utf-8")
    out = tmp_path / "THIRD-PARTY-LICENSES.txt"
    portable.write_third_party_licenses(tmp_path, out)
    text = out.read_text(encoding="utf-8")
    assert "demo 1.0  —  MIT" in text and "Texto de la licencia MIT" in text


def test_nvidia_cudnn_is_excluded_from_packages():
    names = ["cudnn64_9.dll", "ctranslate2.dll", "libiomp5md.dll"]
    assert portable.IGNORE_LIBS(".", names) == {"cudnn64_9.dll"}


def test_installer_version_comes_from_the_app():
    app_py = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")
    assert installer.app_version() == re.search(r'^VERSION = "(.+)"', app_py, re.M)[1]


def test_msi_metadata_matches_signpath_restrictions():
    """SignPath solo firma si el "subject" y el "author" del MSI son los declarados."""
    ns = {"w": "http://wixtoolset.org/schemas/v4/wxs"}
    summary = ET.parse(ROOT / "installer" / "Transcriptor.wxs").find(".//w:SummaryInformation", ns)
    msi = ET.parse(ROOT / ".signpath" / "artifact-configuration.xml").find(
        ".//{http://signpath.io/artifact-configuration/v1}msi-file")
    assert summary.get("Description") == msi.get("subject") == "Transcriptor"
    assert summary.get("Manufacturer") == msi.get("author")


def test_legal_files_exist():
    for name in portable.LEGAL_FILES:
        assert (ROOT / name).is_file(), name
    assert "Apache License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
