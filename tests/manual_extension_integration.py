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
        settings.base_shape = "SILHOUETTE"
        settings.blur_radius = 1.5
        settings.smooth_iterations = 2
        settings.save_images = False

        settings.preview_resolution = 48
        status = bpy.ops.object.orthorelief_preview_start()
        assert status == {"FINISHED"}
        preview = bpy.data.objects["__Orthographic_Relief_Live_Preview__"]
        assert preview["relief_live_preview"] is True
        assert preview["relief_preview_source"] == source.name
        assert source.hide_get() is True
        assert settings.preview_enabled is True
        first_mesh = preview.data

        settings.margin = 0.08
        settings.blur_radius = 3.0
        settings.depth_gamma = 1.4
        status = bpy.ops.object.orthorelief_preview_refresh()
        assert status == {"FINISHED"}
        refreshed = bpy.data.objects["__Orthographic_Relief_Live_Preview__"]
        assert refreshed.data is not first_mesh
        assert "Live" in settings.preview_status

        status = bpy.ops.object.orthorelief_preview_stop()
        assert status == {"FINISHED"}
        assert bpy.data.objects.get("__Orthographic_Relief_Live_Preview__") is None
        assert source.hide_get() is False
        assert bpy.context.active_object is source

        status = bpy.ops.object.orthorelief_preview_start()
        assert status == {"FINISHED"}
        status = bpy.ops.object.generate_orthographic_relief()
        assert status == {"FINISHED"}
        assert bpy.data.objects.get("__Orthographic_Relief_Live_Preview__") is None
        assert source.hide_get() is False
        relief = bpy.data.objects["ManualExtensionRelief"]
        assert relief["relief_projection_is_height_field"] is True
        assert relief["relief_base_shape"] == "SILHOUETTE"
        assert len(relief.data.vertices) < 2 * 32 * 32
        assert any(mod.type == "CORRECTIVE_SMOOTH" for mod in relief.modifiers)

        check_mesh = bmesh.new()
        check_mesh.from_mesh(relief.data)
        assert all(edge.is_manifold for edge in check_mesh.edges)
        assert check_mesh.calc_volume(signed=True) > 0.0
        check_mesh.free()
        print(
            "MANUAL_EXTENSION_OK",
            {
                "blender": bpy.app.version_string,
                "object": relief.name,
                "vertices": len(relief.data.vertices),
                "faces": len(relief.data.polygons),
                "live_preview": True,
                "network_bridge": False,
            },
        )
    finally:
        orthographic_relief.unregister()


if __name__ == "__main__":
    main()
