#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全功能基准测试靶场 v4
专为目录扫描器设计，精确控制每一条路径的响应。

场景覆盖：
  请求1: 30 个根目录已知路径（各种状态码）
  请求2: 20 个 /admin/ 子目录路径
  场景3: 15 个 /api/ 子路径（JSON + 认证）
  请求4: 10 个 /backup/ 路径（备份文件常见后缀）
  请求5: 8 个 /config/ 子目录（配置文件）
  响应5: 5 个 /static/ 资源文件（CSS/JS/图片）
  请求6: 3 个递归目标（进一步递归扫出子路径）
  探索7: 软404多模板（/admin/ + /api/ + / 各自不同的错误页）
  响应8: 隐藏文件（.htaccess, .env, .gitignore）
  请求9: 带扩展名的路径（.php, .html, .xml, .json）
  响应10: 不同响应体大小（10B ~ 100KB）

总计: 100+ 已知路径
"""

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import sys
import os
import random
import string
import time

# ─── 错误页模板（多目录上下文）────────────────────────────────

ROOT_404_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>404 Not Found</title></head>
<body>
  <div class="container">
    <h1>404 — Page Not Found</h1>
    <p>The page you are looking for does not exist.</p>
    <p><a href="/">Return to homepage</a></p>
    <footer>&copy; 2024 Example Corp. All rights reserved.</footer>
  </div>
</body>
</html>"""

ADMIN_404_HTML = """<!DOCTYPE html>
<html>
<head><title>Admin — 404</title></head>
<body>
  <h1>Admin Panel</h1>
  <div class="error">
    <h2>Page Not Found</h2>
    <p>The admin page you requested was not found.</p>
    <p>Request ID: 5a3f2e1b-8c4d-4e6f-9a1b-2c3d4e5f6a7b</p>
  </div>
  <p><a href="/admin/">Back to dashboard</a></p>
</body>
</html>"""

API_404_JSON = '{"error":"not_found","code":404,"message":"Endpoint does not exist","timestamp":"2024-06-15T12:00:00Z","request_id":"rq_7f3a2b1c"}'

BACKUP_404_HTML = """<html><body><h1>Backup Directory</h1><p>404: Backup file not found.</p></body></html>"""

CONFIG_404_HTML = """<html><body><h1>Configuration</h1><p>Config file not available.</p></body></html>"""

SOFT_404_MODE = False
MULTI_404_MODE = False


def random_content(size):
    """生成指定大小的随机文本"""
    return "".join(random.choices(string.ascii_letters + string.digits + "\n ", k=size))


# ─── 路由表（100+ 路径）───────────────────────────────────────

ROUTES = {}

# ─── 根目录常见路径 (32 个) ───
ROUTES["/"] =                     {"status": 200, "content": "<html><body><h1>Welcome</h1><p>Homepage of benchmark target.</p><nav><a href='/admin/'>Admin</a> <a href='/api/v1/'>API</a></nav></body></html>"}
ROUTES["/index.html"] =           {"status": 200, "content": "<html><body><h1>Index</h1><p>Welcome to the index page.</p></body></html>"}
ROUTES["/index.php"] =            {"status": 200, "content": "<html><body><h1>Index (PHP)</h1><p>PHP rendered homepage.</p></body></html>"}
ROUTES["/login"] =                {"status": 200, "content": '<html><body><h1>Login</h1><form method="post" action="/login"><input name="user" type="text" placeholder="Username"/><input name="pass" type="password" placeholder="Password"/><input type="submit" value="Sign In"/></form></body></html>'}
ROUTES["/login.php"] =            {"status": 200, "content": '<html><body><h1>Login</h1><form method="post"><input name="user"/><input name="pass"/></form><p>PHP login page.</p></body></html>'}
ROUTES["/logout"] =               {"status": 302, "location": "/"}
ROUTES["/register"] =             {"status": 200, "content": "<html><body><h1>Register</h1><form method='post'><input name='email'/><input name='pass'/></form></body></html>"}
ROUTES["/about"] =                {"status": 200, "content": "<html><body><h1>About Us</h1><p>About our company.</p><footer>&copy; 2024</footer></body></html>"}
ROUTES["/contact"] =              {"status": 200, "content": "<html><body><h1>Contact</h1><p>Email: info@example.com</p><p>Phone: +1-555-1234</p></body></html>"}
ROUTES["/search"] =               {"status": 200, "content": "<html><body><h1>Search</h1><form><input name='q' type='text' placeholder='Search...'/><button>Go</button></form></body></html>"}
ROUTES["/sitemap.xml"] =          {"status": 200, "content": '<?xml version="1.0"?><urlset><url><loc>http://localhost/</loc></url><url><loc>http://localhost/login</loc></url></urlset>', "content_type": "application/xml"}
ROUTES["/robots.txt"] =           {"status": 200, "content": "User-agent: *\nDisallow: /admin/\nDisallow: /backup/\nDisallow: /api/v2/\nDisallow: /config/\nAllow: /"}
ROUTES["/sitemap.xml.gz"] =       {"status": 200, "content": b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03', "content_type": "application/gzip"}
ROUTES["/favicon.ico"] =          {"status": 200, "content": b'\x00\x00\x01\x00\x01\x00\x10\x10\x00\x00\x01\x00\x08\x00\x68\x05', "content_type": "image/x-icon"}
ROUTES["/crossdomain.xml"] =      {"status": 200, "content": '<?xml version="1.0"?><cross-domain-policy><allow-access-from domain="*"/></cross-domain-policy>', "content_type": "application/xml"}
ROUTES["/humans.txt"] =           {"status": 200, "content": "/* TEAM */\nDeveloper: Alice\nDesigner: Bob\nManager: Charlie"}

# 根目录 3xx 重定向
ROUTES["/dashboard"] =            {"status": 302, "location": "/login"}
ROUTES["/home"] =                 {"status": 301, "location": "/"}
ROUTES["/old-login"] =            {"status": 301, "location": "/login"}
ROUTES["/legacy"] =               {"status": 301, "location": "/"}
ROUTES["/secure"] =               {"status": 302, "location": "/admin/"}

# 根目录 4xx / 5xx
ROUTES["/server-status"] =        {"status": 403, "content": "Forbidden: Server status is disabled."}
ROUTES["/server-info"] =          {"status": 403, "content": "Forbidden: Server info is disabled."}
ROUTES["/phpinfo.php"] =          {"status": 200, "content": "<html><body><h1>PHP Info</h1><table><tr><td>PHP Version</td><td>7.4.0</td></tr></table></body></html>"}

# 大响应体
ROUTES["/big-file"] =             {"status": 200, "content": random_content(80000)}
ROUTES["/tiny"] =                 {"status": 200, "content": "OK"}

# 隐藏文件
ROUTES["/.env"] =                 {"status": 403, "content": "Forbidden"}
ROUTES["/.htaccess"] =            {"status": 403, "content": "Forbidden"}
ROUTES["/.git/config"] =          {"status": 200, "content": "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n"}
ROUTES["/README.md"] =            {"status": 200, "content": "# Project\n\nThis is a benchmark target for directory scanning.\n\n## Setup\n\nRun `python testserver.py`\n"}
ROUTES["/CHANGELOG.txt"] =        {"status": 200, "content": "v1.0.0 - Initial release\nv1.1.0 - Added admin panel\nv1.2.0 - Added API v1\n"}

# ─── /admin/ 子目录 (20 个) ───
ROUTES["/admin/"] =               {"status": 200, "content": "<html><body><h1>Admin Dashboard</h1><nav><a href='/admin/users'>Users</a> | <a href='/admin/settings'>Settings</a> | <a href='/admin/logs'>Logs</a> | <a href='/admin/backup'>Backup</a></nav></body></html>"}
ROUTES["/admin/index.php"] =      {"status": 200, "content": "<html><body><h1>Admin Index</h1><p>Admin panel index.</p></body></html>"}
ROUTES["/admin/login"] =          {"status": 200, "content": '<html><body><h1>Admin Login</h1><form method="post" action="/admin/login"><input name="user" placeholder="Admin"/><input name="pass" type="password"/><input type="submit"/></form></body></html>'}
ROUTES["/admin/login.php"] =      {"status": 200, "content": '<html><body><h1>Admin Login (PHP)</h1><form method="post"><input name="user"/><input name="pass"/></form></body></html>'}
ROUTES["/admin/logout"] =         {"status": 302, "location": "/"}
ROUTES["/admin/users"] =          {"status": 200, "content": "<html><body><h1>Users</h1><table><tr><th>ID</th><th>Name</th><th>Role</th></tr><tr><td>1</td><td>admin</td><td>superuser</td></tr><tr><td>2</td><td>editor</td><td>editor</td></tr></table></body></html>"}
ROUTES["/admin/users/add"] =      {"status": 200, "content": "<html><body><h1>Add User</h1><form method='post'><input name='name'/><input name='role'/></form></body></html>"}
ROUTES["/admin/users/edit"] =     {"status": 200, "content": "<html><body><h1>Edit User</h1><form method='post'><input name='id' value='1'/><input name='name' value='admin'/></form></body></html>"}
ROUTES["/admin/users/delete"] =   {"status": 200, "content": "<html><body><h1>Delete User</h1><p>Are you sure?</p><form method='post'><button>Confirm</button></form></body></html>"}
ROUTES["/admin/settings"] =       {"status": 200, "content": "<html><body><h1>Settings</h1><form><label>Site Name: <input value='Example Corp'/></label><label>Max Users: <input value='1000'/></label></form></body></html>"}
ROUTES["/admin/settings/general"] = {"status": 200, "content": "<html><body><h1>General Settings</h1><p>General configuration.</p></body></html>"}
ROUTES["/admin/settings/security"] = {"status": 200, "content": "<html><body><h1>Security Settings</h1><p>Security configuration.</p></body></html>"}
ROUTES["/admin/settings/email"] = {"status": 200, "content": "<html><body><h1>Email Settings</h1><p>SMTP configuration panel.</p></body></html>"}
ROUTES["/admin/logs"] =           {"status": 200, "content": "<html><body><h1>Logs</h1><pre>2024-06-01 10:00:00 login admin\n2024-06-01 11:00:00 add_user editor\n2024-06-01 12:00:00 backup created\n2024-06-01 13:00:00 logout admin</pre></body></html>"}
ROUTES["/admin/logs/access"] =    {"status": 200, "content": "<html><body><h1>Access Logs</h1><pre>127.0.0.1 - [01/Jun/2024:10:00:00] GET /admin/ 200\n127.0.0.1 - [01/Jun/2024:10:01:00] POST /admin/login 200</pre></body></html>"}
ROUTES["/admin/logs/error"] =     {"status": 200, "content": "<html><body><h1>Error Logs</h1><pre>[error] File not found: /admin/old-page\n[error] Permission denied: /admin/config</pre></body></html>"}
ROUTES["/admin/config"] =         {"status": 403, "content": "Forbidden: Admin config access requires superuser role."}
ROUTES["/admin/backup"] =         {"status": 200, "content": "<html><body><h1>Admin Backup</h1><p>Backup management page.</p><a href='/admin/backup/run'>Run Backup</a></body></html>"}
ROUTES["/admin/backup/run"] =     {"status": 200, "content": "<html><body><h1>Run Backup</h1><p>Backup job started.</p></body></html>"}
ROUTES["/admin/panel"] =          {"status": 403, "content": "Forbidden: Old admin panel has been deprecated."}

# ─── /api/ 子路径 (18 个) ───
ROUTES["/api"] =                  {"status": 200, "content": '<html><body><h1>API Reference</h1><ul><li>GET /api/v1/users</li><li>GET /api/v1/info</li></ul></body></html>', "content_type": "text/html"}
ROUTES["/api/"] =                 {"status": 200, "content": '{"service":"scent-benchmark-api","version":"1.0","endpoints":["/api/v1/","/api/v2/"]}', "content_type": "application/json"}
ROUTES["/api/v1/"] =              {"status": 200, "content": '{"version":"v1","status":"stable","docs":"/api/v1/docs"}', "content_type": "application/json"}
ROUTES["/api/v1/info"] =          {"status": 200, "content": '{"name":"benchmark-api","version":"1.0.0","uptime":3600,"db":"connected","cache":"warm"}', "content_type": "application/json"}
ROUTES["/api/v1/health"] =        {"status": 200, "content": '{"status":"ok","db":"connected","redis":"connected","queue_size":0}', "content_type": "application/json"}
ROUTES["/api/v1/users"] =         {"status": 200, "content": '[{"id":1,"name":"admin","role":"superuser"},{"id":2,"name":"editor","role":"editor"},{"id":3,"name":"viewer","role":"viewer"}]', "content_type": "application/json"}
ROUTES["/api/v1/users/1"] =       {"status": 200, "content": '{"id":1,"name":"admin","email":"admin@example.com","role":"superuser","created":"2024-01-01"}', "content_type": "application/json"}
ROUTES["/api/v1/users/search"] =  {"status": 200, "content": '{"query":"","results":[],"count":0}', "content_type": "application/json"}
ROUTES["/api/v1/posts"] =         {"status": 200, "content": '[{"id":1,"title":"Hello World","author":"admin"}]', "content_type": "application/json"}
ROUTES["/api/v1/config"] =        {"status": 403, "content": '{"error":"forbidden","message":"Insufficient permissions"}', "content_type": "application/json"}
ROUTES["/api/v1/token"] =         {"status": 200, "content": '{"access_token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9","expires_in":3600,"token_type":"Bearer"}', "content_type": "application/json"}
ROUTES["/api/v1/docs"] =          {"status": 200, "content": '<html><body><h1>API Documentation</h1><p>Swagger docs.</p></body></html>', "content_type": "text/html"}
ROUTES["/api/v1/swagger.json"] =  {"status": 200, "content": '{"openapi":"3.0.0","info":{"title":"Benchmark API","version":"1.0.0"},"paths":{"/api/v1/users":{"get":{"summary":"List users"}}}}', "content_type": "application/json"}
ROUTES["/api/v2/"] =              {"status": 401, "content": '{"error":"unauthorized","message":"API v2 requires authentication"}', "content_type": "application/json"}
ROUTES["/api/v2/users"] =         {"status": 401, "content": '{"error":"unauthorized","message":"Valid API key required"}', "content_type": "application/json"}
ROUTES["/api/internal"] =         {"status": 403, "content": '{"error":"forbidden","message":"Internal API not accessible from external network"}', "content_type": "application/json"}
ROUTES["/api/admin"] =            {"status": 403, "content": '{"error":"forbidden","message":"Admin API key required"}', "content_type": "application/json"}

# POST 专用
ROUTES["/api/v1/login"] =         {"status": 200, "content": '{"token":"abc123xyz","expires":7200}', "content_type": "application/json", "method": "POST"}
ROUTES["/api/v1/logout"] =        {"status": 200, "content": '{"status":"ok"}', "content_type": "application/json", "method": "POST"}

# ─── /backup/ 子目录 (8 个) ───
ROUTES["/backup"] =               {"status": 200, "content": "<html><body><h1>Backups</h1><ul><li>db-2024-06-01.sql</li><li>site-2024-05-15.zip</li></ul></body></html>"}
ROUTES["/backup/"] =              {"status": 200, "content": "<html><body><h1>Backup Directory</h1><p>Listing of backup files.</p></body></html>"}
ROUTES["/backup/db.sql"] =        {"status": 200, "content": "-- Database backup\nCREATE TABLE users (\n  id INT PRIMARY KEY,\n  name VARCHAR(255),\n  password VARCHAR(255)\n);\nINSERT INTO users VALUES (1, 'admin', 'hash_admin_pass');\n"}
ROUTES["/backup/db-20240601.sql"] = {"status": 200, "content": "-- Database backup (2024-06-01)\n-- Contains all tables\n"}
ROUTES["/backup/site.zip"] =      {"status": 200, "content": b'PK\x03\x04\x14\x00\x00\x00\x00\x00\x00\x00!\x00', "content_type": "application/zip"}
ROUTES["/backup/site.tar.gz"] =   {"status": 200, "content": b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03', "content_type": "application/gzip"}
ROUTES["/backup/config.bak"] =    {"status": 200, "content": "# Configuration backup\nDB_HOST=localhost\nDB_NAME=app\nDB_USER=admin\nDB_PASS=secret123\nSECRET_KEY=abcdef123456\n"}
ROUTES["/backup/old"] =           {"status": 301, "location": "/backup"}

# ─── /config/ 子目录 (6 个) ───
ROUTES["/config"] =               {"status": 403, "content": "Forbidden: Direct config access not allowed."}
ROUTES["/config/app.json"] =      {"status": 200, "content": '{"app":{"name":"benchmark","debug":false,"log_level":"info"},"db":{"host":"localhost","port":3306}}', "content_type": "application/json"}
ROUTES["/config/app.yml"] =       {"status": 200, "content": "app:\n  name: benchmark\n  debug: false\n  log_level: info\ndb:\n  host: localhost\n  port: 3306\n", "content_type": "application/x-yaml"}
ROUTES["/config/database.ini"] =  {"status": 200, "content": "[database]\nhost = localhost\nport = 3306\nname = benchmark\ndbuser = app_user\npassword = app_pass_123\n"}
ROUTES["/config/routes.php"] =    {"status": 200, "content": "<?php\n// Route configuration\n$routes = [\n  '/' => 'home',\n  '/login' => 'auth_login',\n  '/admin' => 'admin_dashboard',\n];\n"}
ROUTES["/config/cache.php"] =     {"status": 200, "content": "<?php\n// Cache configuration\n$cache['driver'] = 'redis';\n$cache['ttl'] = 3600;\n"}

# ─── /static/ 资源 (6 个) ───
ROUTES["/static/"] =              {"status": 403, "content": "Forbidden: Directory listing disabled."}
ROUTES["/static/style.css"] =     {"status": 200, "content": "/* Main stylesheet */\nbody {font-family: Arial, sans-serif; margin: 0; padding: 20px;}\nh1 {color: #333;}\n.container {max-width: 1200px;}\n", "content_type": "text/css"}
ROUTES["/static/app.js"] =        {"status": 200, "content": "// Main application script\n(function() {\n  'use strict';\n  console.log('App initialized');\n  document.addEventListener('DOMContentLoaded', function() {\n    // Initialize components\n  });\n})();\n", "content_type": "application/javascript"}
ROUTES["/static/logo.png"] =      {"status": 200, "content": b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x10', "content_type": "image/png"}
ROUTES["/static/favicon.ico"] =   {"status": 200, "content": b'\x00\x00\x01\x00\x01\x00\x10\x10', "content_type": "image/x-icon"}
ROUTES["/static/vendor/jquery.min.js"] = {"status": 200, "content": "/*! jQuery v3.6.0 | (c) OpenJS Foundation */\nvar jQuery=function(a,b){return new jQuery.fn.init(a,b)};\n", "content_type": "application/javascript"}

# ─── /cgi-bin/ (2 个) ───
ROUTES["/cgi-bin/"] =             {"status": 403, "content": "Forbidden: CGI directory listing disabled."}
ROUTES["/cgi-bin/test.cgi"] =     {"status": 500, "content": "Internal Server Error: CGI script failed."}

# ─── 重定向到带斜杠的目录 ───
ROUTES["/admin"] =                {"status": 301, "location": "/admin/"}
ROUTES["/static"] =               {"status": 301, "location": "/static/"}
ROUTES["/cgi-bin"] =              {"status": 301, "location": "/cgi-bin/"}

# ─── /images/ (3 个) ───
ROUTES["/images/"] =              {"status": 200, "content": "<html><body><h1>Image Gallery</h1><p>Images directory.</p></body></html>"}
ROUTES["/images/photo1.jpg"] =    {"status": 200, "content": b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01', "content_type": "image/jpeg"}
ROUTES["/images/banner.gif"] =    {"status": 200, "content": b'GIF89a\x01\x00\x01\x00\x80\x00\x00', "content_type": "image/gif"}


def get_custom_404(path):
    """根据 URL 路径前缀返回对应错误页"""
    if path.startswith("/api/"):
        return API_404_JSON, "application/json"
    elif path.startswith("/admin/"):
        return ADMIN_404_HTML, "text/html"
    elif path.startswith("/backup/"):
        return BACKUP_404_HTML, "text/html"
    elif path.startswith("/config/"):
        return CONFIG_404_HTML, "text/html"
    elif path.startswith("/static/"):
        return ROOT_404_HTML, "text/html"
    else:
        return ROOT_404_HTML, "text/html"


# ─── Handler ──────────────────────────────────────────────────

class MockHandler(BaseHTTPRequestHandler):
    def _send_response(self, route):
        status = route["status"]
        content = route.get("content", "")
        if isinstance(content, str):
            content = content.encode("utf-8")
        content_type = route.get("content_type", "text/html")

        if status in (301, 302, 303, 307, 308):
            self.send_response(status)
            self.send_header("Location", route["location"])
            self.send_header("Content-Type", "text/html; charset=utf-8")
            body = f"Redirecting to {route['location']}".encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(status)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            # 添加一些有趣的响应头
            self.send_header("X-Powered-By", "scent-benchmark/4.0")
            self.send_header("X-Response-Time-Ms", str(random.randint(1, 50)))
            self.end_headers()
            self.wfile.write(content)

    def _handle_route(self, method):
        route = ROUTES.get(self.path)
        if route:
            expected = route.get("method", "GET")
            if expected != method:
                self.send_response(405)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Method Not Allowed")
                return
            self._send_response(route)
        else:
            if MULTI_404_MODE:
                content, ct = get_custom_404(self.path)
                status = 200  # 软 404
            elif SOFT_404_MODE:
                content = ROOT_404_HTML
                ct = "text/html"
                status = 200  # 软 404
            else:
                content = ROOT_404_HTML
                ct = "text/html"
                status = 404

            self.send_response(status)
            self.send_header("Content-Type", f"{ct}; charset=utf-8")
            body = content.encode() if isinstance(content, str) else content
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_GET(self):
        self._handle_route("GET")

    def do_POST(self):
        self._handle_route("POST")

    def do_HEAD(self):
        self._handle_route("HEAD")

    def log_message(self, format, *args):
        pass


# ─── 已知路径的 expected 结果集（供测试使用）─────────────────

EXPECTED = {}
for path, route in ROUTES.items():
    if route.get("method", "GET") == "GET":
        EXPECTED[path.lstrip("/")] = route["status"]

# 方便导入
def get_expected():
    return dict(EXPECTED)

def get_route_count():
    return len(ROUTES)


def main():
    global SOFT_404_MODE, MULTI_404_MODE

    if "--multi-404" in sys.argv:
        MULTI_404_MODE = True
    elif "--soft-404" in sys.argv:
        SOFT_404_MODE = True

    host, port = "127.0.0.1", 18888
    server = ThreadingHTTPServer((host, port), MockHandler)

    if MULTI_404_MODE:
        mode_str = " [多模板 404：root/admin/api/backup/config 各自不同错误页]"
    elif SOFT_404_MODE:
        mode_str = " [简单软 404：未知路径返回 200]"
    else:
        mode_str = ""

    print(f"[*] 基准靶场 v4 运行在 http://{host}:{port}{mode_str}")
    print(f"[*] 已知路径: {len(ROUTES)} 个 GET 端点")
    print(f"[*] POST 端点: {sum(1 for r in ROUTES.values() if r.get('method') == 'POST')} 个")
    print(f"[*] 状态码分布: " +
          " ".join(f"{code}xx={sum(1 for r in ROUTES.values() if r['status']//100==code)}"
                    for code in sorted({r["status"]//100 for r in ROUTES.values()})))
    print(f"[*] 未知路径 → HTTP {'200' if SOFT_404_MODE or MULTI_404_MODE else '404'}")
    print(f"[*] 按 Ctrl+C 停止\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] 靶场已关闭")


if __name__ == "__main__":
    main()
