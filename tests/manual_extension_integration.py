"""Integration test for the manual-only Blender 5.2 extension."""

import pathlib
import sys

import bmesh
import bpy


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "blender_extension"))

import orthographic_relief  # noqa: E402


def main():
    assert not hasattr(orthographic_relief, "start_server")
    assert "socket" not in orthographic_relief.__dict__
    orthographic_relief.register()
    try:
        bpy.ops.mesh.primitive_monkey_add()
        source = bpy.context.active_object
        source.name = "ManualExtensionSource"

        settings = bpy.context.scene.orthographic_relief_settings
        settings.output_name = "ManualExtensionRelief"
        settings.projection = "Z"
        settings.resolution = 32
        settings.relief_height = 0.2
        settings.base_thickness = 0.08
        settings.blur_radius = 1.5
        settings.smooth_iterations = 2
        settings.save_images = False

        status = bpy.ops.object.generate_orthographic_relief()
        assert status == {"FINISHED"}
        relief = bpy.data.objects["ManualExtensionRelief"]
        assert relief["relief_projection_is_height_field"] is True
        assert any(mod.type == "CORRECTIVE_SMOOTH" for mod in relief.modifiers)

        check_mesh = bmesh.new()
        check_mesh.from_mesh(relief.data)
        assert all(edge.is_manifold for edge in check_mesh.edges)
        check_mesh.free()
        print(
            "MANUAL_EXTENSION_OK",
            {
                "blender": bpy.app.version_string,
                "object": relief.name,
                "vertices": len(relief.data.vertices),
                "faces": len(relief.data.polygons),
                "network_bridge": False,
            },
        )
    finally:
        orthographic_relief.unregister()


if __name__ == "__main__":
    main()
