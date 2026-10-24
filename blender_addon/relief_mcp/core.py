"""Geometry and image generation for the Relief MCP Blender add-on."""

from __future__ import annotations

import math
import os
import re
import tempfile
from typing import Any, Dict, Optional, Tuple

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree


PROJECTION_AXES = {"X", "-X", "Y", "-Y", "Z", "-Z", "CAMERA"}


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


def _build_relief_mesh(
    source: bpy.types.Object,
    name: str,
    field: Dict[str, Any],
    right: Vector,
    up: Vector,
    ray_direction: Vector,
    relief_height: float,
    base_thickness: float,
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
    surface_group.add(list(range(top_vertex_count)), 1.0, "REPLACE")
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
