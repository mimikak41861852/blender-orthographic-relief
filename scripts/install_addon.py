"""Install and enable the add-on zip; intended to run inside Blender."""

import pathlib
import sys

import bpy


if len(sys.argv) < 2:
    raise SystemExit("Expected add-on zip path after --")

zip_path = pathlib.Path(sys.argv[-1]).resolve()
if not zip_path.is_file():
    raise SystemExit(f"Add-on zip not found: {zip_path}")

try:
    bpy.ops.preferences.addon_disable(module="relief_mcp")
except Exception:
    pass
bpy.ops.preferences.addon_install(filepath=str(zip_path), overwrite=True)
bpy.ops.preferences.addon_enable(module="relief_mcp")
bpy.ops.wm.save_userpref()
print("RELIEF_ADDON_INSTALLED", zip_path)
