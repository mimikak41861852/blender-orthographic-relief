"""Exercise the installed Orthographic Relief + ReQuad extension pair."""

import bpy


enabled = set(bpy.context.preferences.addons.keys())
assert any(name.endswith(".orthographic_relief") for name in enabled), enabled
assert any(name.endswith(".requad") for name in enabled), enabled

bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
source = bpy.context.active_object
source.name = "InstalledAdaptiveSource"
source.scale = (1.0, 0.85, 0.45)
bpy.context.view_layer.update()

settings = bpy.context.scene.orthographic_relief_settings
settings.output_name = "InstalledAdaptiveRelief"
settings.resolution = 72
settings.base_shape = "SILHOUETTE"
settings.blur_radius = 1.5
settings.save_images = False
assert bpy.ops.object.generate_orthographic_relief() == {"FINISHED"}
relief = bpy.context.active_object

settings.quad_backend = "REQUAD_ADAPTIVE"
settings.quad_target_faces = 1200
settings.quad_adaptive_size = 100.0
settings.quad_adaptive_count = False
settings.quad_preserve_sharp = True
settings.quad_sharp_angle = 35.0
settings.quad_relax_iterations = 12
assert bpy.ops.object.orthorelief_cad_quad_remesh() == {"FINISHED"}

result = bpy.context.active_object
assert result is not relief
assert result["cad_quad_backend"] == "REQUAD_ADAPTIVE"
assert result["cad_quad_all_quads"] is True
assert result["cad_quad_subd_safe"] is True
assert result["cad_quad_invalid_edges"] == 0
assert result["cad_quad_non_quad_faces"] == 0
assert result["cad_quad_feature_edges_split"] > 0
assert result["cad_quad_boundary_edges"] > 0
assert result["cad_quad_coverage_p95"] >= 0.0

print(
    "INSTALLED_ADAPTIVE_OK",
    {
        "blender": bpy.app.version_string,
        "source_faces": len(relief.data.polygons),
        "quad_faces": len(result.data.polygons),
        "boundary_edges": result["cad_quad_boundary_edges"],
        "coverage_p95": result["cad_quad_coverage_p95"],
    },
)
