"""Compare native QuadriFlow and ReQuad on a synthetic fine-detail relief."""

import math
import pathlib
import sys

import bmesh
import bpy
from mathutils.bvhtree import BVHTree


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "blender_extension"))

import orthographic_relief  # noqa: E402
from orthographic_relief.core import quad_remesh_for_cad  # noqa: E402


def make_fine_relief(name="FineRelief", resolution=129):
    vertices = []
    for layer in ("TOP", "BOTTOM"):
        for y_index in range(resolution):
            y = -1.0 + 2.0 * y_index / (resolution - 1)
            for x_index in range(resolution):
                x = -1.0 + 2.0 * x_index / (resolution - 1)
                if layer == "TOP":
                    broad = 0.18 * math.exp(-2.0 * (x * x + y * y))
                    detail_envelope = math.exp(
                        -18.0 * ((x - 0.28) ** 2 + (y + 0.18) ** 2)
                    )
                    engraving = (
                        0.035
                        * detail_envelope
                        * math.sin(72.0 * x)
                        * math.sin(72.0 * y)
                    )
                    bead = 0.055 * math.exp(
                        -220.0 * ((x + 0.38) ** 2 + (y - 0.32) ** 2)
                    )
                    z = 0.08 + broad + engraving + bead
                else:
                    z = -0.08
                vertices.append((x, y, z))

    faces = []
    layer_size = resolution * resolution
    for y_index in range(resolution - 1):
        for x_index in range(resolution - 1):
            a = y_index * resolution + x_index
            b = a + 1
            d = a + resolution
            c = d + 1
            faces.append((a, b, c, d))
            faces.append(
                (
                    layer_size + a,
                    layer_size + d,
                    layer_size + c,
                    layer_size + b,
                )
            )

    top = 0
    bottom = layer_size
    for index in range(resolution - 1):
        # -Y and +Y walls
        faces.append(
            (
                top + index + 1,
                top + index,
                bottom + index,
                bottom + index + 1,
            )
        )
        far = (resolution - 1) * resolution + index
        faces.append(
            (
                top + far,
                top + far + 1,
                bottom + far + 1,
                bottom + far,
            )
        )
        # -X and +X walls
        left = index * resolution
        next_left = (index + 1) * resolution
        faces.append(
            (
                top + left,
                top + next_left,
                bottom + next_left,
                bottom + left,
            )
        )
        right = left + resolution - 1
        next_right = next_left + resolution - 1
        faces.append(
            (
                top + next_right,
                top + right,
                bottom + right,
                bottom + next_right,
            )
        )

    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["relief_projection_is_height_field"] = True
    obj["relief_undercut_free_direction"] = (0.0, 0.0, 1.0)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj, vertices[:layer_size]


def select_only(obj):
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def metrics(obj, reference_top):
    vertices = [vertex.co.copy() for vertex in obj.data.vertices]
    polygons = [tuple(poly.vertices) for poly in obj.data.polygons]
    bvh = BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    all_distances = []
    detail_distances = []
    for x, y, z in reference_top:
        nearest = bvh.find_nearest((x, y, z))
        distance = float(nearest[3]) if nearest is not None else float("inf")
        all_distances.append(distance)
        if (x - 0.28) ** 2 + (y + 0.18) ** 2 < 0.16:
            detail_distances.append(distance)

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        boundary = sum(1 for edge in bm.edges if len(edge.link_faces) == 1)
        invalid = sum(1 for edge in bm.edges if len(edge.link_faces) not in {1, 2})
    finally:
        bm.free()

    all_distances.sort()
    detail_distances.sort()
    return {
        "faces": len(obj.data.polygons),
        "all_quads": all(len(poly.vertices) == 4 for poly in obj.data.polygons),
        "boundary": boundary,
        "invalid": invalid,
        "mean": sum(all_distances) / len(all_distances),
        "p95": all_distances[int(0.95 * (len(all_distances) - 1))],
        "max": max(all_distances),
        "detail_mean": sum(detail_distances) / len(detail_distances),
        "detail_p95": detail_distances[
            int(0.95 * (len(detail_distances) - 1))
        ],
    }


def run_requad(source, adaptive_size, target=5000):
    select_only(source)
    settings = bpy.context.scene.orthographic_relief_settings
    settings.quad_backend = "REQUAD_ADAPTIVE"
    settings.quad_target_faces = target
    settings.quad_adaptive_size = adaptive_size
    settings.quad_adaptive_count = False
    settings.quad_paint_density = False
    settings.quad_relax_iterations = 20
    settings.quad_preserve_sharp = True
    settings.quad_sharp_angle = 35.0
    before = set(bpy.data.objects)
    status = bpy.ops.object.orthorelief_cad_quad_remesh()
    assert status == {"FINISHED"}, status
    created = [obj for obj in set(bpy.data.objects) - before if obj.type == "MESH"]
    assert len(created) == 1, [obj.name for obj in created]
    assert created[0]["cad_quad_backend"] == "REQUAD_ADAPTIVE"
    assert created[0]["cad_quad_subd_safe"] is True
    assert created[0]["cad_quad_invalid_edges"] == 0
    return created[0]


def main():
    module = "bl_ext.user_default.requad"
    if module not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=module)
    orthographic_relief.register()
    try:
        source, reference_top = make_fine_relief()

        select_only(source)
        native_result = quad_remesh_for_cad(
            source_object=source.name,
            output_name="FineRelief_Native",
            target_faces=5000,
            preserve_sharp=True,
            apply_modifiers=True,
        )
        native = bpy.data.objects[native_result["object_name"]]

        uniform = run_requad(source, 0.0)
        uniform.name = "FineRelief_ReQuad_Uniform"
        adaptive = run_requad(source, 100.0)
        adaptive.name = "FineRelief_ReQuad_Adaptive"

        results = {
            "native": metrics(native, reference_top),
            "requad_uniform": metrics(uniform, reference_top),
            "requad_adaptive": metrics(adaptive, reference_top),
        }
        print("ADAPTIVE_REMESH_EVALUATION", results)
        assert all(result["all_quads"] for result in results.values())
        assert all(result["invalid"] == 0 for result in results.values())
        assert results["requad_adaptive"]["boundary"] > 0
        assert (
            results["requad_adaptive"]["detail_mean"]
            < results["native"]["detail_mean"] * 0.7
        )
    finally:
        orthographic_relief.unregister()
        bpy.ops.preferences.addon_disable(module=module)


if __name__ == "__main__":
    main()
