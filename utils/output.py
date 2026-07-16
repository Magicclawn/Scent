"""输出工具：彩色状态码格式化"""
import json
import csv


class ReportWriter:
    def __init__(self, report_path, report_format="txt"):
        self.report_path = report_path
        self.report_format = report_format
        self.report_data = []

    def add_result(self, path, status, size, redirect, content_type):
        self.report_data.append({"path": path, "status": status, "size": size, "redirect": redirect, "content_type": content_type})

    def _write_txt(self):
        with open(self.report_path, "w") as f:
            for data in self.report_data:
                path = data["path"]
                status = data["status"]
                content_length = data["size"]
                redirect = data["redirect"]
                if status in (301, 302):
                    f.write(f"[+] /{path} -> {redirect} (HTTP {status}), {content_length}B\n")
                else:
                    f.write(f"[+] /{path} (HTTP {status}), {content_length}B\n")

    def _write_csv(self):
        with open(self.report_path, "w") as f:
            writer = csv.writer(f)
            writer.writerow(["path", "status", "size", "redirect", "content_type"]) # 表头
            for data in self.report_data:
                writer.writerow([data["path"], data["status"], data["size"], data["redirect"], data["content_type"]])

    def _write_json(self):
        with open(self.report_path, "w") as f:
            json.dump(self.report_data, f, indent=2, ensure_ascii=False)

    def _write_html(self):
        STATUS_COLORS = {
            200: "#22c55e", 301: "#eab308", 302: "#eab308",
            401: "#3b82f6", 403: "#a855f7", 404: "#6b7280", 500: "#ef4444",
        }
        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>")
            f.write("<title>scent Report</title>")
            f.write("<style>")
            f.write("body{font-family:system-ui,sans-serif;margin:2rem;background:#f9fafb}")
            f.write("h1{color:#1f2937}")
            f.write("table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1)}")
            f.write("th,td{padding:.5rem 1rem;text-align:left;border-bottom:1px solid #e5e7eb}")
            f.write("th{background:#f3f4f6;font-weight:600}")
            f.write("tr:hover{background:#f9fafb}")
            f.write("</style></head><body>")
            f.write(f"<h1>scent Report</h1>")
            f.write(f"<p>Found <b>{len(self.report_data)}</b> paths</p>")
            f.write("<table><tr>")
            for col in ["Path", "Status", "Size", "Redirect", "Content-Type"]:
                f.write(f"<th>{col}</th>")
            f.write("</tr>")
            for data in self.report_data:
                color = STATUS_COLORS.get(data["status"], "#374151")
                status_text = f"{data['status']}" if data["status"] else "ERR"
                f.write("<tr>")
                f.write(f"<td>/{data['path']}</td>")
                f.write(f"<td style='color:{color};font-weight:600'>{status_text}</td>")
                f.write(f"<td>{data['size']}B</td>")
                f.write(f"<td>{data['redirect'] or '-'}</td>")
                f.write(f"<td>{data['content_type']}</td>")
                f.write("</tr>")
            f.write("</table></body></html>")

    def close(self):
        if self.report_format == "json":
            self._write_json()
        elif self.report_format == "html":
            self._write_html()
        elif self.report_format == "txt":
            self._write_txt()
        elif self.report_format == "csv":
            self._write_csv()
        print(f"[*] 报告已保存至 {self.report_path}")