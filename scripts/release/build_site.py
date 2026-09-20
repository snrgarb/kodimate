#!/usr/bin/env python3
"""Build the GitHub-Pages-hosted Kodi addon repository site.

Usage:
    build_site.py --addon-zip dist/script.kodimate-0.1.0.zip --out site

Reads the built script.kodimate addon zip (so addons.xml matches exactly
what is shipped), zips up the repository.kodimate addon alongside it, and
writes the addons.xml / addons.xml.md5 / index.html Kodi expects to find at
the repository's <datadir> root.
"""
import argparse
import hashlib
import os
import re
import shutil
import zipfile

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
REPOSITORY_ADDON_DIR = os.path.join(os.path.dirname(__file__), "repository.kodimate")


def _addon_root_xml_string(addon_xml_bytes):
    """Return the <addon>...</addon> element as a UTF-8 string, without the
    leading XML declaration."""
    text = addon_xml_bytes.decode("utf-8")
    text = re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", text)
    return text.strip()


def _read_zip_member(zip_path, member):
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(member)


def _addon_version(addon_xml_string):
    match = re.search(r'\bversion="([^"]*)"', addon_xml_string)
    return match.group(1)


def _addon_id(addon_xml_string):
    match = re.search(r'\bid="([^"]*)"', addon_xml_string)
    return match.group(1)


def _write_directory_index(dir_path):
    """Write an index.html in dir_path listing its files as bare-filename
    links, for Kodi's CHTTPDirectory parser (File manager -> Add source)."""
    names = sorted(os.listdir(dir_path))
    items = "\n".join('<li><a href="%s">%s</a></li>' % (n, n) for n in names)
    html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>%s</title></head>
<body>
<ul>
%s
</ul>
</body>
</html>
""" % (
        os.path.basename(dir_path.rstrip("/")),
        items,
    )
    with open(os.path.join(dir_path, "index.html"), "w") as f:
        f.write(html)


def _zip_repository_addon(out_dir, version):
    dest_dir = os.path.join(out_dir, "repository.kodimate")
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, "repository.kodimate-%s.zip" % version)
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(REPOSITORY_ADDON_DIR):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, os.path.dirname(REPOSITORY_ADDON_DIR))
                zf.write(full, rel)
    return zip_path


def build(addon_zip_path, out_dir):
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    # script.kodimate: read straight from the built zip.
    script_addon_xml_bytes = _read_zip_member(addon_zip_path, "script.kodimate/addon.xml")
    script_addon_xml = _addon_root_xml_string(script_addon_xml_bytes)
    script_version = _addon_version(script_addon_xml)
    script_id = _addon_id(script_addon_xml)

    script_dest_dir = os.path.join(out_dir, script_id)
    os.makedirs(script_dest_dir, exist_ok=True)
    zip_basename = os.path.basename(addon_zip_path)
    shutil.copy2(addon_zip_path, os.path.join(script_dest_dir, zip_basename))

    with zipfile.ZipFile(addon_zip_path) as zf:
        for asset in ("icon.png", "fanart.jpg"):
            member = "script.kodimate/%s" % asset
            if member in zf.namelist():
                with zf.open(member) as src, open(
                    os.path.join(script_dest_dir, asset), "wb"
                ) as dst:
                    shutil.copyfileobj(src, dst)

    _write_directory_index(script_dest_dir)

    # repository.kodimate: zip from the source tree beside this script.
    repo_addon_xml_path = os.path.join(REPOSITORY_ADDON_DIR, "addon.xml")
    with open(repo_addon_xml_path, "rb") as f:
        repo_addon_xml_bytes = f.read()
    repo_addon_xml = _addon_root_xml_string(repo_addon_xml_bytes)
    repo_version = _addon_version(repo_addon_xml)
    repo_id = _addon_id(repo_addon_xml)

    _zip_repository_addon(out_dir, repo_version)
    shutil.copy2(
        os.path.join(REPOSITORY_ADDON_DIR, "icon.png"),
        os.path.join(out_dir, repo_id, "icon.png"),
    )
    _write_directory_index(os.path.join(out_dir, repo_id))

    # addons.xml + md5
    addons_xml = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<addons>\n"
    for element in (script_addon_xml, repo_addon_xml):
        indented = "\n".join("    " + line for line in element.splitlines())
        addons_xml += indented + "\n"
    addons_xml += "</addons>\n"
    addons_xml_bytes = addons_xml.encode("utf-8")

    addons_xml_path = os.path.join(out_dir, "addons.xml")
    with open(addons_xml_path, "wb") as f:
        f.write(addons_xml_bytes)

    md5_path = os.path.join(out_dir, "addons.xml.md5")
    with open(md5_path, "w") as f:
        f.write(hashlib.md5(addons_xml_bytes).hexdigest())

    # Root index.html: Apache-style listing, one bare-filename or
    # bare-directory-name-with-trailing-slash <a> per entry, so Kodi's
    # CHTTPDirectory parser (File manager -> Add source) can follow it.
    index_html = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Kodimate repository</title></head>
<body>
<pre>
<a href="{repo_id}/">{repo_id}/</a>
<a href="{script_id}/">{script_id}/</a>
<a href="addons.xml">addons.xml</a>
<a href="addons.xml.md5">addons.xml.md5</a>
</pre>
</body>
</html>
""".format(
        repo_id=repo_id,
        script_id=script_id,
    )
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(index_html)

    open(os.path.join(out_dir, ".nojekyll"), "w").close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--addon-zip", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    build(args.addon_zip, args.out)


if __name__ == "__main__":
    main()
