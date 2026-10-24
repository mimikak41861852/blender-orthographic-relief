"""Run against normal Blender preferences to verify the installed extension."""

import bpy


enabled = set(bpy.context.preferences.addons.keys())
manual_module = next(
    (name for name in enabled if name.endswith(".orthographic_relief")), None
)
assert manual_module is not None, f"Manual extension is not enabled: {sorted(enabled)}"
assert "relief_mcp" not in enabled, f"MCP add-on must not be enabled in 5.2: {enabled}"

bpy.ops.mesh.primitive_cube_add(size=2.0)
source = bpy.context.active_object
source.name = "InstalledExtensionSource"
settings = bpy.context.scene.orthographic_relief_settings
assert settings.bl_rna.properties["resolution"].hard_max == 1024
assert settings.fit_resolution_to_aspect is True
settings.output_name = "InstalledExtensionRelief"
settings.resolution = 24
settings.blur_radius = 1.0
settings.save_images = False
status = bpy.ops.object.generate_orthographic_relief()
assert status == {"FINISHED"}
result = bpy.data.objects["InstalledExtensionRelief"]
assert result["relief_projection_is_height_field"] is True

print(
    "INSTALLED_MANUAL_EXTENSION_OK",
    {
        "blender": bpy.app.version_string,
        "module": manual_module,
        "mcp_addon_enabled": False,
        "resolution_max": 1024,
        "object": result.name,
    },
)
