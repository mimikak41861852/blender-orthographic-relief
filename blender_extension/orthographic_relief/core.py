"""Geometry and image generation for the standalone Orthographic Relief extension."""

from __future__ import annotations

import math
import os
import re
import tempfile
from typing import Any, Dict, Optional, Tuple

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


PROJECTION_AXES = {"X", "-X", "Y", "-Y", "Z", "-Z", "CAMERA"}
BASE_SHAPES = {"SILHOUETTE", "RECTANGLE"}
PREVIEW_OBJECT_NAME = "__Orthographic_Relief_Live_Preview__"


def _projection_basis(
    projection: str, camera: Optional[bpy.types.Object]
) -> Tuple[Vector, Vector, Vector]:
    """Return screen-right, screen-up, and ray direction in world space."""
    projection = projection.upper()
    if projection == "CAMERA":
        if camera is None or camera.type != "CAMERA":
            raise ValueError("CAMERA projection requires an active scene camera")
        rotation = camera.matrix_world.to_quaternion()
        right = rotation @ Vector((1.0, 0.0, 0.0))
        up = rotation @ Vector((0.0, 1.0, 0.0))
        ray_direction = rotation @ Vector((0.0, 0.0, -1.0))
        return right.normalized(), up.normalized(), ray_direction.normalized()

    bases = {
        "Z": ((1, 0, 0), (0, 1, 0), (0, 0, -1)),
        "-Z": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
        "X": ((0, 1, 0), (0, 0, 1), (-1, 0, 0)),
        "-X": ((0, -1, 0), (0, 0, 1), (1, 0, 0)),
        "Y": ((-1, 0, 0), (0, 0, 1), (0, -1, 0)),
        "-Y": ((1, 0, 0), (0, 0, 1), (0, 1, 0)),
    }
    if projection not in bases:
        raise ValueError(
            "projection must be one of " + ", ".join(sorted(PROJECTION_AXES))
        )
    right, up, ray_direction = bases[projection]
    return Vector(right), Vector(up), Vector(ray_direction)


def _evaluated_world_geometry(
    source: bpy.types.Object,
) -> Tuple[list[Vector], list[tuple[int, ...]]]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = source.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world.copy()
        vertices = [matrix @ vertex.co for vertex in mesh.vertices]
        polygons = [tuple(polygon.vertices) for polygon in mesh.polygons]
    finally:
        evaluated.to_mesh_clear()

    if not vertices or not polygons:
        raise ValueError(f"Source object {source.name!r} has no renderable mesh faces")
    return vertices, polygons


def _gaussian_blur(values: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0.0:
        return values.copy()
    radius = max(1, int(math.ceil(sigma * 3.0)))
    coordinates = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-(coordinates * coordinates) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()

    def convolve_same(line: np.ndarray) -> np.ndarray:
        padded = np.pad(line, (radius, radius), mode="edge")
        return np.convolve(padded, kernel, mode="valid")

    horizontal = np.apply_along_axis(convolve_same, 1, values)
    return np.apply_along_axis(convolve_same, 0, horizontal).astype(np.float32)


def _capture_height_field(
    source: bpy.types.Object,
    right: Vector,
    up: Vector,
    ray_direction: Vector,
    resolution_x: int,
    resolution_y: int,
    fit_resolution_to_aspect: bool,
    margin: float,
    blur_radius: float,
    depth_gamma: float,
    minimum_height: float,
) -> Dict[str, Any]:
    vertices, polygons = _evaluated_world_geometry(source)
    bvh = BVHTree.FromPolygons(vertices, polygons, all_triangles=False)
    if bvh is None:
        raise RuntimeError("Could not create a BVH from the source mesh")

    projected_u = np.asarray([vertex.dot(right) for vertex in vertices])
    projected_v = np.asarray([vertex.dot(up) for vertex in vertices])
    projected_d = np.asarray([vertex.dot(ray_direction) for vertex in vertices])

    u_min, u_max = float(projected_u.min()), float(projected_u.max())
    v_min, v_max = float(projected_v.min()), float(projected_v.max())
    d_min, d_max = float(projected_d.min()), float(projected_d.max())
    width = u_max - u_min
    height = v_max - v_min

    if fit_resolution_to_aspect:
        longest_axis_resolution = max(resolution_x, resolution_y)
        if width >= height:
            resolution_x = longest_axis_resolution
            resolution_y = max(
                8, int(round(longest_axis_resolution * height / width))
            )
        else:
            resolution_y = longest_axis_resolution
            resolution_x = max(
                8, int(round(longest_axis_resolution * width / height))
            )
    depth_span = d_max - d_min
    if width <= 1.0e-8 or height <= 1.0e-8:
        raise ValueError("The source has no usable area in the selected projection")

    u_padding = width * margin
    v_padding = height * margin
    u_min -= u_padding
    u_max += u_padding
    v_min -= v_padding
    v_max += v_padding
    width = u_max - u_min
    height = v_max - v_min

    ray_padding = max(depth_span * 0.05, max(width, height) * 0.001, 1.0e-4)
    ray_start_d = d_min - ray_padding
    ray_distance = depth_span + ray_padding * 2.0
    u_values = np.linspace(u_min, u_max, resolution_x, dtype=np.float64)
    v_values = np.linspace(v_min, v_max, resolution_y, dtype=np.float64)
    hit_depth = np.zeros((resolution_y, resolution_x), dtype=np.float32)
    mask = np.zeros_like(hit_depth)

    ray_direction = ray_direction.normalized()
    for y_index, v_coord in enumerate(v_values):
        row_origin = up * float(v_coord) + ray_direction * ray_start_d
        for x_index, u_coord in enumerate(u_values):
            origin = row_origin + right * float(u_coord)
            location, _normal, _face_index, _distance = bvh.ray_cast(
                origin, ray_direction, ray_distance
            )
            if location is not None:
                hit_depth[y_index, x_index] = location.dot(ray_direction)
                mask[y_index, x_index] = 1.0

    hit_count = int(mask.sum())
    if hit_count == 0:
        raise RuntimeError(
            "No ray hit the source mesh; try another projection or a higher resolution"
        )

    values = hit_depth[mask > 0.5]
    front_depth = float(values.min())
    back_depth = float(values.max())
    visible_span = back_depth - front_depth
    raw_height = np.zeros_like(hit_depth)
    if visible_span <= 1.0e-8:
        raw_height[mask > 0.5] = 1.0
    else:
        normalized_depth = (hit_depth[mask > 0.5] - front_depth) / visible_span
        raw_height[mask > 0.5] = 1.0 - normalized_depth

    raw_height[mask > 0.5] = minimum_height + (
        (1.0 - minimum_height)
        * np.power(raw_height[mask > 0.5], depth_gamma)
    )
    blurred_height = np.clip(_gaussian_blur(raw_height, blur_radius), 0.0, 1.0)
    blurred_mask = np.clip(_gaussian_blur(mask, blur_radius), 0.0, 1.0)

    return {
        "raw_height": raw_height,
        "height": blurred_height,
        "mask": mask,
        "blurred_mask": blurred_mask,
        "u_min": u_min,
        "u_max": u_max,
        "v_min": v_min,
        "v_max": v_max,
        "center_d": (d_min + d_max) * 0.5,
        "hit_count": hit_count,
        "resolution_x": resolution_x,
        "resolution_y": resolution_y,
    }

def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "relief"


def _store_image(
    name: str,
    values: np.ndarray,
    alpha: np.ndarray,
    output_directory: Optional[str],
) -> Tuple[bpy.types.Image, Optional[str]]:
    old_image = bpy.data.images.get(name)
    if old_image is not None:
        bpy.data.images.remove(old_image)

    height, width = values.shape
    image = bpy.data.images.new(
        name=name,
        width=width,
        height=height,
        alpha=True,
        float_buffer=True,
    )
    rgba = np.empty((height, width, 4), dtype=np.float32)
    rgba[:, :, 0] = values
    rgba[:, :, 1] = values
    rgba[:, :, 2] = values
    rgba[:, :, 3] = alpha
    image.pixels.foreach_set(rgba.ravel())
    image.colorspace_settings.name = "Non-Color"
    image.use_fake_user = True
    image.update()

    saved_path: Optional[str] = None
    if output_directory:
        if output_directory.startswith("//") and not bpy.data.filepath:
            relative = output_directory[2:].replace("/", os.sep).replace("\\", os.sep)
            directory = os.path.join(tempfile.gettempdir(), relative)
        else:
            directory = os.path.abspath(bpy.path.abspath(output_directory))
        os.makedirs(directory, exist_ok=True)
        saved_path = os.path.join(directory, _safe_name(name) + ".png")
        image.filepath_raw = saved_path
        image.file_format = "PNG"
        image.save()
    return image, saved_path


def _build_rectangular_geometry(
    heights: np.ndarray,
    u_values: np.ndarray,
    v_values: np.ndarray,
    right: Vector,
    up: Vector,
    normal: Vector,
    base_thickness: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]], list[int], int]:
    resolution_y, resolution_x = heights.shape
    mesh_vertices: list[tuple[float, float, float]] = []
    for y_index, v_coord in enumerate(v_values):
        row = up * float(v_coord)
        for x_index, u_coord in enumerate(u_values):
            point = (
                row
                + right * float(u_coord)
                + normal * float(heights[y_index, x_index])
            )
            mesh_vertices.append(tuple(point))

    top_vertex_count = len(mesh_vertices)
    bottom_start = top_vertex_count
    bottom_corners = (
        right * float(u_values[0]) + up * float(v_values[0]) - normal * base_thickness,
        right * float(u_values[-1]) + up * float(v_values[0]) - normal * base_thickness,
        right * float(u_values[-1]) + up * float(v_values[-1]) - normal * base_thickness,
        right * float(u_values[0]) + up * float(v_values[-1]) - normal * base_thickness,
    )
    mesh_vertices.extend(tuple(point) for point in bottom_corners)

    faces: list[tuple[int, ...]] = []
    for y_index in range(resolution_y - 1):
        for x_index in range(resolution_x - 1):
            lower_left = y_index * resolution_x + x_index
            lower_right = lower_left + 1
            upper_left = lower_left + resolution_x
            upper_right = upper_left + 1
            faces.append((lower_left, lower_right, upper_right, upper_left))
    top_face_count = len(faces)

    bottom_left, bottom_right, top_right, top_left = range(
        bottom_start, bottom_start + 4
    )
    faces.append((bottom_left, top_left, top_right, bottom_right))
    faces.append(
        (bottom_left, bottom_right)
        + tuple(range(resolution_x - 1, -1, -1))
    )
    right_edge = tuple(
        y_index * resolution_x + resolution_x - 1
        for y_index in range(resolution_y - 1, -1, -1)
    )
    faces.append((bottom_right, top_right) + right_edge)
    top_edge = tuple(
        (resolution_y - 1) * resolution_x + x_index
        for x_index in range(resolution_x)
    )
    faces.append((top_right, top_left) + top_edge)
    left_edge = tuple(y_index * resolution_x for y_index in range(resolution_y))
    faces.append((top_left, bottom_left) + left_edge)
    return mesh_vertices, faces, list(range(top_vertex_count)), top_face_count


def _build_silhouette_geometry(
    heights: np.ndarray,
    mask: np.ndarray,
    u_values: np.ndarray,
    v_values: np.ndarray,
    right: Vector,
    up: Vector,
    normal: Vector,
    base_thickness: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]], list[int], int]:
    """Build a closed solid from grid cells touching the projected source mask."""
    resolution_y, resolution_x = heights.shape
    occupied_samples = mask > 0.5
    active_cells = (
        occupied_samples[:-1, :-1]
        | occupied_samples[:-1, 1:]
        | occupied_samples[1:, :-1]
        | occupied_samples[1:, 1:]
    )
    if not bool(active_cells.any()):
        raise RuntimeError("The projected silhouette is too small for this resolution")

    used_samples = np.zeros((resolution_y, resolution_x), dtype=bool)
    used_samples[:-1, :-1] |= active_cells
    used_samples[:-1, 1:] |= active_cells
    used_samples[1:, :-1] |= active_cells
    used_samples[1:, 1:] |= active_cells

    top_indices = np.full((resolution_y, resolution_x), -1, dtype=np.int64)
    bottom_indices = np.full((resolution_y, resolution_x), -1, dtype=np.int64)
    mesh_vertices: list[tuple[float, float, float]] = []

    used_coordinates = np.argwhere(used_samples)
    for y_index_value, x_index_value in used_coordinates:
        y_index = int(y_index_value)
        x_index = int(x_index_value)
        point = (
            up * float(v_values[y_index])
            + right * float(u_values[x_index])
            + normal * float(heights[y_index, x_index])
        )
        top_indices[y_index, x_index] = len(mesh_vertices)
        mesh_vertices.append(tuple(point))

    top_vertex_indices = list(range(len(mesh_vertices)))
    for y_index_value, x_index_value in used_coordinates:
        y_index = int(y_index_value)
        x_index = int(x_index_value)
        point = (
            up * float(v_values[y_index])
            + right * float(u_values[x_index])
            - normal * base_thickness
        )
        bottom_indices[y_index, x_index] = len(mesh_vertices)
        mesh_vertices.append(tuple(point))

    faces: list[tuple[int, ...]] = []
    active_coordinates = np.argwhere(active_cells)
    for y_index_value, x_index_value in active_coordinates:
        y_index = int(y_index_value)
        x_index = int(x_index_value)
        lower_left = int(top_indices[y_index, x_index])
        lower_right = int(top_indices[y_index, x_index + 1])
        upper_left = int(top_indices[y_index + 1, x_index])
        upper_right = int(top_indices[y_index + 1, x_index + 1])
        faces.append((lower_left, lower_right, upper_right, upper_left))
    top_face_count = len(faces)

    for y_index_value, x_index_value in active_coordinates:
        y_index = int(y_index_value)
        x_index = int(x_index_value)
        lower_left = int(bottom_indices[y_index, x_index])
        lower_right = int(bottom_indices[y_index, x_index + 1])
        upper_left = int(bottom_indices[y_index + 1, x_index])
        upper_right = int(bottom_indices[y_index + 1, x_index + 1])
        faces.append((lower_left, upper_left, upper_right, lower_right))

    cell_height, cell_width = active_cells.shape
    for y_index_value, x_index_value in active_coordinates:
        y_index = int(y_index_value)
        x_index = int(x_index_value)
        top_lower_left = int(top_indices[y_index, x_index])
        top_lower_right = int(top_indices[y_index, x_index + 1])
        top_upper_left = int(top_indices[y_index + 1, x_index])
        top_upper_right = int(top_indices[y_index + 1, x_index + 1])
        bottom_lower_left = int(bottom_indices[y_index, x_index])
        bottom_lower_right = int(bottom_indices[y_index, x_index + 1])
        bottom_upper_left = int(bottom_indices[y_index + 1, x_index])
        bottom_upper_right = int(bottom_indices[y_index + 1, x_index + 1])

        if y_index == 0 or not active_cells[y_index - 1, x_index]:
            faces.append(
                (
                    top_lower_right,
                    top_lower_left,
                    bottom_lower_left,
                    bottom_lower_right,
                )
            )
        if x_index == cell_width - 1 or not active_cells[y_index, x_index + 1]:
            faces.append(
                (
                    top_upper_right,
                    top_lower_right,
                    bottom_lower_right,
                    bottom_upper_right,
                )
            )
        if y_index == cell_height - 1 or not active_cells[y_index + 1, x_index]:
            faces.append(
                (
                    top_upper_left,
                    top_upper_right,
                    bottom_upper_right,
                    bottom_upper_left,
                )
            )
        if x_index == 0 or not active_cells[y_index, x_index - 1]:
            faces.append(
                (
                    top_lower_left,
                    top_upper_left,
                    bottom_upper_left,
                    bottom_lower_left,
                )
            )

    return mesh_vertices, faces, top_vertex_indices, top_face_count


def _build_relief_mesh(
    source: bpy.types.Object,
    name: str,
    field: Dict[str, Any],
    right: Vector,
    up: Vector,
    ray_direction: Vector,
    relief_height: float,
    base_thickness: float,
    base_shape: str,
    corrective_smooth_factor: float,
    corrective_smooth_iterations: int,
) -> bpy.types.Object:
    heights: np.ndarray = field["height"] * relief_height
    resolution_y, resolution_x = heights.shape
    normal = -ray_direction.normalized()
    center_u = (field["u_min"] + field["u_max"]) * 0.5
    center_v = (field["v_min"] + field["v_max"]) * 0.5
    center = (
        right * center_u
        + up * center_v
        + ray_direction * float(field["center_d"])
    )
    u_values = np.linspace(
        field["u_min"] - center_u,
        field["u_max"] - center_u,
        resolution_x,
    )
    v_values = np.linspace(
        field["v_min"] - center_v,
        field["v_max"] - center_v,
        resolution_y,
    )

    if base_shape == "SILHOUETTE":
        mesh_vertices, faces, top_vertex_indices, top_face_count = (
            _build_silhouette_geometry(
                heights=heights,
                mask=field["mask"],
                u_values=u_values,
                v_values=v_values,
                right=right,
                up=up,
                normal=normal,
                base_thickness=base_thickness,
            )
        )
    else:
        mesh_vertices, faces, top_vertex_indices, top_face_count = (
            _build_rectangular_geometry(
                heights=heights,
                u_values=u_values,
                v_values=v_values,
                right=right,
                up=up,
                normal=normal,
                base_thickness=base_thickness,
            )
        )

    mesh = bpy.data.meshes.new(name + "Mesh")
    mesh.from_pydata(mesh_vertices, [], faces)
    mesh.update(calc_edges=True)
    relief = bpy.data.objects.new(name, mesh)
    relief.location = center

    output_collection = bpy.data.collections.get("Relief Output")
    if output_collection is None:
        output_collection = bpy.data.collections.new("Relief Output")
        bpy.context.scene.collection.children.link(output_collection)
    output_collection.objects.link(relief)

    for polygon_index in range(top_face_count):
        mesh.polygons[polygon_index].use_smooth = True

    surface_group = relief.vertex_groups.new(name="ReliefSurface")
    surface_group.add(top_vertex_indices, 1.0, "REPLACE")
    modifier = relief.modifiers.new(
        name="Relief Corrective Smooth", type="CORRECTIVE_SMOOTH"
    )
    modifier.vertex_group = surface_group.name
    modifier.factor = corrective_smooth_factor
    modifier.iterations = corrective_smooth_iterations
    modifier.smooth_type = "LENGTH_WEIGHTED"
    modifier.use_pin_boundary = True
    # A height field does not have a preceding deformation to correct. This mode
    # makes the requested modifier contribute an actual, gentle surface pass.
    modifier.use_only_smooth = True

    relief["relief_source"] = source.name
    relief["relief_projection_is_height_field"] = True
    relief["relief_undercut_free_direction"] = tuple(normal)
    relief["relief_base_shape"] = base_shape
    return relief


def generate_relief(
    source_object: Optional[str] = None,
    output_name: Optional[str] = None,
    projection: str = "Z",
    resolution_x: int = 512,
    resolution_y: int = 512,
    fit_resolution_to_aspect: bool = False,
    relief_height: float = 0.25,
    base_thickness: float = 0.1,
    base_shape: str = "SILHOUETTE",
    margin: float = 0.05,
    blur_radius: float = 1.25,
    depth_gamma: float = 1.0,
    minimum_height: float = 0.03,
    corrective_smooth_factor: float = 0.15,
    corrective_smooth_iterations: int = 2,
    save_images: bool = True,
    output_directory: Optional[str] = "//relief_output",
) -> Dict[str, Any]:
    """Create an undercut-free relief from the front-most orthographic depth image."""
    resolution_x = int(max(8, min(1024, resolution_x)))
    resolution_y = int(max(8, min(1024, resolution_y)))
    relief_height = float(max(1.0e-5, relief_height))
    base_thickness = float(max(1.0e-5, base_thickness))
    base_shape = base_shape.upper()
    if base_shape not in BASE_SHAPES:
        raise ValueError("base_shape must be SILHOUETTE or RECTANGLE")
    margin = float(max(0.0, min(1.0, margin)))
    blur_radius = float(max(0.0, min(64.0, blur_radius)))
    depth_gamma = float(max(0.05, min(10.0, depth_gamma)))
    minimum_height = float(max(0.0, min(1.0, minimum_height)))
    corrective_smooth_factor = float(
        max(-10.0, min(10.0, corrective_smooth_factor))
    )
    corrective_smooth_iterations = int(
        max(0, min(200, corrective_smooth_iterations))
    )

    source = bpy.data.objects.get(source_object) if source_object else bpy.context.active_object
    if source is None:
        raise ValueError("No source object was specified and there is no active object")
    if source.type != "MESH":
        raise TypeError(f"Source object {source.name!r} is not a mesh")

    projection = projection.upper()
    right, up, ray_direction = _projection_basis(projection, bpy.context.scene.camera)
    field = _capture_height_field(
        source=source,
        right=right,
        up=up,
        ray_direction=ray_direction,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
        fit_resolution_to_aspect=fit_resolution_to_aspect,
        margin=margin,
        blur_radius=blur_radius,
        depth_gamma=depth_gamma,
        minimum_height=minimum_height,
    )

    base_name = output_name or source.name + "_Relief"
    image_directory = output_directory if save_images else None
    raw_image, raw_path = _store_image(
        base_name + "_Depth",
        field["raw_height"],
        field["mask"],
        image_directory,
    )
    blurred_image, blurred_path = _store_image(
        base_name + "_Blurred",
        field["height"],
        field["blurred_mask"],
        image_directory,
    )
    relief = _build_relief_mesh(
        source=source,
        name=base_name,
        field=field,
        right=right,
        up=up,
        ray_direction=ray_direction,
        relief_height=relief_height,
        base_thickness=base_thickness,
        base_shape=base_shape,
        corrective_smooth_factor=corrective_smooth_factor,
        corrective_smooth_iterations=corrective_smooth_iterations,
    )

    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    relief.select_set(True)
    bpy.context.view_layer.objects.active = relief

    return {
        "object_name": relief.name,
        "source_object": source.name,
        "projection": projection,
        "base_shape": base_shape,
        "resolution": [field["resolution_x"], field["resolution_y"]],
        "hit_pixels": field["hit_count"],
        "vertex_count": len(relief.data.vertices),
        "face_count": len(relief.data.polygons),
        "depth_image": raw_image.name,
        "blurred_image": blurred_image.name,
        "depth_image_path": raw_path,
        "blurred_image_path": blurred_path,
        "corrective_smooth_modifier": "Relief Corrective Smooth",
        "undercut_free_along_projection": True,
    }


def remove_relief_preview() -> None:
    """Remove the transient live-preview object and its orphaned mesh."""
    preview = bpy.data.objects.get(PREVIEW_OBJECT_NAME)
    if preview is None:
        return
    mesh = preview.data if preview.type == "MESH" else None
    bpy.data.objects.remove(preview, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def refresh_relief_preview(
    source_object: str,
    projection: str = "Z",
    preview_resolution: int = 128,
    final_resolution: int = 512,
    fit_resolution_to_aspect: bool = True,
    relief_height: float = 0.25,
    base_thickness: float = 0.1,
    base_shape: str = "SILHOUETTE",
    margin: float = 0.05,
    blur_radius: float = 1.25,
    depth_gamma: float = 1.0,
    minimum_height: float = 0.03,
    corrective_smooth_factor: float = 0.15,
    corrective_smooth_iterations: int = 2,
) -> Dict[str, Any]:
    """Rebuild a disposable low-resolution relief for interactive tuning."""
    source = bpy.data.objects.get(source_object)
    if source is None or source.type != "MESH":
        raise ValueError("The live-preview source mesh is no longer available")

    preview_resolution = int(max(32, min(256, preview_resolution)))
    final_resolution = int(max(8, min(1024, final_resolution)))
    base_shape = base_shape.upper()
    if base_shape not in BASE_SHAPES:
        raise ValueError("base_shape must be SILHOUETTE or RECTANGLE")

    projection = projection.upper()
    right, up, ray_direction = _projection_basis(projection, bpy.context.scene.camera)
    # Gaussian blur is specified in final-image pixels. Scale its radius so
    # the lower-resolution preview has the same approximate world-space blur.
    preview_blur = float(blur_radius) * preview_resolution / final_resolution
    field = _capture_height_field(
        source=source,
        right=right,
        up=up,
        ray_direction=ray_direction,
        resolution_x=preview_resolution,
        resolution_y=preview_resolution,
        fit_resolution_to_aspect=fit_resolution_to_aspect,
        margin=float(max(0.0, min(1.0, margin))),
        blur_radius=float(max(0.0, min(64.0, preview_blur))),
        depth_gamma=float(max(0.05, min(10.0, depth_gamma))),
        minimum_height=float(max(0.0, min(1.0, minimum_height))),
    )

    remove_relief_preview()
    preview = _build_relief_mesh(
        source=source,
        name=PREVIEW_OBJECT_NAME,
        field=field,
        right=right,
        up=up,
        ray_direction=ray_direction,
        relief_height=float(max(1.0e-5, relief_height)),
        base_thickness=float(max(1.0e-5, base_thickness)),
        base_shape=base_shape,
        corrective_smooth_factor=float(
            max(-10.0, min(10.0, corrective_smooth_factor))
        ),
        corrective_smooth_iterations=int(
            max(0, min(200, corrective_smooth_iterations))
        ),
    )
    preview["relief_live_preview"] = True
    preview["relief_preview_source"] = source.name
    preview.hide_render = True
    preview.show_in_front = True
    preview.color = (0.18, 0.55, 1.0, 0.72)

    return {
        "object_name": preview.name,
        "source_object": source.name,
        "resolution": [field["resolution_x"], field["resolution_y"]],
        "vertex_count": len(preview.data.vertices),
        "face_count": len(preview.data.polygons),
        "preview_blur_radius": preview_blur,
    }


def quad_remesh_for_cad(
    source_object: Optional[str] = None,
    output_name: Optional[str] = None,
    target_faces: int = 20000,
    preserve_sharp: bool = True,
    preserve_boundary: bool = False,
    use_mesh_symmetry: bool = False,
    apply_modifiers: bool = True,
    seed: int = 0,
) -> Dict[str, Any]:
    """Create a lower-density all-quad copy suitable for Rhino SubD conversion.

    Boundary edges are valid output. In particular, QuadriFlow can split retained
    sharp edges into unwelded boundary pairs which Rhino can import as SubD
    creases. Only wire/branching edges and non-quad faces fail validation.
    """
    source = bpy.data.objects.get(source_object) if source_object else bpy.context.active_object
    if source is None:
        raise ValueError("No source object was specified and there is no active object")
    if source.type != "MESH":
        raise TypeError(f"Source object {source.name!r} is not a mesh")

    target_faces = int(max(4, min(2_000_000, target_faces)))
    seed = int(max(0, min(2_147_483_647, seed)))
    depsgraph = bpy.context.evaluated_depsgraph_get()

    if apply_modifiers:
        evaluated = source.evaluated_get(depsgraph)
        output_mesh = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=False,
            depsgraph=depsgraph,
        )
    else:
        output_mesh = source.data.copy()

    base_name = output_name or source.name + "_CAD_Quad"
    output = bpy.data.objects.new(base_name, output_mesh)
    output.matrix_world = source.matrix_world.copy()
    output_collection = (
        source.users_collection[0]
        if source.users_collection
        else bpy.context.scene.collection
    )
    output_collection.objects.link(output)

    reference_mesh = output_mesh.copy()
    output_mesh_name = output_mesh.name
    reference_mesh_name = reference_mesh.name
    reference_vertices = [vertex.co.copy() for vertex in reference_mesh.vertices]
    reference_polygons = [tuple(polygon.vertices) for polygon in reference_mesh.polygons]
    reference_bvh = BVHTree.FromPolygons(
        reference_vertices,
        reference_polygons,
        all_triangles=False,
    )
    source_face_count = len(reference_mesh.polygons)

    def run_quadriflow(keep_sharp: bool) -> None:
        status = bpy.ops.object.quadriflow_remesh(
            use_mesh_symmetry=bool(use_mesh_symmetry),
            use_preserve_sharp=keep_sharp,
            use_preserve_boundary=bool(preserve_boundary),
            preserve_attributes=False,
            smooth_normals=True,
            mode="FACES",
            target_faces=target_faces,
            seed=seed,
        )
        if "FINISHED" not in status:
            raise RuntimeError(f"QuadriFlow did not finish: {sorted(status)}")

    def inspect_output() -> tuple[bool, bool, bool, int, int, int, float, float, float]:
        all_quads = all(len(polygon.vertices) == 4 for polygon in output.data.polygons)
        check_mesh = bmesh.new()
        try:
            check_mesh.from_mesh(output.data)
            boundary_edge_count = sum(
                1 for edge in check_mesh.edges if len(edge.link_faces) == 1
            )
            invalid_edge_count = sum(
                1 for edge in check_mesh.edges if len(edge.link_faces) not in {1, 2}
            )
            isolated_vertex_count = sum(
                1 for vertex in check_mesh.verts if not vertex.link_edges
            )
            closed_manifold = (
                bool(check_mesh.faces)
                and boundary_edge_count == 0
                and invalid_edge_count == 0
                and isolated_vertex_count == 0
            )
            subd_safe = (
                bool(check_mesh.faces)
                and all_quads
                and invalid_edge_count == 0
                and isolated_vertex_count == 0
            )
            signed_volume = float(check_mesh.calc_volume(signed=True))
        finally:
            check_mesh.free()

        distances: list[float] = []
        if reference_bvh is not None:
            for vertex in output.data.vertices:
                nearest = reference_bvh.find_nearest(vertex.co)
                if nearest is not None:
                    distances.append(float(nearest[3]))
        mean_deviation = float(sum(distances) / len(distances)) if distances else 0.0
        max_deviation = float(max(distances)) if distances else 0.0
        return (
            all_quads,
            subd_safe,
            closed_manifold,
            boundary_edge_count,
            invalid_edge_count,
            isolated_vertex_count,
            signed_volume,
            mean_deviation,
            max_deviation,
        )

    try:
        if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for selected in list(bpy.context.selected_objects):
            selected.select_set(False)
        output.select_set(True)
        bpy.context.view_layer.objects.active = output

        run_quadriflow(bool(preserve_sharp))
        (
            all_quads,
            subd_safe,
            closed_manifold,
            boundary_edge_count,
            invalid_edge_count,
            isolated_vertex_count,
            signed_volume,
            mean_deviation,
            max_deviation,
        ) = inspect_output()

        if not subd_safe:
            raise RuntimeError(
                "QuadriFlow did not produce a SubD-safe all-quad mesh "
                f"({invalid_edge_count} invalid edges, "
                f"{isolated_vertex_count} isolated vertices); "
                "try a different target face count"
            )

        output_bvh = BVHTree.FromPolygons(
            [vertex.co.copy() for vertex in output.data.vertices],
            [tuple(polygon.vertices) for polygon in output.data.polygons],
            all_triangles=False,
        )
        coverage_distances: list[float] = []
        if output_bvh is not None:
            sample_step = max(1, len(reference_vertices) // 50_000)
            for vertex in reference_vertices[::sample_step]:
                nearest = output_bvh.find_nearest(vertex)
                if nearest is not None:
                    coverage_distances.append(float(nearest[3]))
        coverage_distances.sort()
        coverage_mean = (
            float(sum(coverage_distances) / len(coverage_distances))
            if coverage_distances
            else 0.0
        )
        coverage_p95 = (
            float(coverage_distances[int(0.95 * (len(coverage_distances) - 1))])
            if coverage_distances
            else 0.0
        )
        coverage_max = (
            float(max(coverage_distances)) if coverage_distances else 0.0
        )

        output["cad_quad_source"] = source.name
        output["cad_quad_backend"] = "QUADRIFLOW_NATIVE"
        output["cad_quad_target_faces"] = target_faces
        output["cad_quad_all_quads"] = all_quads
        output["cad_quad_subd_safe"] = subd_safe
        output["cad_quad_closed_manifold"] = closed_manifold
        output["cad_quad_manifold"] = closed_manifold
        output["cad_quad_boundary_edges"] = boundary_edge_count
        output["cad_quad_invalid_edges"] = invalid_edge_count
        output["cad_quad_isolated_vertices"] = isolated_vertex_count
        output["cad_quad_preserved_sharp"] = bool(preserve_sharp)
        output["cad_quad_mean_deviation"] = mean_deviation
        output["cad_quad_max_deviation"] = max_deviation
        output["cad_quad_coverage_mean"] = coverage_mean
        output["cad_quad_coverage_p95"] = coverage_p95
        output["cad_quad_coverage_max"] = coverage_max

        if reference_mesh.users == 0:
            bpy.data.meshes.remove(reference_mesh)

        return {
            "object_name": output.name,
            "source_object": source.name,
            "source_face_count": source_face_count,
            "target_face_count": target_faces,
            "face_count": len(output.data.polygons),
            "vertex_count": len(output.data.vertices),
            "all_quads": all_quads,
            "subd_safe": subd_safe,
            "closed_manifold": closed_manifold,
            "manifold": closed_manifold,
            "boundary_edge_count": boundary_edge_count,
            "invalid_edge_count": invalid_edge_count,
            "isolated_vertex_count": isolated_vertex_count,
            "signed_volume": signed_volume,
            "mean_deviation": mean_deviation,
            "max_deviation": max_deviation,
            "coverage_mean": coverage_mean,
            "coverage_p95": coverage_p95,
            "coverage_max": coverage_max,
            "modifiers_applied": bool(apply_modifiers),
            "preserved_sharp": bool(preserve_sharp),
        }
    except Exception:
        bpy.data.objects.remove(output, do_unlink=True)
        for mesh_name in (output_mesh_name, reference_mesh_name):
            mesh = bpy.data.meshes.get(mesh_name)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for selected in list(bpy.context.selected_objects):
            selected.select_set(False)
        source.select_set(True)
        bpy.context.view_layer.objects.active = source
        raise


def finalize_adaptive_quad_for_cad(
    source_object: str,
    output_object: str,
    target_faces: int,
    preserve_sharp: bool = True,
    sharp_angle: float = 35.0,
) -> Dict[str, Any]:
    """Validate and annotate a ReQuad result, optionally unwelding creases."""
    source = bpy.data.objects.get(source_object)
    output = bpy.data.objects.get(output_object)
    if source is None or source.type != "MESH":
        raise ValueError("The adaptive-remesh source mesh is no longer available")
    if output is None or output.type != "MESH":
        raise ValueError("The adaptive-remesh output mesh is no longer available")

    split_edge_count = 0
    if preserve_sharp:
        threshold = math.radians(float(max(0.0, min(180.0, sharp_angle))))
        split_mesh = bmesh.new()
        try:
            split_mesh.from_mesh(output.data)
            relief_normal = source.get("relief_undercut_free_direction")
            if relief_normal is not None and len(relief_normal) == 3:
                world_normal = Vector(relief_normal).normalized()
                normal_matrix = output.matrix_world.to_3x3().inverted().transposed()

                def face_region(face):
                    transformed = (normal_matrix @ face.normal).normalized()
                    alignment = transformed.dot(world_normal)
                    if alignment > 0.25:
                        return "FRONT"
                    if alignment < -0.25:
                        return "BACK"
                    return "WALL"

                feature_edges = [
                    edge
                    for edge in split_mesh.edges
                    if len(edge.link_faces) == 2
                    and face_region(edge.link_faces[0])
                    != face_region(edge.link_faces[1])
                    and edge.calc_face_angle(0.0) >= threshold
                ]
            else:
                feature_edges = [
                    edge
                    for edge in split_mesh.edges
                    if len(edge.link_faces) == 2
                    and edge.calc_face_angle(0.0) >= threshold
                ]
            split_edge_count = len(feature_edges)
            if feature_edges:
                bmesh.ops.split_edges(split_mesh, edges=feature_edges)
                split_mesh.to_mesh(output.data)
                output.data.update(calc_edges=True)
        finally:
            split_mesh.free()

    reference_vertices, reference_polygons = _evaluated_world_geometry(source)
    reference_bvh = BVHTree.FromPolygons(
        reference_vertices,
        reference_polygons,
        all_triangles=False,
    )

    check_mesh = bmesh.new()
    try:
        check_mesh.from_mesh(output.data)
        non_quad_face_count = sum(
            1 for face in check_mesh.faces if len(face.verts) != 4
        )
        boundary_edge_count = sum(
            1 for edge in check_mesh.edges if len(edge.link_faces) == 1
        )
        invalid_edge_count = sum(
            1 for edge in check_mesh.edges if len(edge.link_faces) not in {1, 2}
        )
        isolated_vertex_count = sum(
            1 for vertex in check_mesh.verts if not vertex.link_edges
        )
    finally:
        check_mesh.free()

    distances: list[float] = []
    if reference_bvh is not None:
        matrix = output.matrix_world
        for vertex in output.data.vertices:
            nearest = reference_bvh.find_nearest(matrix @ vertex.co)
            if nearest is not None:
                distances.append(float(nearest[3]))
    mean_deviation = float(sum(distances) / len(distances)) if distances else 0.0
    max_deviation = float(max(distances)) if distances else 0.0

    output_world_vertices = [
        output.matrix_world @ vertex.co for vertex in output.data.vertices
    ]
    output_polygons = [tuple(polygon.vertices) for polygon in output.data.polygons]
    output_bvh = BVHTree.FromPolygons(
        output_world_vertices,
        output_polygons,
        all_triangles=False,
    )
    coverage_distances: list[float] = []
    if output_bvh is not None:
        sample_step = max(1, len(reference_vertices) // 50_000)
        for vertex in reference_vertices[::sample_step]:
            nearest = output_bvh.find_nearest(vertex)
            if nearest is not None:
                coverage_distances.append(float(nearest[3]))
    coverage_distances.sort()
    coverage_mean = (
        float(sum(coverage_distances) / len(coverage_distances))
        if coverage_distances
        else 0.0
    )
    coverage_p95 = (
        float(coverage_distances[int(0.95 * (len(coverage_distances) - 1))])
        if coverage_distances
        else 0.0
    )
    coverage_max = float(max(coverage_distances)) if coverage_distances else 0.0

    all_quads = bool(output.data.polygons) and non_quad_face_count == 0
    subd_safe = (
        all_quads
        and invalid_edge_count == 0
        and isolated_vertex_count == 0
    )
    closed_manifold = subd_safe and boundary_edge_count == 0

    output["cad_quad_source"] = source.name
    output["cad_quad_backend"] = "REQUAD_ADAPTIVE"
    output["cad_quad_target_faces"] = int(target_faces)
    output["cad_quad_all_quads"] = all_quads
    output["cad_quad_subd_safe"] = subd_safe
    output["cad_quad_closed_manifold"] = closed_manifold
    output["cad_quad_manifold"] = closed_manifold
    output["cad_quad_boundary_edges"] = boundary_edge_count
    output["cad_quad_invalid_edges"] = invalid_edge_count
    output["cad_quad_isolated_vertices"] = isolated_vertex_count
    output["cad_quad_non_quad_faces"] = non_quad_face_count
    output["cad_quad_feature_edges_split"] = split_edge_count
    output["cad_quad_preserved_sharp"] = bool(preserve_sharp)
    output["cad_quad_mean_deviation"] = mean_deviation
    output["cad_quad_max_deviation"] = max_deviation
    output["cad_quad_coverage_mean"] = coverage_mean
    output["cad_quad_coverage_p95"] = coverage_p95
    output["cad_quad_coverage_max"] = coverage_max

    return {
        "object_name": output.name,
        "source_object": source.name,
        "target_face_count": int(target_faces),
        "face_count": len(output.data.polygons),
        "vertex_count": len(output.data.vertices),
        "all_quads": all_quads,
        "subd_safe": subd_safe,
        "closed_manifold": closed_manifold,
        "boundary_edge_count": boundary_edge_count,
        "invalid_edge_count": invalid_edge_count,
        "isolated_vertex_count": isolated_vertex_count,
        "non_quad_face_count": non_quad_face_count,
        "split_edge_count": split_edge_count,
        "mean_deviation": mean_deviation,
        "max_deviation": max_deviation,
        "coverage_mean": coverage_mean,
        "coverage_p95": coverage_p95,
        "coverage_max": coverage_max,
        "preserved_sharp": bool(preserve_sharp),
        "backend": "REQUAD_ADAPTIVE",
    }
