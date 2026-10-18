"""Run the installed Blender MCP addon without opening a GUI.

Usage: Blender --background --python headless_mcp.py
The existing addon keeps its own permissions and safe-mode checks. Background
Blender has no UI event loop, so queued commands are drained on the main thread.
This script does not change preferences, install addons, or load user projects.
"""
import importlib
import socket
import threading
import time
import bpy

addon = importlib.import_module("blender_mcp")
if not hasattr(bpy.types.Scene, "blendermcp_port"):
    addon.register()
server = addon.BlenderMCPServer(port=9876)
server.host = "127.0.0.1"
# Addon start() assumes a UI timer. Initialize its existing local transport, then
# provide the missing main-thread pump below. Command validation stays unchanged.
server.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.socket.bind((server.host, server.port))
server.socket.listen(5)
server.running = True
server.server_thread = threading.Thread(target=server._server_loop, daemon=True)
server.server_thread.start()
print("UITA headless Blender MCP ready on localhost:9876", flush=True)
try:
    while server.running:
        server._drain_command_queue()
        time.sleep(.025)
finally:
    server.stop()
