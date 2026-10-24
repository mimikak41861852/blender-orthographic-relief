"""Validate the Blender-native QuadriFlow wrapper for the Rhino workflow."""

import pathlib
import sys

import bmesh
import bpy


REPOSITORY = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "blender_extension"))

import orthographic_relief  # noqa: E402


def inspect_topology(mesh_object):
    check_mesh = bmesh.new()
    try:
        check_mesh.from_mesh(mesh_object.data)
        boundary_edges = sum(
            1 for edge in check_mesh.edges if len(edge.link_faces) == 1
        )
        invalid_edges = sum(
            1 for edge in check_mesh.edges if len(edge.link_faces) not in {1, 2}
        )
        isolated_vertices = sum(
            1 for vertex in check_mesh.verts if not vertex.link_edges
        )
        signed_volume = check_mesh.calc_volume(signed=True)
    finally:
        check_mesh.free()
    return boundary_edges, invalid_edges, isolated_vertices, signed_volume


def main():
    orthographic_relief.register()
    try:
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
        source = bpy.context.active_object
        source.name = "CADQuadSource"
        source.scale = (1.0, 0.9, 0.45)
        bpy.context.view_layer.update()

        settings = bpy.context.scene.orthographic_relief_settings
        settings.output_name = "CADQuadRelief"
        settings.projection = "Z"
        settings.resolution = 96
        settings.base_shape = "SILHOUETTE"
        settings.relief_height = 0.2
        settings.base_thickness = 0.08
        settings.blur_radius = 1.25
        settings.smooth_factor = 0.15
        settings.smooth_iterations = 2
        settings.save_images = False

        status = bpy.ops.object.generate_orthographic_relief()
        assert status == {"FINISHED"}
        relief = bpy.context.active_object
        relief_face_count = len(relief.data.polygons)
        assert relief.modifiers.get("Relief Corrective Smooth") is not None

        settings.quad_target_faces = 1500
        settings.quad_apply_modifiers = True
        settings.quad_preserve_sharp = True
        settings.quad_preserve_boundary = False
        settings.quad_use_symmetry = False
        status = bpy.ops.object.orthorelief_cad_quad_remesh()
        assert status == {"FINISHED"}

        crease_quad = bpy.context.active_object
        assert crease_quad is not relief
        assert crease_quad["cad_quad_source"] == relief.name
        assert crease_quad["cad_quad_all_quads"] is True
        assert crease_quad["cad_quad_subd_safe"] is True
        assert crease_quad["cad_quad_closed_manifold"] is False
        assert crease_quad["cad_quad_boundary_edges"] > 0
        assert crease_quad["cad_quad_invalid_edges"] == 0
        assert crease_quad["cad_quad_isolated_vertices"] == 0
        assert len(crease_quad.data.polygons) < relief_face_count
        assert all(len(polygon.vertices) == 4 for polygon in crease_quad.data.polygons)
        assert len(crease_quad.modifiers) == 0

        boundary, invalid, isolated, _volume = inspect_topology(crease_quad)
        assert boundary == crease_quad["cad_quad_boundary_edges"]
        assert invalid == 0
        assert isolated == 0

        diagonal = crease_quad.dimensions.length
        assert crease_quad["cad_quad_max_deviation"] < diagonal * 0.05

        for selected in list(bpy.context.selected_objects):
            selected.select_set(False)
        relief.select_set(True)
        bpy.context.view_layer.objects.active = relief
        settings.quad_preserve_sharp = False
        status = bpy.ops.object.orthorelief_cad_quad_remesh()
        assert status == {"FINISHED"}

        closed_quad = bpy.context.active_object
        assert closed_quad is not crease_quad
        assert closed_quad["cad_quad_all_quads"] is True
        assert closed_quad["cad_quad_subd_safe"] is True
        assert closed_quad["cad_quad_closed_manifold"] is True
        assert closed_quad["cad_quad_boundary_edges"] == 0
        assert closed_quad["cad_quad_invalid_edges"] == 0
        boundary, invalid, isolated, signed_volume = inspect_topology(closed_quad)
        assert boundary == 0
        assert invalid == 0
        assert isolated == 0
        assert signed_volume > 0.0

        closed_diagonal = closed_quad.dimensions.length
        assert closed_quad["cad_quad_max_deviation"] < closed_diagonal * 0.05
        print(
            "CAD_QUAD_REMESH_OK",
            {
                "blender": bpy.app.version_string,
                "source_faces": relief_face_count,
                "crease_faces": len(crease_quad.data.polygons),
                "crease_boundary_edges": crease_quad["cad_quad_boundary_edges"],
                "closed_faces": len(closed_quad.data.polygons),
                "closed_manifold": closed_quad["cad_quad_closed_manifold"],
                "max_deviation": max(
                    crease_quad["cad_quad_max_deviation"],
                    closed_quad["cad_quad_max_deviation"],
                ),
            },
        )
    finally:
        orthographic_relief.unregister()


if __name__ == "__main__":
    main()
