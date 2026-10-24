"""Run with Blender in background mode; exits non-zero when generation regresses."""

import pathlib
import sys

import bmesh
import bpy


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "blender_addon"))

from relief_mcp.core import generate_relief  # noqa: E402


def main():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1.0)
    source = bpy.context.active_object
    source.name = "IntegrationSphere"
    source.scale = (1.0, 0.8, 0.45)
    bpy.context.view_layer.update()

    result = generate_relief(
        source_object=source.name,
        output_name="IntegrationRelief",
        projection="Z",
        resolution_x=32,
        resolution_y=24,
        relief_height=0.2,
        base_thickness=0.08,
        blur_radius=1.5,
        save_images=False,
    )
    relief = bpy.data.objects[result["object_name"]]
    assert result["undercut_free_along_projection"] is True
    assert len(relief.data.vertices) == 32 * 24 + 4
    assert any(modifier.type == "CORRECTIVE_SMOOTH" for modifier in relief.modifiers)
    check_mesh = bmesh.new()
    check_mesh.from_mesh(relief.data)
    assert all(edge.is_manifold for edge in check_mesh.edges)
    check_mesh.free()
    assert result["hit_pixels"] > 0
    assert bpy.data.images.get(result["depth_image"]) is not None
    assert bpy.data.images.get(result["blurred_image"]) is not None
    print("RELIEF_INTEGRATION_OK", result)


if __name__ == "__main__":
    main()
