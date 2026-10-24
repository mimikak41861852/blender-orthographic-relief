"""Exercise the outline-trimmed solid at the recommended 512 resolution."""

import pathlib
import sys

import bmesh
import bpy


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "blender_extension"))

from orthographic_relief.core import generate_relief  # noqa: E402


def main():
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.0)
    source = bpy.context.active_object
    source.name = "SilhouetteHighDetailSource"
    source.scale = (1.0, 0.9, 0.5)
    bpy.context.view_layer.update()

    result = generate_relief(
        source_object=source.name,
        output_name="SilhouetteHighDetailRelief",
        projection="Z",
        resolution_x=512,
        resolution_y=512,
        base_shape="SILHOUETTE",
        relief_height=0.2,
        base_thickness=0.08,
        blur_radius=1.25,
        corrective_smooth_iterations=2,
        save_images=False,
    )
    relief = bpy.data.objects[result["object_name"]]
    assert result["base_shape"] == "SILHOUETTE"
    assert len(relief.data.vertices) < int(2 * 512 * 512 * 0.85)

    check_mesh = bmesh.new()
    check_mesh.from_mesh(relief.data)
    assert all(edge.is_manifold for edge in check_mesh.edges)
    assert check_mesh.calc_volume(signed=True) > 0.0
    check_mesh.free()

    print(
        "SILHOUETTE_HIGH_DETAIL_OK",
        {
            "blender": bpy.app.version_string,
            "resolution": result["resolution"],
            "vertices": len(relief.data.vertices),
            "faces": len(relief.data.polygons),
            "base_shape": result["base_shape"],
        },
    )


if __name__ == "__main__":
    main()
