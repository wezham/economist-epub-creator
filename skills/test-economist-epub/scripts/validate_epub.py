#!/usr/bin/env python3
"""Validate the structural requirements of an EPUB file."""

import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def validate_epub(path: Path) -> list[str]:
    errors = []
    if not path.is_file():
        return [f"file does not exist: {path}"]
    if not zipfile.is_zipfile(path):
        return ["file is not a ZIP/EPUB archive"]

    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not names or names[0] != "mimetype":
            errors.append("mimetype must be the first ZIP entry")
        if "mimetype" not in names:
            errors.append("missing mimetype")
        else:
            info = archive.getinfo("mimetype")
            if info.compress_type != zipfile.ZIP_STORED:
                errors.append("mimetype must be stored without compression")
            if archive.read("mimetype") != b"application/epub+zip":
                errors.append("invalid mimetype content")

        container_name = "META-INF/container.xml"
        if container_name not in names:
            errors.append("missing META-INF/container.xml")
            return errors

        try:
            container = ElementTree.fromstring(archive.read(container_name))
            rootfile = container.find(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            opf_path = rootfile.get("full-path") if rootfile is not None else None
        except ElementTree.ParseError as exc:
            errors.append(f"invalid container.xml: {exc}")
            return errors

        if not opf_path or opf_path not in names:
            errors.append("container.xml does not reference an existing package document")
            return errors

        try:
            package = ElementTree.fromstring(archive.read(opf_path))
        except ElementTree.ParseError as exc:
            errors.append(f"invalid package document: {exc}")
            return errors

        namespace = {"opf": "http://www.idpf.org/2007/opf"}
        manifest = {
            item.get("id"): item
            for item in package.findall(".//opf:manifest/opf:item", namespace)
        }
        spine = package.findall(".//opf:spine/opf:itemref", namespace)
        if not manifest:
            errors.append("package manifest is empty")
        if not spine:
            errors.append("package spine is empty")
        for itemref in spine:
            if itemref.get("idref") not in manifest:
                errors.append(f"spine references missing item: {itemref.get('idref')}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("epub", type=Path)
    args = parser.parse_args()
    errors = validate_epub(args.epub)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Valid EPUB structure: {args.epub}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
