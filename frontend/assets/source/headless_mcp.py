"""Run installed MCP-for-Blender handlers in an isolated background Blender.

Usage: Blender --background --factory-startup --python headless_mcp.py -- ADDON_PATH
The addon UI server depends on timers. This dedicated main-thread loop replaces
that transport scheduler; it does not open a window or read a user's .blend.
"""
import bpy
import importlib.util
import socket
import sys
import threading
import time

assert bpy.app.background, 'This runner must use --background'
addon_path = sys.argv[sys.argv.index('--') + 1]
spec = importlib.util.spec_from_file_location('uita_blender_mcp', addon_path)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
addon.register()
server = addon.BlenderMCPServer(host='127.0.0.1', port=9876)
server.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.socket.bind((server.host, server.port))
server.socket.listen(5)
server.running = True
server.server_thread = threading.Thread(target=server._server_loop, daemon=True)
server.server_thread.start()
print('UITA headless Blender MCP ready; background=', bpy.app.background, flush=True)
try:
    while server.running:
        server._drain_command_queue()
        time.sleep(0.05)
finally:
    server.stop()
