"""Smoke-test the installed Blender add-on through the same TCP path as MCP."""

import pathlib
import sys


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import mcp_server  # noqa: E402


status = mcp_server.ping_blender()
objects = mcp_server.list_mesh_objects()
assert status["ok"] is True
assert objects["ok"] is True
source = next(item["name"] for item in objects["mesh_objects"] if item["name"] == "Cube")
result = mcp_server.generate_relief(
    source_object=source,
    output_name="BridgeSmokeRelief",
    projection="Z",
    resolution=24,
    relief_height=0.2,
    base_thickness=0.08,
    blur_radius=1.0,
    corrective_smooth_iterations=2,
    save_images=False,
)
assert result["undercut_free_along_projection"] is True
assert result["object_name"].startswith("BridgeSmokeRelief")
print("BRIDGE_SMOKE_OK", status, result)
