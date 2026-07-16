import re

# 排除媒体文件
MEDIA_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".mp3", ".webm", ".css", ".woff", ".ttf")

# 爬取内容
LINK_REGEX = re.compile(r'(?:href|src|action)\s*=\s*["\']([^"\']+)["\']')

def extract_links(content):
    """ 从HTML提取相对路径 """
    try:
        text = content.decode("utf-8", errors="ignore")
    except AttributeError:
        text = content

    links = set()
    for match in LINK_REGEX.findall(text):
        link = match.strip()
        # 排除空链接、媒体文件、外部链接、锚点、mailto、JavaScript
        if not link or link.lower().endswith(MEDIA_EXTENSIONS) or link.startswith(("http://", "https://", "//", "mailto:", "javascript:", "#")):
            continue
        # 去掉开头的”/“
        if link.startswith("/"):
            link = link[1:]
        links.add(link)

    return links

