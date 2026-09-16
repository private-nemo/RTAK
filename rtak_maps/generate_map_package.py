#!/usr/bin/env python3
"""
RTAK Map Package Generator
Generates an ATAK Mission Package (.zip) that configures an offline .mbtiles
file as a map layer. Import the output zip into ATAK to auto-configure the
offline layer on any device — no manual per-device setup required.

Usage:
    python3 generate_map_package.py --name "RTAK Base Map" \
        --mbtiles rtak-base.mbtiles --output rtak-maps-package.zip

The generated package configures ATAK to look for the mbtiles file at:
    /sdcard/atak/imagery/<mbtiles-filename>

Copy the mbtiles file to that path on each device before importing the package.

ATAK data package format reference:
    https://github.com/deptofdefense/AndroidTacticalAssaultKit-CIV
"""

import argparse
import uuid
import zipfile
from pathlib import Path


MAP_SOURCE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<customMapSource>
    <name>{name}</name>
    <minZoom>0</minZoom>
    <maxZoom>20</maxZoom>
    <type>mbtiles</type>
    <localSourceFolder>/sdcard/atak/imagery</localSourceFolder>
    <localSourceFilename>{filename}</localSourceFilename>
</customMapSource>
"""

MANIFEST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<MissionPackageManifest version="2">
  <Configuration>
    <Parameter name="uid" value="{uid}"/>
    <Parameter name="name" value="{name}"/>
    <Parameter name="onReceiveDelete" value="false"/>
  </Configuration>
  <Contents>
    <Content ignore="false" zipEntry="maps/{config_filename}"/>
  </Contents>
</MissionPackageManifest>
"""


def generate(name: str, mbtiles: str, output: str) -> None:
    mbtiles_filename = Path(mbtiles).name
    config_filename = Path(mbtiles).stem + "-source.xml"
    package_uid = str(uuid.uuid4())

    map_source_content = MAP_SOURCE_XML.format(
        name=name,
        filename=mbtiles_filename,
    )

    manifest_content = MANIFEST_XML.format(
        uid=package_uid,
        name=name,
        config_filename=config_filename,
    )

    output_path = Path(output)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"maps/{config_filename}", map_source_content)
        zf.writestr("MANIFEST.xml", manifest_content)

    print(f"Package written: {output_path}")
    print(f"  Layer name   : {name}")
    print(f"  mbtiles file : /sdcard/atak/imagery/{mbtiles_filename}")
    print(f"  Package UID  : {package_uid}")
    print()
    print("Deploy steps:")
    print(f"  1. Copy {mbtiles_filename} to /sdcard/atak/imagery/ on each device")
    print(f"  2. Import {output_path.name} into ATAK:")
    print("       Settings → Data Packages → Import → select the zip")
    print("  3. The offline layer will appear in ATAK's map layer list")
    print("  4. Set it as the default base map and remove online sources")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an ATAK data package for offline mbtiles map layer"
    )
    parser.add_argument("--name", required=True, help="Layer display name shown in ATAK")
    parser.add_argument("--mbtiles", required=True, help="Path to or filename of the .mbtiles file")
    parser.add_argument("--output", required=True, help="Output .zip package filename")
    args = parser.parse_args()

    generate(args.name, args.mbtiles, args.output)


if __name__ == "__main__":
    main()
