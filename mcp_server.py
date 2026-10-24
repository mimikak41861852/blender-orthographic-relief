"""STDIO MCP server that forwards relief tools to a running Blender add-on."""

from __future__ import annotations

import json
import os
import socket
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # Allows the v1 SDK as a compatibility fallback.
    from mcp.server.fastmcp import FastMCP as MCPServer


HOST = os.environ.get("BLENDER_RELIEF_HOST", "127.0.0.1")
PORT = int(os.environ.get("BLENDER_RELIEF_PORT", "9876"))

mcp = MCPServer(
    "Blender Relief",
    instructions=(
        "Use list_mesh_objects before generate_relief when the source name is unknown. "
        "Blender must be open with the Relief MCP add-on enabled. generate_relief creates "
        "a blurred orthographic height field, so the result has no undercuts along the "
        "selected projection direction. The generated object is selected in Blender."
    ),
)


def _blender_request(command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    request = {"command": command, "payload": payload or {}}
    encoded = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
    try:
        with socket.create_connection((HOST, PORT), timeout=5.0) as connection:
            connection.settimeout(305.0)
            connection.sendall(encoded)
            response = bytearray()
            while b"\n" not in response and len(response) < 16 * 1024 * 1024:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response.extend(chunk)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot connect to Blender at {HOST}:{PORT}. Open Blender and enable "
            f"the Relief MCP add-on, then retry. Original error: {exc}"
        ) from exc

    if not response:
        raise RuntimeError("Blender closed the bridge connection without a response")
    result = json.loads(bytes(response).split(b"\n", 1)[0].decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(
            f"Blender {result.get('error_type', 'error')}: {result.get('error', result)}"
        )
    return result


@mcp.tool()
def ping_blender() -> dict[str, Any]:
    """Check that Blender and the Relief MCP bridge are running."""
    return _blender_request("ping")


@mcp.tool()
def list_mesh_objects() -> dict[str, Any]:
    """List mesh objects in the open Blender file and identify the active object."""
    return _blender_request("list_mesh_objects")


@mcp.tool()
def generate_relief(
    source_object: str,
    output_name: str | None = None,
    projection: str = "Z",
    resolution: int = 512,
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
    save_images: bool = True,
    output_directory: str = "//relief_output",
) -> dict[str, Any]:
    """Create an undercut-free relief from a Blender mesh.

    projection is the viewing side: X, -X, Y, -Y, Z, -Z, or CAMERA. The source
    is sampled by orthographic rays, converted to a grayscale height image,
    Gaussian-blurred, and rebuilt as a closed solid relief. base_shape can be
    SILHOUETTE to follow the projected source outline or RECTANGLE for the original
    plaque. Dimensions are Blender units; blur_radius is in image pixels.
    """
    payload = {
        "source_object": source_object,
        "output_name": output_name,
        "projection": projection,
        "resolution_x": resolution,
        "resolution_y": resolution,
        "fit_resolution_to_aspect": fit_resolution_to_aspect,
        "relief_height": relief_height,
        "base_thickness": base_thickness,
        "base_shape": base_shape,
        "margin": margin,
        "blur_radius": blur_radius,
        "depth_gamma": depth_gamma,
        "minimum_height": minimum_height,
        "corrective_smooth_factor": corrective_smooth_factor,
        "corrective_smooth_iterations": corrective_smooth_iterations,
        "save_images": save_images,
        "output_directory": output_directory,
    }
    return _blender_request("generate_relief", payload)["result"]


if __name__ == "__main__":
    mcp.run(transport="stdio")
