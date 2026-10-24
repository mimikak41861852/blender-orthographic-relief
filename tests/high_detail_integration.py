"""Exercise resolution above the old 512 limit with aspect fitting enabled."""

import pathlib
import sys

import bpy


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "blender_extension"))

import orthographic_relief  # noqa: E402


def main():
    orthographic_relief.register()
    try:
        bpy.ops.mesh.primitive_cube_add(size=2.0)
        source = bpy.context.active_object
        source.name = "HighDetailWideSource"
        source.scale = (2.0, 1.0, 0.5)
        bpy.context.view_layer.update()

        settings = bpy.context.scene.orthographic_relief_settings
        settings.output_name = "HighDetailRelief"
        settings.projection = "Z"
        settings.resolution = 1024
        settings.fit_resolution_to_aspect = True
        settings.base_shape = "RECTANGLE"
        settings.blur_radius = 0.5
        settings.smooth_factor = 0.0
        settings.smooth_iterations = 0
        settings.save_images = False

        status = bpy.ops.object.generate_orthographic_relief()
        assert status == {"FINISHED"}
        depth_image = bpy.data.images["HighDetailRelief_Depth"]
        resolution = tuple(depth_image.size)
        assert max(resolution) == 1024, resolution
        assert min(resolution) == 512, resolution
        assert max(resolution) > 512

        relief = bpy.data.objects["HighDetailRelief"]
        assert len(relief.data.vertices) == resolution[0] * resolution[1] + 4
        print(
            "HIGH_DETAIL_OK",
            {
                "blender": bpy.app.version_string,
                "resolution": resolution,
                "vertices": len(relief.data.vertices),
                "old_limit_exceeded": True,
            },
        )
    finally:
        orthographic_relief.unregister()


if __name__ == "__main__":
    main()
