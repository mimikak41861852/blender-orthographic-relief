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

from .core import (
    PREVIEW_OBJECT_NAME,
    finalize_adaptive_quad_for_cad,
    generate_relief,
    quad_remesh_for_cad,
    refresh_relief_preview,
    remove_relief_preview,
)


REQUAD_RELEASE_URL = "https://github.com/mlstr0m/requad/releases/latest"
_preview_request_id = 0
_adaptive_request_id = 0


def _requad_available(context) -> bool:
    if context is None or not hasattr(context.scene, "requad"):
        return False
    return any(
        module == "requad" or module.endswith(".requad")
        for module in context.preferences.addons.keys()
    )


def _select_preview(preview) -> None:
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    preview.hide_set(False)
    preview.select_set(True)
    bpy.context.view_layer.objects.active = preview


def _refresh_preview_scene(scene):
    settings = scene.orthographic_relief_settings
    source = bpy.data.objects.get(settings.preview_source)
    if source is None or source.type != "MESH":
        raise ValueError("Select a source mesh and restart Live Preview")
    result = refresh_relief_preview(
        source_object=source.name,
        projection=settings.projection,
        preview_resolution=settings.preview_resolution,
        final_resolution=settings.resolution,
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
    )
    preview = bpy.data.objects[result["object_name"]]
    _select_preview(preview)
    settings.preview_status = (
        f"Live {result['resolution'][0]}x{result['resolution'][1]} | "
        f"{result['face_count']:,} faces"
    )
    return result


def _stop_preview_scene(scene, restore_selection=True):
    global _preview_request_id
    _preview_request_id += 1
    settings = scene.orthographic_relief_settings
    settings.preview_enabled = False
    source = bpy.data.objects.get(settings.preview_source)
    remove_relief_preview()
    if source is not None:
        source.hide_set(settings.preview_source_was_hidden)
        if restore_selection and not settings.preview_source_was_hidden:
            for selected in list(bpy.context.selected_objects):
                selected.select_set(False)
            source.select_set(True)
            bpy.context.view_layer.objects.active = source
    settings.preview_status = ""
    settings.preview_source = ""
    settings.preview_source_was_hidden = False


def _preview_setting_changed(self, context):
    global _preview_request_id
    if (
        context is None
        or bpy.app.background
        or not self.preview_enabled
        or not self.preview_auto_update
    ):
        return
    _preview_request_id += 1
    request_id = _preview_request_id
    scene_name = context.scene.name

    def refresh_after_debounce():
        if request_id != _preview_request_id:
            return None
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return None
        settings = getattr(scene, "orthographic_relief_settings", None)
        if settings is None or not settings.preview_enabled:
            return None
        try:
            _refresh_preview_scene(scene)
        except Exception as exc:
            traceback.print_exc()
            settings.preview_status = f"Preview error: {exc}"
        return None

    bpy.app.timers.register(refresh_after_debounce, first_interval=0.2)


def _find_adaptive_output(source_name, before_names):
    prefix = source_name + "_requad"
    candidates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and obj.name not in before_names
        and obj.name.startswith(prefix)
    ]
    return max(candidates, key=lambda obj: obj.name, default=None)


def _finish_adaptive_output(
    scene,
    source_name,
    before_names,
    target_faces,
    preserve_sharp,
    sharp_angle,
):
    settings = scene.orthographic_relief_settings
    output = _find_adaptive_output(source_name, before_names)
    if output is None:
        settings.quad_status = "Adaptive remesh ended without an output mesh"
        return None
    result = finalize_adaptive_quad_for_cad(
        source_object=source_name,
        output_object=output.name,
        target_faces=target_faces,
        preserve_sharp=preserve_sharp,
        sharp_angle=sharp_angle,
    )
    if result["subd_safe"]:
        settings.quad_status = (
            f"Adaptive: {result['face_count']:,} quads | "
            f"crease boundaries {result['boundary_edge_count']:,} | "
            f"coverage p95 {result['coverage_p95']:.5g}"
        )
    else:
        settings.quad_status = (
            f"Adaptive result needs review: {result['non_quad_face_count']} "
            f"non-quads, {result['invalid_edge_count']} invalid edges"
        )
    return result


def _watch_adaptive_output(
    scene_name,
    source_name,
    before_names,
    target_faces,
    preserve_sharp,
    sharp_angle,
):
    global _adaptive_request_id
    _adaptive_request_id += 1
    request_id = _adaptive_request_id

    def poll_requad():
        if request_id != _adaptive_request_id:
            return None
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return None
        progress = getattr(bpy.context.window_manager, "requad_progress", -1)
        if progress >= 0:
            return 0.25
        try:
            _finish_adaptive_output(
                scene,
                source_name,
                before_names,
                target_faces,
                preserve_sharp,
                sharp_angle,
            )
        except Exception as exc:
            traceback.print_exc()
            scene.orthographic_relief_settings.quad_status = (
                f"Adaptive post-process error: {exc}"
            )
        return None

    bpy.app.timers.register(poll_requad, first_interval=0.25)


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
        update=_preview_setting_changed,
    )
    resolution: IntProperty(
        name="Longest Axis",
        description="Height-field samples along the longest projected axis",
        default=512,
        min=8,
        max=1024,
        update=_preview_setting_changed,
    )
    fit_resolution_to_aspect: BoolProperty(
        name="Fit Resolution to Aspect",
        description=(
            "Reduce samples along the shorter projected axis to preserve detail "
            "while avoiding unnecessary geometry"
        ),
        default=True,
        update=_preview_setting_changed,
    )
    relief_height: FloatProperty(
        name="Relief Height",
        description="Maximum height above the front of the base",
        default=0.25,
        min=0.00001,
        unit="LENGTH",
        update=_preview_setting_changed,
    )
    base_thickness: FloatProperty(
        name="Base Thickness",
        default=0.1,
        min=0.00001,
        unit="LENGTH",
        update=_preview_setting_changed,
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
        update=_preview_setting_changed,
    )
    margin: FloatProperty(
        name="Margin",
        description="Fractional border around the projected source",
        default=0.05,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_preview_setting_changed,
    )
    blur_radius: FloatProperty(
        name="Gaussian Blur",
        description="Blur radius in image pixels",
        default=1.25,
        min=0.0,
        max=64.0,
        update=_preview_setting_changed,
    )
    depth_gamma: FloatProperty(
        name="Depth Gamma",
        description="Adjust depth-to-height contrast",
        default=1.0,
        min=0.05,
        max=10.0,
        update=_preview_setting_changed,
    )
    minimum_height: FloatProperty(
        name="Minimum Height",
        description="Minimum normalized height inside the source silhouette",
        default=0.03,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_preview_setting_changed,
    )
    smooth_factor: FloatProperty(
        name="Corrective Smooth",
        default=0.15,
        min=-10.0,
        max=10.0,
        update=_preview_setting_changed,
    )
    smooth_iterations: IntProperty(
        name="Smooth Iterations",
        default=2,
        min=0,
        max=200,
        update=_preview_setting_changed,
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
    preview_resolution: IntProperty(
        name="Preview Resolution",
        description="Low-resolution longest axis used for responsive 3D preview",
        default=128,
        min=32,
        max=256,
        update=_preview_setting_changed,
    )
    preview_auto_update: BoolProperty(
        name="Auto Update",
        description="Refresh the preview after Margin, Blur, Gamma, or geometry changes",
        default=True,
        update=_preview_setting_changed,
    )
    preview_enabled: BoolProperty(default=False, options={"HIDDEN"})
    preview_source: StringProperty(default="", options={"HIDDEN"})
    preview_source_was_hidden: BoolProperty(default=False, options={"HIDDEN"})
    preview_status: StringProperty(default="", options={"HIDDEN"})
    quad_backend: EnumProperty(
        name="Remesher",
        items=[
            (
                "REQUAD_ADAPTIVE",
                "Adaptive Detail (ReQuad)",
                "Curvature-adaptive QuadWild bi-MDF topology with optional density paint",
            ),
            (
                "QUADRIFLOW_NATIVE",
                "Blender QuadriFlow",
                "Blender's bundled uniform-density QuadriFlow remesher",
            ),
        ],
        default="REQUAD_ADAPTIVE",
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
    quad_adaptive_size: FloatProperty(
        name="Detail Adaptivity",
        description="Use smaller quads on curved detail and larger quads on flat regions",
        default=100.0,
        min=0.0,
        max=100.0,
        subtype="PERCENTAGE",
    )
    quad_adaptive_count: BoolProperty(
        name="Quality Priority",
        description="Allow adaptive sizing to take priority over an exact target count",
        default=False,
    )
    quad_paint_density: BoolProperty(
        name="Use Density Paint",
        description=(
            "Use the active color attribute: red creates finer quads and cyan "
            "creates coarser quads"
        ),
        default=False,
    )
    quad_sharp_angle: FloatProperty(
        name="Sharp Angle",
        description="Feature angle for ReQuad guides and optional Rhino crease seams",
        default=35.0,
        min=0.0,
        max=90.0,
    )
    quad_relax_iterations: IntProperty(
        name="Project / Relax",
        description="Relax quad flow and re-project every pass onto the detailed source",
        default=20,
        min=0,
        max=50,
    )
    quad_status: StringProperty(default="", options={"HIDDEN"})


class ORTHORELIEF_OT_PreviewStart(bpy.types.Operator):
    bl_idname = "object.orthorelief_preview_start"
    bl_label = "Start Live Preview"
    bl_description = "Create a low-resolution relief and update it while settings change"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        active = context.active_object
        return (
            active is not None
            and active.type == "MESH"
            and not bool(active.get("relief_live_preview", False))
        )

    def execute(self, context):
        settings = context.scene.orthographic_relief_settings
        source = context.active_object
        settings.preview_source = source.name
        settings.preview_source_was_hidden = source.hide_get()
        settings.preview_enabled = True
        source.hide_set(True)
        try:
            result = _refresh_preview_scene(context.scene)
        except Exception as exc:
            traceback.print_exc()
            _stop_preview_scene(context.scene)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Live preview: {result['resolution'][0]}x{result['resolution'][1]}",
        )
        return {"FINISHED"}


class ORTHORELIEF_OT_PreviewRefresh(bpy.types.Operator):
    bl_idname = "object.orthorelief_preview_refresh"
    bl_label = "Refresh Preview"
    bl_description = "Refresh the low-resolution relief preview now"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "orthographic_relief_settings", None)
        return settings is not None and settings.preview_enabled

    def execute(self, context):
        try:
            _refresh_preview_scene(context.scene)
        except Exception as exc:
            traceback.print_exc()
            context.scene.orthographic_relief_settings.preview_status = (
                f"Preview error: {exc}"
            )
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class ORTHORELIEF_OT_PreviewStop(bpy.types.Operator):
    bl_idname = "object.orthorelief_preview_stop"
    bl_label = "Stop Preview"
    bl_description = "Remove the temporary preview and restore the source object"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "orthographic_relief_settings", None)
        return settings is not None and settings.preview_enabled

    def execute(self, context):
        _stop_preview_scene(context.scene)
        return {"FINISHED"}


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
        settings = getattr(context.scene, "orthographic_relief_settings", None)
        if settings is not None and settings.preview_enabled:
            source = bpy.data.objects.get(settings.preview_source)
            return source is not None and source.type == "MESH"
        return (
            context.active_object is not None
            and context.active_object.type == "MESH"
            and not bool(context.active_object.get("relief_live_preview", False))
        )

    def execute(self, context):
        settings = context.scene.orthographic_relief_settings
        source = (
            bpy.data.objects.get(settings.preview_source)
            if settings.preview_enabled
            else context.active_object
        )
        if settings.preview_enabled:
            _stop_preview_scene(context.scene)
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
        return (
            context.active_object is not None
            and context.active_object.type == "MESH"
            and not bool(context.active_object.get("relief_live_preview", False))
        )

    def execute(self, context):
        settings = context.scene.orthographic_relief_settings
        source = context.active_object
        settings.quad_status = ""

        if settings.quad_backend == "REQUAD_ADAPTIVE":
            if not _requad_available(context):
                self.report(
                    {"ERROR"},
                    "ReQuad is not installed or enabled; install it from the official release",
                )
                return {"CANCELLED"}

            requad = context.scene.requad
            # Organic performs ReQuad's quad-only singularity cleanup. Rhino
            # crease seams are added deterministically in our post-process.
            requad.preset = "ORGANIC"
            requad.target_count = settings.quad_target_faces
            requad.count_mode = "QUADS"
            requad.adaptive_size = settings.quad_adaptive_size
            requad.adaptive_count = settings.quad_adaptive_count
            requad.use_paint_density = settings.quad_paint_density
            requad.pre_remesh = True
            requad.relax_iterations = settings.quad_relax_iterations
            requad.sharp_angle = settings.quad_sharp_angle
            requad.guide_sharp = True
            requad.guide_seams = False
            requad.material_guides = False
            requad.keep_materials = False
            requad.transfer_uvs = False
            requad.transfer_weights = False
            requad.smooth_result = True
            requad.hide_original = False
            before_names = set(bpy.data.objects.keys())
            settings.quad_status = "Adaptive remesh running..."
            try:
                status = bpy.ops.requad.remesh()
            except Exception as exc:
                traceback.print_exc()
                settings.quad_status = f"Adaptive remesh error: {exc}"
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

            if "CANCELLED" in status:
                settings.quad_status = "Adaptive remesh was cancelled"
                return {"CANCELLED"}
            if "FINISHED" in status:
                try:
                    result = _finish_adaptive_output(
                        context.scene,
                        source.name,
                        before_names,
                        settings.quad_target_faces,
                        settings.quad_preserve_sharp,
                        settings.quad_sharp_angle,
                    )
                except Exception as exc:
                    traceback.print_exc()
                    settings.quad_status = f"Adaptive post-process error: {exc}"
                    self.report({"ERROR"}, str(exc))
                    return {"CANCELLED"}
                if result is None:
                    self.report({"ERROR"}, settings.quad_status)
                    return {"CANCELLED"}
                self.report({"INFO"}, settings.quad_status)
            else:
                _watch_adaptive_output(
                    context.scene.name,
                    source.name,
                    before_names,
                    settings.quad_target_faces,
                    settings.quad_preserve_sharp,
                    settings.quad_sharp_angle,
                )
                self.report({"INFO"}, "Adaptive remesh started; progress is shown by ReQuad")
            return {"FINISHED"}

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
                f"coverage p95 {result['coverage_p95']:.6g}"
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
        source_name = (
            settings.preview_source
            if settings.preview_enabled
            else active.name if active and active.type == "MESH" else "Select a mesh"
        )

        source_box = layout.box()
        source_box.label(
            text=f"Source: {source_name}",
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

        preview_box = layout.box()
        preview_box.label(text="Live 3D Preview", icon="HIDE_OFF")
        preview_box.prop(settings, "preview_resolution")
        preview_box.prop(settings, "preview_auto_update")
        if settings.preview_enabled:
            row = preview_box.row(align=True)
            row.operator(
                "object.orthorelief_preview_refresh",
                text="Refresh",
                icon="FILE_REFRESH",
            )
            row.operator(
                "object.orthorelief_preview_stop",
                text="Stop",
                icon="CANCEL",
            )
            if settings.preview_status:
                preview_box.label(text=settings.preview_status, icon="INFO")
        else:
            preview_box.operator(
                "object.orthorelief_preview_start",
                text="Start Live Preview",
                icon="PLAY",
            )
        preview_box.label(text="Margin / Blur / Gamma update after 0.2 s", icon="INFO")

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
        quad_box.prop(settings, "quad_backend")
        quad_box.prop(settings, "quad_target_faces")
        quad_box.prop(settings, "quad_preserve_sharp")
        if settings.quad_preserve_sharp:
            quad_box.label(text="Open seams become Rhino SubD creases", icon="INFO")
        else:
            quad_box.label(text="Sharp seams off: prefer a closed solid", icon="INFO")
        if settings.quad_backend == "REQUAD_ADAPTIVE":
            if _requad_available(context):
                quad_box.prop(settings, "quad_adaptive_size", slider=True)
                quad_box.prop(settings, "quad_adaptive_count")
                quad_box.prop(settings, "quad_paint_density")
                quad_box.prop(settings, "quad_sharp_angle")
                quad_box.prop(settings, "quad_relax_iterations")
                quad_box.label(text="Fine detail gets smaller local quads", icon="INFO")
                quad_box.operator(
                    "object.orthorelief_cad_quad_remesh",
                    text="Create Adaptive CAD Quad Copy",
                    icon="MOD_REMESH",
                )
            else:
                quad_box.label(text="ReQuad is not installed or enabled", icon="ERROR")
                download = quad_box.operator(
                    "wm.url_open",
                    text="Open Official ReQuad Download",
                    icon="URL",
                )
                download.url = REQUAD_RELEASE_URL
        else:
            quad_box.prop(settings, "quad_apply_modifiers")
            quad_box.prop(settings, "quad_preserve_boundary")
            quad_box.prop(settings, "quad_use_symmetry")
            quad_box.operator(
                "object.orthorelief_cad_quad_remesh",
                text="Create Native CAD Quad Copy",
                icon="MOD_REMESH",
            )
        if settings.quad_status:
            quad_box.label(text=settings.quad_status, icon="INFO")
        quad_box.label(text="Rhino: OBJ > ToSubD > ToNURBS > STEP", icon="INFO")


CLASSES = (
    ORTHORELIEF_PG_Settings,
    ORTHORELIEF_OT_PreviewStart,
    ORTHORELIEF_OT_PreviewRefresh,
    ORTHORELIEF_OT_PreviewStop,
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
    global _preview_request_id, _adaptive_request_id
    _preview_request_id += 1
    _adaptive_request_id += 1
    for scene in bpy.data.scenes:
        settings = getattr(scene, "orthographic_relief_settings", None)
        if settings is not None and settings.preview_enabled:
            _stop_preview_scene(scene, restore_selection=False)
    remove_relief_preview()
    del bpy.types.Scene.orthographic_relief_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
