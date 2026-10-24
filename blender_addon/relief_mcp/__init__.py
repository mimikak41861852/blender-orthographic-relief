"""Blender UI and localhost bridge for the Relief MCP server."""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
import traceback
from typing import Any, Dict, Optional

import bpy
from bpy.props import EnumProperty, FloatProperty, IntProperty, PointerProperty

from .core import generate_relief


bl_info = {
    "name": "Relief MCP",
    "author": "OpenAI Codex",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "3D View > Sidebar > Relief MCP",
    "description": "Create undercut-free orthographic reliefs and expose them over MCP",
    "category": "Object",
}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = int(os.environ.get("BLENDER_RELIEF_PORT", "9876"))
_COMMAND_QUEUE: queue.Queue = queue.Queue()
_SERVER: Optional["ReliefBridgeServer"] = None


def _dispatch(request: Dict[str, Any]) -> Dict[str, Any]:
    command = request.get("command")
    payload = request.get("payload") or {}
    if command == "ping":
        return {
            "ok": True,
            "blender_version": bpy.app.version_string,
            "blend_file": bpy.data.filepath or None,
        }
    if command == "list_mesh_objects":
        return {
            "ok": True,
            "active_object": bpy.context.active_object.name
            if bpy.context.active_object
            else None,
            "mesh_objects": [
                {
                    "name": obj.name,
                    "vertex_count": len(obj.data.vertices),
                    "face_count": len(obj.data.polygons),
                    "selected": obj.select_get(),
                }
                for obj in bpy.data.objects
                if obj.type == "MESH"
            ],
        }
    if command == "generate_relief":
        return {"ok": True, "result": generate_relief(**payload)}
    raise ValueError(f"Unknown bridge command: {command!r}")


def _process_commands() -> float:
    processed = 0
    while processed < 4:
        try:
            request, response_queue = _COMMAND_QUEUE.get_nowait()
        except queue.Empty:
            break
        try:
            response = _dispatch(request)
        except Exception as exc:  # Blender must send useful errors back to MCP.
            traceback.print_exc()
            response = {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        response_queue.put(response)
        processed += 1
    return 0.05


class ReliefBridgeServer:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._stop = threading.Event()
        self._listener: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve, name="ReliefMCPBridge", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _serve(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                self._listener = listener
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind((self.host, self.port))
                listener.listen(8)
                listener.settimeout(0.25)
                while not self._stop.is_set():
                    try:
                        connection, _address = listener.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    threading.Thread(
                        target=self._handle_connection,
                        args=(connection,),
                        daemon=True,
                    ).start()
        except OSError as exc:
            print(f"Relief MCP bridge could not listen on {self.host}:{self.port}: {exc}")
        finally:
            self._listener = None

    def _handle_connection(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(305.0)
            buffer = bytearray()
            while b"\n" not in buffer and len(buffer) < 4 * 1024 * 1024:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
            try:
                request = json.loads(bytes(buffer).split(b"\n", 1)[0].decode("utf-8"))
                response_queue: queue.Queue = queue.Queue(maxsize=1)
                _COMMAND_QUEUE.put((request, response_queue))
                response = response_queue.get(timeout=300.0)
            except Exception as exc:
                response = {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            encoded = json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n"
            try:
                connection.sendall(encoded)
            except OSError:
                pass


def start_server() -> None:
    global _SERVER
    if _SERVER is None:
        _SERVER = ReliefBridgeServer()
    _SERVER.start()


def stop_server() -> None:
    global _SERVER
    if _SERVER is not None:
        _SERVER.stop()
        _SERVER = None


class RELIEF_PG_Settings(bpy.types.PropertyGroup):
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
    resolution: IntProperty(name="Resolution", default=512, min=8, max=1024)
    relief_height: FloatProperty(name="Relief Height", default=0.25, min=0.00001)
    base_thickness: FloatProperty(name="Base Thickness", default=0.1, min=0.00001)
    base_shape: EnumProperty(
        name="Base Shape",
        items=[
            ("SILHOUETTE", "Source Silhouette", "Trim to the projected source outline"),
            ("RECTANGLE", "Rectangle", "Keep the original rectangular plaque"),
        ],
        default="SILHOUETTE",
    )
    margin: FloatProperty(name="Margin", default=0.05, min=0.0, max=1.0)
    blur_radius: FloatProperty(name="Blur (px)", default=1.25, min=0.0, max=64.0)
    smooth_factor: FloatProperty(name="Corrective Smooth", default=0.15, min=-10.0, max=10.0)
    smooth_iterations: IntProperty(name="Smooth Iterations", default=2, min=0, max=200)


class RELIEF_OT_Generate(bpy.types.Operator):
    bl_idname = "object.generate_orthographic_relief"
    bl_label = "Generate Relief"
    bl_description = "Create a blurred, undercut-free height-field relief from the active mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.relief_mcp_settings
        try:
            result = generate_relief(
                projection=settings.projection,
                resolution_x=settings.resolution,
                resolution_y=settings.resolution,
                relief_height=settings.relief_height,
                base_thickness=settings.base_thickness,
                base_shape=settings.base_shape,
                margin=settings.margin,
                blur_radius=settings.blur_radius,
                corrective_smooth_factor=settings.smooth_factor,
                corrective_smooth_iterations=settings.smooth_iterations,
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Created {result['object_name']}")
        return {"FINISHED"}


class RELIEF_OT_StartServer(bpy.types.Operator):
    bl_idname = "wm.relief_mcp_start_server"
    bl_label = "Start MCP Bridge"

    def execute(self, _context):
        start_server()
        return {"FINISHED"}


class RELIEF_OT_StopServer(bpy.types.Operator):
    bl_idname = "wm.relief_mcp_stop_server"
    bl_label = "Stop MCP Bridge"

    def execute(self, _context):
        stop_server()
        return {"FINISHED"}


class RELIEF_PT_Panel(bpy.types.Panel):
    bl_label = "Relief MCP"
    bl_idname = "RELIEF_PT_relief_mcp"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Relief MCP"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.relief_mcp_settings
        active = context.active_object
        layout.label(text=f"Source: {active.name if active else 'None'}")
        layout.prop(settings, "projection")
        layout.prop(settings, "resolution")
        layout.prop(settings, "base_shape")
        layout.prop(settings, "relief_height")
        layout.prop(settings, "base_thickness")
        layout.prop(settings, "margin")
        layout.prop(settings, "blur_radius")
        layout.separator()
        layout.prop(settings, "smooth_factor")
        layout.prop(settings, "smooth_iterations")
        layout.operator("object.generate_orthographic_relief", icon="MOD_DISPLACE")
        layout.separator()
        running = bool(_SERVER and _SERVER.running)
        layout.label(
            text=f"MCP bridge: {'running' if running else 'stopped'} ({DEFAULT_PORT})"
        )
        layout.operator(
            "wm.relief_mcp_stop_server" if running else "wm.relief_mcp_start_server",
            icon="PAUSE" if running else "PLAY",
        )


CLASSES = (
    RELIEF_PG_Settings,
    RELIEF_OT_Generate,
    RELIEF_OT_StartServer,
    RELIEF_OT_StopServer,
    RELIEF_PT_Panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.relief_mcp_settings = PointerProperty(type=RELIEF_PG_Settings)
    if not bpy.app.timers.is_registered(_process_commands):
        bpy.app.timers.register(_process_commands, first_interval=0.05, persistent=True)
    start_server()


def unregister():
    stop_server()
    if bpy.app.timers.is_registered(_process_commands):
        bpy.app.timers.unregister(_process_commands)
    del bpy.types.Scene.relief_mcp_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
