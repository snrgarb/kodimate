"""Tests for release packaging: deploy.sh zip contents and the site builder."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "release"))


def _tools_available():
    return shutil.which("rsync") and shutil.which("zip")


@pytest.mark.skipif(not _tools_available(), reason="rsync/zip not available")
def test_deploy_sh_builds_versioned_zip_with_expected_contents():
    with tempfile.TemporaryDirectory() as tmp_dist:
        env = dict(os.environ)
        env["KODIMATE_DIST_DIR"] = tmp_dist
        result = subprocess.run(
            ["bash", "scripts/dev/deploy.sh"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        last_line = result.stdout.strip().splitlines()[-1]
        zip_path = os.path.join(tmp_dist, "script.kodimate-0.1.0.zip")
        assert last_line == "built %s" % zip_path
        assert os.path.exists(zip_path)

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()

        assert all(n.startswith("script.kodimate/") for n in names)

        required = [
            "script.kodimate/addon.xml",
            "script.kodimate/default.py",
            "script.kodimate/service.py",
            "script.kodimate/icon.png",
            "script.kodimate/fanart.jpg",
            "script.kodimate/resources/settings.xml",
            "script.kodimate/resources/skins/Main/skin.xml",
            "script.kodimate/resources/language/resource.language.en_gb/strings.po",
        ]
        for path in required:
            assert path in names, "missing %s in zip" % path

        forbidden_substrings = [
            ".git/",
            ".github/",
            ".claude/",
            "docs/",
            "scripts/",
            "tests/",
            "dist/",
            "__pycache__",
            ".pyc",
            ".pytest_cache",
            "pytest.ini",
            "requirements-dev.txt",
            "CLAUDE.md",
            "CONTEXT.md",
            "proto_guide",
            "proto_osd",
            "proto_overrides",
        ]
        for name in names:
            for forbidden in forbidden_substrings:
                assert forbidden not in name, "%s should not be in zip (matched %r)" % (
                    name,
                    forbidden,
                )


def test_deploy_sh_version_sed_ignores_xml_declaration():
    sed_expr = r's/^[[:space:]]*version="\([^"]*\)".*/\1/p'
    with tempfile.TemporaryDirectory() as tmp:
        addon_xml = os.path.join(tmp, "addon.xml")
        with open(addon_xml, "w") as f:
            f.write(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<addon id="script.kodimate"\n'
                '       name="Kodimate"\n'
                '       version="9.8.7"\n'
                '       provider-name="snrgarb">\n'
            )
        result = subprocess.run(
            ["sed", "-n", sed_expr, addon_xml],
            capture_output=True,
            text=True,
            check=True,
        )
        version = result.stdout.strip().splitlines()[0]
        assert version == "9.8.7"


def _make_fake_addon_zip(path, version="0.1.0"):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "script.kodimate/addon.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<addon id="script.kodimate" name="Kodimate" version="%s" '
                'provider-name="snrgarb">\n'
                "    <extension point=\"xbmc.addon.metadata\">\n"
                "        <summary lang=\"en_GB\">Kodimate</summary>\n"
                "        <description lang=\"en_GB\">Desc</description>\n"
                "    </extension>\n"
                "</addon>\n"
            )
            % version,
        )
        zf.writestr("script.kodimate/icon.png", b"fake-icon-bytes")
        zf.writestr("script.kodimate/fanart.jpg", b"fake-fanart-bytes")


def test_build_site_produces_expected_layout(tmp_path):
    import build_site

    addon_zip = tmp_path / "script.kodimate-0.1.0.zip"
    _make_fake_addon_zip(str(addon_zip))
    out_dir = tmp_path / "site"

    build_site.main(["--addon-zip", str(addon_zip), "--out", str(out_dir)])

    assert (out_dir / "repository.kodimate" / "repository.kodimate-1.0.0.zip").exists()
    assert (out_dir / "script.kodimate" / "script.kodimate-0.1.0.zip").exists()
    assert (out_dir / "script.kodimate" / "icon.png").exists()
    assert (out_dir / "script.kodimate" / "fanart.jpg").exists()
    assert (out_dir / "repository.kodimate" / "icon.png").exists()
    assert (out_dir / "index.html").exists()
    assert (out_dir / ".nojekyll").exists()

    addons_xml_path = out_dir / "addons.xml"
    addons_xml_bytes = addons_xml_path.read_bytes()
    root = ET.fromstring(addons_xml_bytes)
    assert root.tag == "addons"
    addons = root.findall("addon")
    ids = {a.get("id"): a.get("version") for a in addons}
    assert ids == {"script.kodimate": "0.1.0", "repository.kodimate": "1.0.0"}

    md5_path = out_dir / "addons.xml.md5"
    expected_md5 = hashlib.md5(addons_xml_bytes).hexdigest()
    assert md5_path.read_text().strip() == expected_md5

    with zipfile.ZipFile(out_dir / "repository.kodimate" / "repository.kodimate-1.0.0.zip") as zf:
        names = zf.namelist()
    assert "repository.kodimate/addon.xml" in names

    index_html = (out_dir / "index.html").read_text()
    assert "repository.kodimate/" in index_html
    assert "script.kodimate/" in index_html


def test_root_index_html_links_are_kodi_httpdirectory_compatible(tmp_path):
    """Kodi's CHTTPDirectory only follows <a href> links that are a bare
    filename or a bare directory name ending in "/" -- no nested paths."""
    import build_site

    addon_zip = tmp_path / "script.kodimate-0.1.0.zip"
    _make_fake_addon_zip(str(addon_zip))
    out_dir = tmp_path / "site"

    build_site.main(["--addon-zip", str(addon_zip), "--out", str(out_dir)])

    index_html = (out_dir / "index.html").read_text()
    hrefs = re.findall(r'href="([^"]+)"', index_html)
    assert "repository.kodimate/" in hrefs
    assert "script.kodimate/" in hrefs
    assert "addons.xml" in hrefs
    assert "addons.xml.md5" in hrefs
    for href in hrefs:
        assert not (href.startswith(".") or href.startswith("/")), href
        if "/" in href:
            assert href.endswith("/") and href.count("/") == 1, href


def test_subdirectory_index_html_files_exist(tmp_path):
    import build_site

    addon_zip = tmp_path / "script.kodimate-0.1.0.zip"
    _make_fake_addon_zip(str(addon_zip))
    out_dir = tmp_path / "site"

    build_site.main(["--addon-zip", str(addon_zip), "--out", str(out_dir)])

    repo_index = (out_dir / "repository.kodimate" / "index.html").read_text()
    assert 'href="repository.kodimate-1.0.0.zip"' in repo_index
    assert 'href="icon.png"' in repo_index

    script_index = (out_dir / "script.kodimate" / "index.html").read_text()
    assert 'href="script.kodimate-0.1.0.zip"' in script_index
    assert 'href="icon.png"' in script_index
