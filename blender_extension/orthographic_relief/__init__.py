"""Manual Blender UI for the Orthographic Relief extension.

This package intentionally contains no MCP bridge, network listener, or background
service. All work starts from an explicit user action in Blender.
"""

from __future__ import annotations

import traceback

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from .core import generate_relief, quad_remesh_for_cad


class ORTHORELIEF_PG_Settings(bpy.types.PropertyGroup):
    output_name: StringProperty(
        name="Output Name",
        description="Leave empty to derive the name from the active mesh",
        default="",
    )
    projection: EnumProperty(
        name="View From",
        items=[
            ("Z", "+Z", "Project from +Z toward -Z"),
            ("-Z", "-Z", "Project from -Z toward +Z"),
            ("X", "+X", "Project from +X toward -X"),
            ("-X", "-X", "Project from -X toward +X"),
            ("Y", "+Y", "Project from +Y toward -Y"),
            ("-Y", "-Y", "Project from -Y toward +Y"),
            ("CAMERA", "Camera", "Use the active scene camera orientation"),
        ],
        default="Z",
    )
    resolution: IntProperty(
        name="Longest Axis",
        description="Height-field samples along the longest projected axis",
        default=512,
        min=8,
        max=1024,
    )
    fit_resolution_to_aspect: BoolProperty(
        name="Fit Resolution to Aspect",
        description=(
            "Reduce samples along the shorter projected axis to preserve detail "
            "while avoiding unnecessary geometry"
        ),
        default=True,
    )
    relief_height: FloatProperty(
        name="Relief Height",
        description="Maximum height above the front of the base",
        default=0.25,
        min=0.00001,
        unit="LENGTH",
    )
    base_thickness: FloatProperty(
        name="Base Thickness",
        default=0.1,
        min=0.00001,
        unit="LENGTH",
    )
    base_shape: EnumProperty(
        name="Base Shape",
        description="Choose whether the solid follows the projected source outline",
        items=[
            (
                "SILHOUETTE",
                "Source Silhouette",
                "Trim the base, back, and side wall to the projected source outline",
            ),
            (
                "RECTANGLE",
                "Rectangle",
                "Keep the original rectangular plaque around the relief",
            ),
        ],
        default="SILHOUETTE",
    )
    margin: FloatProperty(
        name="Margin",
        description="Fractional border around the projected source",
        default=0.05,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    blur_radius: FloatProperty(
        name="Gaussian Blur",
        description="Blur radius in image pixels",
        default=1.25,
        min=0.0,
        max=64.0,
    )
    depth_gamma: FloatProperty(
        name="Depth Gamma",
        description="Adjust depth-to-height contrast",
        default=1.0,
        min=0.05,
        max=10.0,
    )
    minimum_height: FloatProperty(
        name="Minimum Height",
        description="Minimum normalized height inside the source silhouette",
        default=0.03,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    smooth_factor: FloatProperty(
        name="Corrective Smooth",
        default=0.15,
        min=-10.0,
        max=10.0,
    )
    smooth_iterations: IntProperty(
        name="Smooth Iterations",
        default=2,
        min=0,
        max=200,
    )
    save_images: BoolProperty(
        name="Save PNG Images",
        description="Save the raw depth and blurred height images as PNG files",
        default=True,
    )
    output_directory: StringProperty(
        name="Image Directory",
        description="Directory for generated PNG images",
        default="//relief_output",
        subtype="DIR_PATH",
    )
    quad_target_faces: IntProperty(
        name="Target Quad Faces",
        description="Approximate face count for the Rhino/SubD-friendly copy",
        default=20000,
        min=4,
        max=2000000,
    )
    quad_preserve_sharp: BoolProperty(
        name="Preserve Sharp Edges",
        description=(
            "Retain rim and back creases; the resulting unwelded boundary seams "
            "are intentional and can become creases with Rhino ToSubD"
        ),
        default=True,
    )
    quad_preserve_boundary: BoolProperty(
        name="Preserve Open Boundaries",
        description="Preserve boundary loops on open input meshes",
        default=False,
    )
    quad_use_symmetry: BoolProperty(
        name="Use Mesh Symmetry",
        description="Generate symmetric topology using the mesh symmetry settings",
        default=False,
    )
    quad_apply_modifiers: BoolProperty(
        name="Bake Modifiers",
        description="Bake Corrective Smooth and other modifiers into the remesh source",
        default=True,
    )


class ORTHORELIEF_OT_Generate(bpy.types.Operator):
    bl_idname = "object.generate_orthographic_relief"
    bl_label = "Generate Orthographic Relief"
    bl_description = (
        "Create a blurred solid height-field relief from the active mesh; "
        "the result has no undercuts along the selected projection"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        settings = context.scene.orthographic_relief_settings
        source = context.active_object
        try:
            result = generate_relief(
                source_object=source.name,
                output_name=settings.output_name.strip() or None,
                projection=settings.projection,
                resolution_x=settings.resolution,
                resolution_y=settings.resolution,
                fit_resolution_to_aspect=settings.fit_resolution_to_aspect,
                relief_height=settings.relief_height,
                base_thickness=settings.base_thickness,
                base_shape=settings.base_shape,
                margin=settings.margin,
                blur_radius=settings.blur_radius,
                depth_gamma=settings.depth_gamma,
                minimum_height=settings.minimum_height,
                corrective_smooth_factor=settings.smooth_factor,
                corrective_smooth_iterations=settings.smooth_iterations,
                save_images=settings.save_images,
                output_directory=settings.output_directory,
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Created {result['object_name']}")
        return {"FINISHED"}


class ORTHORELIEF_OT_CADQuadRemesh(bpy.types.Operator):
    bl_idname = "object.orthorelief_cad_quad_remesh"
    bl_label = "Create CAD Quad Copy"
    bl_description = (
        "Duplicate the active mesh and rebuild it as a lower-density all-quad "
        "mesh for Rhino SubD/NURBS conversion; retained creases may be open seams"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == "MESH"

    def execute(self, context):
        settings = context.scene.orthographic_relief_settings
        source = context.active_object
        try:
            result = quad_remesh_for_cad(
                source_object=source.name,
                target_faces=settings.quad_target_faces,
                preserve_sharp=settings.quad_preserve_sharp,
                preserve_boundary=settings.quad_preserve_boundary,
                use_mesh_symmetry=settings.quad_use_symmetry,
                apply_modifiers=settings.quad_apply_modifiers,
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        if not result["subd_safe"]:
            self.report(
                {"WARNING"},
                f"Created {result['object_name']}, but topology validation found issues",
            )
        else:
            message = (
                f"Created {result['object_name']}: {result['face_count']:,} quads, "
                f"max deviation {result['max_deviation']:.6g}"
            )
            if result["boundary_edge_count"]:
                message += (
                    f"; {result['boundary_edge_count']:,} intentional crease "
                    "boundary edges"
                )
            else:
                message += "; closed manifold"
            self.report({"INFO"}, message)
        return {"FINISHED"}


class ORTHORELIEF_PT_MainPanel(bpy.types.Panel):
    bl_label = "Orthographic Relief"
    bl_idname = "ORTHORELIEF_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Relief"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.orthographic_relief_settings
        active = context.active_object

        source_box = layout.box()
        source_box.label(
            text=f"Source: {active.name if active and active.type == 'MESH' else 'Select a mesh'}",
            icon="MESH_DATA",
        )
        source_box.prop(settings, "output_name")
        source_box.prop(settings, "projection")

        image_box = layout.box()
        image_box.label(text="Depth Image", icon="IMAGE_DATA")
        image_box.prop(settings, "resolution")
        image_box.prop(settings, "fit_resolution_to_aspect")
        maximum_vertices = settings.resolution * settings.resolution
        if settings.base_shape == "SILHOUETTE":
            maximum_vertices *= 2
        else:
            maximum_vertices += 4
        image_box.label(text=f"Maximum vertices: {maximum_vertices:,}")
        if settings.resolution > 768:
            image_box.label(text="High memory usage; generation may take time", icon="ERROR")
        image_box.prop(settings, "margin")
        image_box.prop(settings, "blur_radius")
        image_box.prop(settings, "depth_gamma")
        image_box.prop(settings, "minimum_height")

        geometry_box = layout.box()
        geometry_box.label(text="Relief Geometry", icon="MOD_DISPLACE")
        geometry_box.prop(settings, "base_shape")
        geometry_box.prop(settings, "relief_height")
        geometry_box.prop(settings, "base_thickness")
        geometry_box.prop(settings, "smooth_factor")
        geometry_box.prop(settings, "smooth_iterations")

        output_box = layout.box()
        output_box.prop(settings, "save_images")
        column = output_box.column()
        column.enabled = settings.save_images
        column.prop(settings, "output_directory")

        layout.operator(
            "object.generate_orthographic_relief",
            text="Generate Relief",
            icon="MOD_DISPLACE",
        )
        layout.label(text="Undercut-free along the selected view direction", icon="INFO")

        quad_box = layout.box()
        quad_box.label(text="CAD / Rhino Quad Mesh", icon="MESH_GRID")
        quad_box.prop(settings, "quad_target_faces")
        quad_box.prop(settings, "quad_apply_modifiers")
        quad_box.prop(settings, "quad_preserve_sharp")
        if settings.quad_preserve_sharp:
            quad_box.label(text="Open seams become Rhino SubD creases", icon="INFO")
        else:
            quad_box.label(text="Sharp seams off: prefer a closed solid", icon="INFO")
        quad_box.prop(settings, "quad_preserve_boundary")
        quad_box.prop(settings, "quad_use_symmetry")
        quad_box.operator(
            "object.orthorelief_cad_quad_remesh",
            text="Create CAD Quad Copy",
            icon="MOD_REMESH",
        )
        quad_box.label(text="Rhino: OBJ > ToSubD > ToNURBS > STEP", icon="INFO")


CLASSES = (
    ORTHORELIEF_PG_Settings,
    ORTHORELIEF_OT_Generate,
    ORTHORELIEF_OT_CADQuadRemesh,
    ORTHORELIEF_PT_MainPanel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.orthographic_relief_settings = PointerProperty(
        type=ORTHORELIEF_PG_Settings
    )


def unregister():
    del bpy.types.Scene.orthographic_relief_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
