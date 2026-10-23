"""
@Author: star_482
@Date: 2025/8/26 
@File: utils 
@Description:
"""

# app/utils/utils.py
from __future__ import annotations
from typing import List
from PIL import Image
import numpy as np

from ipaddress import ip_address
from typing import Mapping, Optional


def color_array_to_png(
    color_array: List[str], width: int, height: int, output_path: str | None = None
) -> bytes:
    """
    将颜色数组转换为PNG图片格式

    Args:
        color_array: 颜色数组，每个元素为十六进制颜色码（如"#FF0000"）
        width: 图片宽度
        height: 图片高度
        output_path: 可选，输出文件路径，如果提供则保存到文件

    Returns:
        bytes: PNG图片的字节数据

    Raises:
        ValueError: 当颜色数组长度与指定的宽高不匹配时
    """
    # 验证输入参数
    if len(color_array) != width * height:
        raise ValueError(f"颜色数组长度({len(color_array)})与指定尺寸({width}x{height}={width * height})不匹配")

    # 创建一个numpy数组来存储RGB值
    img_array = np.zeros((height, width, 3), dtype=np.uint8)

    # 将十六进制颜色转换为RGB值并填充到数组中
    for i, color_hex in enumerate(color_array):
        # 处理空字符串或无效颜色值的情况
        if not color_hex or len(color_hex) == 0:
            # 使用默认颜色（白色）替代
            color_hex = "#FFFFFF"
        elif color_hex.startswith('#'):
            color_hex = color_hex[1:]

        # 确保颜色值长度正确（应该为6个字符）
        if len(color_hex) != 6:
            # 使用默认颜色（白色）替代
            color_hex = "FFFFFF"

        # 将十六进制转换为RGB
        try:
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
        except ValueError:
            # 如果转换失败，使用默认颜色（白色）
            r, g, b = 255, 255, 255

        # 计算在数组中的位置
        y = i // width
        x = i % width

        # 填充RGB值
        img_array[y, x] = [r, g, b]

    # 创建PIL图像
    img = Image.fromarray(img_array, 'RGB')

    # 如果指定了输出路径，则只写入一次文件。
    if output_path:
        img.save(output_path, 'PNG')
        return b""

    # 将图像转换为字节数据
    from io import BytesIO
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    return img_bytes.getvalue()

def png_to_color_array(
    png_path: str | None = None, png_bytes: bytes | None = None
) -> List[str]:
    """
    将PNG图像转换为十六进制颜色值数组
    
    Args:
        png_path: PNG图片文件路径
        png_bytes: PNG图片字节数据
        
    Returns:
        List[str]: 颜色数组，每个元素为十六进制颜色码（如"#FF0000"）
        
    Raises:
        ValueError: 当既没有提供文件路径也没有提供字节数据时
    """
    # 验证输入参数
    if not png_path and not png_bytes:
        raise ValueError("必须提供png_path或png_bytes参数")
    
    # 加载图像并立即复制转换结果，确保底层文件句柄及时关闭。
    if png_path:
        with Image.open(png_path) as source_img:
            img = source_img.convert('RGB')
    else:
        assert png_bytes is not None
        from io import BytesIO
        with Image.open(BytesIO(png_bytes)) as source_img:
            img = source_img.convert('RGB')
    
    # 转换为numpy数组
    img_array = np.array(img)
    
    # 获取图像尺寸
    height, width = img_array.shape[:2]
    
    # 创建颜色数组
    color_array = []
    
    # 遍历每个像素
    for y in range(height):
        for x in range(width):
            # 获取RGB值
            r, g, b = img_array[y, x]
            
            # 转换为十六进制颜色码
            color_hex = f"#{r:02X}{g:02X}{b:02X}"
            
            # 添加到数组
            color_array.append(color_hex)
    
    return color_array




def _clean_ip_candidate(value: Optional[str]) -> Optional[str]:
    """Normalize a raw IP candidate and return valid IP or None."""
    if not value:
        return None

    s = value.strip()
    if not s or s.lower() == "unknown":
        return None

    # Handle common format: "client, proxy1, proxy2"
    if "," in s:
        s = s.split(",")[0].strip()

    # Handle bracketed IPv6: "[2001:db8::1]"
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()

    # Try direct parse first
    try:
        ip_address(s)
        return s
    except ValueError:
        pass

    # Handle possible "ip:port" (mostly IPv4 from some proxies)
    if ":" in s and s.count(":") == 1:
        host, _, _port = s.partition(":")
        host = host.strip()
        try:
            ip_address(host)
            return host
        except ValueError:
            return None

    return None


def extract_client_ip(
    headers: Mapping[str, str],
    client_host: Optional[str] = None,
    trust_proxy_headers: bool = False,
) -> Optional[str]:
    """
    Extract client IP behind reverse proxy.

    Priority:
    1) X-Forwarded-For (first hop)
    2) X-Real-IP
    3) direct client_host from socket
    """
    if trust_proxy_headers:
        xff = headers.get("x-forwarded-for")
        ip = _clean_ip_candidate(xff)
        if ip:
            return ip

        xri = headers.get("x-real-ip")
        ip = _clean_ip_candidate(xri)
        if ip:
            return ip

    return _clean_ip_candidate(client_host)


def extract_client_ip_from_websocket(
    websocket,
    trust_proxy_headers: bool = False,
) -> Optional[str]:
    """FastAPI/Starlette WebSocket helper."""
    client_host = websocket.client.host if websocket.client else None
    return extract_client_ip(
        websocket.headers,
        client_host,
        trust_proxy_headers=trust_proxy_headers,
    )


def extract_client_ip_from_request(
    request,
    trust_proxy_headers: bool = False,
) -> Optional[str]:
    """FastAPI/Starlette Request helper."""
    client_host = request.client.host if request.client else None
    return extract_client_ip(
        request.headers,
        client_host,
        trust_proxy_headers=trust_proxy_headers,
    )
