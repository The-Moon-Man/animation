#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
番剧自动整理工具 v1.9.3
功能：
  - 自动提取视频文件信息（标题、集数、季度等）
  - 从AniBK刮削番剧数据（标题、简介、海报等）
  - 智能语言匹配（中日文混合环境）
  - 重命名文件为标准格式
  - 生成NFO元数据文件
  - 多番剧自动分组
  - 文件夹级别100%匹配加速
  - 源文件追踪与错误恢复
  - 双层缓存机制

作者：[Your Name]
版本：v1.9.3
日期：2024
"""

import os
import re
import json
import requests
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from xml.etree import ElementTree as ET
from xml.dom import minidom
from bs4 import BeautifulSoup


# ============================================================================
# 配置常量
# ============================================================================

# 支持的视频文件扩展名
VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.wmv', '.mov', '.flv', '.webm'}

# AniBK番组百科基础URL
ANIBK_BASE_URL = "https://www.anibk.com"

# Bangumi API基础URL（预留，当前未使用）
BANGUMI_BASE_URL = "https://api.bgm.tv"


# ============================================================================
# 数据类
# ============================================================================

class VideoInfo:
    """视频文件信息数据类
    
    存储从视频文件名中提取的各种信息
    """
    def __init__(self):
        self.file_path = ""          # 文件完整路径
        self.title = ""              # 提取的标题
        self.clean_title = ""        # 清理后的标题（用于搜索）
        self.episode = None          # 集数（整数）
        self.episode_title = ""      # 集数名称
        self.season = None           # 季度（整数）
        self.year = None             # 年份（整数）
        self.resolution = ""         # 分辨率（如720p, 1080p）
        self.source = ""             # 来源（如BluRay, WEB-DL）
        self.codec = ""              # 编码（如x264, HEVC）
        self.group = ""              # 字幕组名称
        self.special_type = ""       # 特殊类型（OVA, OAD, 剧场版等）


class AnimeInfo:
    """番剧信息数据类
    
    存储从刮削网站获取的番剧详细信息
    """
    def __init__(self):
        self.title = ""              # 中文标题
        self.original_title = ""     # 原版标题（日文/英文）
        self.year = None             # 年份
        self.plot = ""               # 剧情简介
        self.rating = None           # 评分
        self.genres = []             # 类型标签列表
        self.studio = ""             # 制作公司
        self.premiered = ""          # 首播日期
        self.episodes_total = None   # 总集数
        self.poster_url = ""         # 海报URL
        self.fanart_url = ""         # 背景图URL
        self.tags = []               # 标签列表
        self.source_url = ""         # 来源URL
        self.source_id = ""          # 来源ID
        self.all_names = {}          # 所有名称字典（v1.6新增）

zm_pattern = r'\b(' \
                  r'简体|繁体|简繁|港台|' \
                  r'CHS|CHT|SC|TC|zh-CN|zh-TW|' \
                  r'BIG5|GB2312|GBK|UTF-8|UTF8|' \
                  r'英文|English|ENG|EN|eng|' \
                  r'日文|日语|JP|JPN|JAP|jap|Japanese|' \
                  r'HardSub|HARDSUB|Hard Subs|硬字幕|硬烧|内嵌字幕|' \
                  r'SoftSub|SOFTSUB|软字幕|外挂字幕|可选字幕|' \
                  r'ASS|SSA|SRT|SUB|VTT|LRC|' \
                  r'双语|中英双语|双字幕|多语言|' \
                  r'官方字幕|官方中字|Official Subs|' \
                  r'精校字幕|校对字幕|校正字幕|' \
                  r'高清字幕|HiHD|' \
                  r'无字幕|无字|' \
                  r'内嵌|外挂' \
                  r')\b'
# ============================================================================
# 视频文件解析器
# ============================================================================
def sanitize_filename(name, max_length=230):
    """
    清理并限制字符串，使其适合Linux文件命名

    参数:
        name: 原始文件名
        max_length: 最大字节长度，Linux默认255字节

    返回:
        安全的文件名
    """
    # 移除或替换Linux文件名中的非法字符
    # Linux中只有 '/' 和 '\0' 是非法的，但为了兼容性，也处理其他特殊字符
    illegal_chars = r'[/\0]'
    name = re.sub(illegal_chars, '_', name)

    # 可选：替换其他可能引起问题的字符
    problematic_chars = r'[<>:"|?*\\]'
    name = re.sub(problematic_chars, '_', name)

    # 移除首尾空格和点号（避免隐藏文件或路径问题）
    name = name.strip('. ')

    # 如果为空，提供默认名称
    if not name:
        name = "unnamed_file"

    # 限制字节长度（UTF-8编码）
    name_bytes = name.encode('utf-8')
    if len(name_bytes) <= max_length:
        return name

    # 截断到最大字节数，避免截断多字节字符
    truncated_bytes = name_bytes[:max_length]
    # 使用errors='ignore'避免不完整的UTF-8序列
    truncated_name = truncated_bytes.decode('utf-8', errors='ignore')

    # 再次清理尾部空格
    return truncated_name.rstrip('. ')


# def sanitize_filename_with_extension(name, max_length=255):
#     """
#     保留文件扩展名的安全文件名生成
#
#     参数:
#         name: 原始文件名（包含扩展名）
#         max_length: 最大字节长度
#
#     返回:
#         安全的文件名（保留扩展名）
#     """
#     # 分离文件名和扩展名
#     if '.' in name:
#         parts = name.rsplit('.', 1)
#         basename = parts[0]
#         extension = '.' + parts[1]
#     else:
#         basename = name
#         extension = ''
#
#     # 清理基础名称
#     basename = sanitize_filename(basename, max_length)
#
#     # 确保扩展名也是安全的
#     extension = sanitize_filename(extension.lstrip('.'), max_length)
#     if extension:
#         extension = '.' + extension
#
#     # 组合并确保总长度不超限
#     full_name = basename + extension
#     full_bytes = full_name.encode('utf-8')
#
#     if len(full_bytes) <= max_length:
#         return full_name
#
#     # 如果超长，缩短基础名称
#     extension_bytes = extension.encode('utf-8')
#     available_bytes = max_length - len(extension_bytes)
#
#     if available_bytes <= 0:
#         # 扩展名太长，只能截断整体
#         return sanitize_filename(full_name, max_length)
#
#     basename_bytes = basename.encode('utf-8')[:available_bytes]
#     basename = basename_bytes.decode('utf-8', errors='ignore').rstrip('. ')
#
#     return basename + extension


def cjk_to_number(cjk_numeral):
    numerals = {
        '零': 0, '〇': 0, '○': 0,
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9,
        '壱': 1, '弌': 1,
        '弍': 2, '弐': 2,
        '弎': 3, '参': 3,
        '肆': 4, '伍': 5, '陸': 6, '漆': 7, '捌': 8, '玖': 9,
        '两': 2, '兩': 2,
    }
    units = {
        '十': 10, '拾': 10,
        '百': 100, '佰': 100,
        '千': 1000, '仟': 1000,
        '万': 10**4, '萬': 10**4,
        '亿': 10**8, '億': 10**8,
    }

    result = 0
    section = 0
    number = 0
    i = 0
    length = len(cjk_numeral)

    while i < length:
        char = cjk_numeral[i]
        if char in numerals:
            number = numerals[char]
            i += 1
        elif char in units:
            unit_val = units[char]
            if unit_val >= 10000:
                section = (section + number) * unit_val
                result += section
                section = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit_val
            number = 0
            i += 1
        else:
            break
    result += section + number
    return result

def fullwidth_to_halfwidth(text):
    return ''.join(
        chr(ord(c) - 0xFEE0) if '０' <= c <= '９' else c
        for c in text
    )



def replace_numbers(match):
    token = match.group()
    if token.isdigit():
        value = int(token)
    else:
        value = cjk_to_number(token)
    return str(value)

def convert_text_numbers(text):
    cjk_digits = '零〇○一二三四五六七八九十拾百佰千仟万萬亿億兩壱弌弍弎肆伍陸漆捌玖弐参'
    pattern = re.compile(r'(\d+|[' + cjk_digits + r']+)')
    text = fullwidth_to_halfwidth(text)
    return pattern.sub(replace_numbers, text)


def match_title(text):
    # 排除含英文+数字混合的情况
    # 例如：E01，EP02，A3 等不匹配
    if re.search(r'[A-Za-z]+\d+', text):
        return False

    return True

class VideoFileParser:
    """视频文件名解析器
    
    从视频文件名中提取各种信息：
    - 字幕组、分辨率、来源、编码等技术信息
    - 标题、季度、集数等内容信息
    - 特殊类型（OVA、剧场版等）
    """
    
    @staticmethod
    def parse_filename(filename: str) -> VideoInfo:
        """解析文件名，提取番剧信息
        
        Args:
            filename: 视频文件名（包含扩展名）
            
        Returns:
            VideoInfo对象，包含提取的所有信息
            
        示例：
            输入: "[Lilith-Raws] 我推的孩子 S01E01 [1080p].mkv"
            输出: VideoInfo(title="我推的孩子", season=1, episode=1, resolution="1080p", group="Lilith-Raws")
        """
        info = VideoInfo()
        info.file_path = filename
        name_without_ext = Path(filename).stem  # 去除扩展名

        print(f"\n  原始文件名: {name_without_ext}")

        # ========== 提取来源 ==========
        # 格式：BluRay, WEB-DL, HDTV等
        source_match = re.search(r'(BluRay|18禁|無修正|DVD|BDRip|WEB-?DL|HDTV|DVDRip|x264|x265|HEVC|AVC|H\.?264|H\.?265)',
                                 name_without_ext, re.IGNORECASE)
        if source_match:
            info.source = source_match.group(1).upper()
            print(f"  来源: {info.source}")
        name_without_ext = re.sub(r'(BluRay|18禁|無修正|DVD|BDRip|WEB-?DL|HDTV|DVDRip|x264|x265|HEVC|AVC|H\.?264|H\.?265)', '', name_without_ext,
                       flags=re.IGNORECASE)
        # ========== 提取编码 ==========
        # 格式：x264, x265, HEVC等
        codec_match = re.search(r'\b(x264|x265|HEVC|AVC|H\.?264|H\.?265)\b', name_without_ext, re.IGNORECASE)
        if codec_match:
            info.codec = codec_match.group(1).upper()
            print(f"  编码: {info.codec}")
        name_without_ext = re.sub(r'\b(x264|x265|HEVC|AVC|H\.?264|H\.?265)\b', '',name_without_ext,flags=re.IGNORECASE)
        # ========== 提取年份 ==========
        # 格式：1900-2099
        year_match = re.search(r'\b(19|20)\d{2}\b', name_without_ext)
        if year_match:
            info.year = int(year_match.group(0))
            print(f"  年份: {info.year}")
        name_without_ext = re.sub(r'\b(19|20)\d{2}\b', '',name_without_ext)

        name_without_ext = re.sub(zm_pattern, '', name_without_ext, flags=re.IGNORECASE)

        # ========== 提取字幕组 ==========
        # 格式：[字幕组名称]
        group_match = re.match(r'^\[([^\]]+)\]', name_without_ext)
        if group_match:
            info.group = group_match.group(1)
            print(f"  字幕组: {info.group}")
            name_without_ext = name_without_ext[group_match.end():]
        # ========== 提取分辨率 ==========
        # 格式：[720p] 或 1080p
        res_match = re.search(r'\[(\d{3,4}[pPi])\]|\b(\d{3,4}[pP])\b', name_without_ext)
        if res_match:
            info.resolution = (res_match.group(1) or res_match.group(2)).lower()
            print(f"  分辨率: {info.resolution}")
            name_without_ext = re.sub(r'\[(\d{3,4}[pPi])\]|\b(\d{3,4}[pP])\b', '', name_without_ext)

        # ========== 提取特殊类型 ==========
        # OVA, OAD, 剧场版, 番外, SP等
        special_patterns = [
            (r'(OVA|OAD|ONA)', 'OVA'),
            (r'\b(SP|Special|特别篇)\b', 'SP'),
            (r'(剧场版|电影版|Movie)', '剧场版'),
            (r'(番外|Extra)', '番外'),
            (r'(总集篇|Recap)', '总集篇'),
        ]
        
        for pattern, type_name in special_patterns:
            if re.search(pattern, name_without_ext, re.IGNORECASE):
                info.special_type = type_name
                print(f"  特殊类型: {info.special_type}")
                break
        name_without_ext0 = convert_text_numbers(name_without_ext)
        # ========== 提取季数 ==========
        # 格式：S01, 第二季, Season 2, 第2期
        season_patterns = [
            r'\bS(\d{1,2})\b',      # S01, S02
            r'第(\d+)季',            # 第二季
            r'Season\s*(\d+)',      # Season 2
            r'\b(\d+)期\b',         # 第2期
        ]
        for pattern in season_patterns:
            match = re.search(pattern, name_without_ext0, re.IGNORECASE)
            if match:
                info.season = int(match.group(1))
                print(f"  季数: 第{info.season}季")
                break

        # ========== 提取集数 ==========
        # 格式：E01, EP01, 第01话, [01], - 01
        episode_patterns = [
            # === 基本数字形式 ===
            r'\bE(\d{1,3})\b',  # E01, E02
            r'\bEP(\d{1,3})\b',  # EP01, EP02
            r'\be(\d{1,3})\b',  # e01, e02 (小写)
            r'\bep(\d{1,3})\b',  # ep01, ep02 (小写)
            r'\b第(\d{1,3})[话集]\b',  # 第01话, 第01集
            r'[\s\-_]\[(\d{1,3})\]',  # [01], -[01]
            r'[\s\-_](\d{2,3})(?:\s|\.|\[|$)',  # - 01, _01
            r'\b(\d{1,3})[话集]\b',  # 01话, 01集 (无"第"字)

            # === 中文数字表达 ===
            # r'\b第([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)[话集章节卷部]\b',  # 第零一话, 第三话
            # r'\b第([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)(?:[话集章节卷部])?$',  # 第三, 第十话
            # r'\b([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)[话集章节卷部]\b',  # 一话, 三集

            # === 单独数字（阿拉伯数字）===
            r'^(\d{1,3})$',  # 01, 001, 1 (文件名本身是数字)
            r'\b(\d{2,3})\b',  # 01, 12, 001 (独立的2-3位数字)
            # r'^(\d{1,3})[^\d]*$',  # 01.mp4, 1.avi (以数字开头，后接非数字)
            r'[\s\-_](\d{1,3})$',  # -01, _1 (以数字结尾)
            # r'^(\d{1,3})[\s\-_]',  # 01-, 1_ (以数字开头)
            r'[^\d](\d{2,3})[^\d]',  # 前后都是非数字，单独的数字

            # === 单独中文数字 ===
            # r'^([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)$',  # 一, 三, 十
            # r'\b([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)\b',  # 独立的中文数字
            # r'^([壱弐参]+)\b',
            # r'\b([壱弐参]+)\b',
            # r'^([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)[^\u4e00-\u9fa5\d]',  # 中文数字开头
            # r'[^\u4e00-\u9fa5\d]([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)$',  # 中文数字结尾
            # r'[^\u4e00-\u9fa5\d]([壱弐参]+)$',
            # === 中文大写数字单独使用 ===
            # r'^([零壹贰叁肆伍陆柒捌玖拾佰仟万亿兩]+)$',  # 壹, 叁, 拾
            # r'\b([零壹贰叁肆伍陆柒捌玖拾佰仟万亿兩]+)\b',  # 独立的大写数字

            # r'^([壱弐参]+)$',  # 壹, 叁, 拾
            # r'\b([壱弐参]+)\b',  # 独立的大写数字
            # === 中文数字混合阿拉伯数字 ===
            # r'\b第([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)(\d{1,3})[话集]\b',  # 第三01话
            # r'\b([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)(\d{1,3})[话集]\b',  # 三01话
            # r'\b第([壱弐参]+)(\d{1,3})[话集]\b',  # 第三01话
            # r'\b([壱弐参]+)(\d{1,3})[话集]\b',  # 三01话

            # === 带"#"符号的形式 ===
            r'#(\d{1,3})\b',  # #01, #001
            r'\b#(\d{1,3})[话集]\b',  # #01话, #01集
            # r'#([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)\b',  # #一, #三
            # r'#([壱弐参]+)\b',  # #一, #三
            # === 括号形式 ===
            r'\((\d{1,3})\)',  # (01)
            r'（(\d{1,3})）',  # （01）中文括号
            r'【(\d{1,3})】',  # 【01】
            r'「(\d{1,3})」',  # 「01」
            r'\d+$',
            # r'（([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)）',  # （一）, （三）
            # r'【([零一二三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟万亿两]+)】',  # 【一】, 【三】
            # r'（([壱弐参]+)）',  # （一）, （三）
            # r'【([壱弐参]+)】',  # 【一】, 【三】
            # === 完整英文形式 ===
            r'\bEpisode\s?(\d{1,3})\b',  # Episode 01, Episode01
            r'\bepisode\s?(\d{1,3})\b',  # episode 01, episode01
            r'\bEPISODE\s?(\d{1,3})\b',  # EPISODE 01

            # === 带季节标记 ===
            # r'\bS\d{1,2}E(\d{1,3})\b',  # S01E01, S2E03
            # r'\bSeason\s?\d{1,2}\s?Episode\s?(\d{1,3})\b',  # Season 1 Episode 01

            # === 其他常见格式 ===
            r'[\s\-_]第?(\d{1,3})[话集][\s\-_]',  # -第01话-, _01集_
            r'[\[\(]?第?(\d{1,3})[\]\)]',  # [01], (01)
            r'[\s\-_](\d{1,3})v\d+\b',  # 01v2, 001v3 (带版本号)
            r'\bVOL[\.\s]?(\d{1,3})\b',  # VOL.01, VOL 01
            r'\bVol[\.\s]?(\d{1,3})\b',  # Vol.01, Vol 01

            # === 特殊分隔符 ===
            r'[\s\-_](\d{1,3})[_\-.].*?$',  # 01_.mkv, 001-.avi
            r'^(\d{1,3})[\s\-_]',  # 01_, 001-

            # === 中日韩混合格式 ===
            r'\b第?(\d{1,3})[話话集]\b',  # 第01話, 01話 (日文)
            r'\b第?(\d{1,3})회\b',  # 第01회, 01회 (韩文)
            r'\b第?(\d{1,3})화\b',  # 第01화, 01화 (韩文)

            # === 点分隔 ===
            r'\.(\d{2,3})\.',  # .01., .001.
            r'^(\d{2,3})\.',  # 01., 001.

            # === 横线分隔 ===
            r'-(\d{2,3})-',  # -01-, -001-
            r'_(\d{2,3})_',  # _01_, _001_

            # === 带前导零的处理 ===
            # r'\b0*(\d{1,3})\b',  # 001, 0001 (匹配去掉前导零的数字)
        ]

        for pattern in episode_patterns:
            separators = [' ', '.', '_', '-', '【', '】', '[', ']']

            for sep in separators:
                if sep in name_without_ext0:
                    parts = name_without_ext0.split(sep)
                    # 尝试前N个部分的组合
                    for i in range(1, min(len(parts) + 1, 4)):  # 最多尝试前3个部分
                        print(sep.join(parts[:i]).strip())
                        match = re.search(pattern, sep.join(parts[:i]).strip(), re.IGNORECASE)
                        if match :
                            if match_title(match.group()):
                                """提取字符串中的第一个数字（整数）并转换为int"""
                                match0 = re.search(r'(\d+)', match.group())
                                if match0 :
                                    if int(match0.group(0)) <=30 :
                                        info.episode = int(match0.group(0))
                                break


        # ========== 提取标题 ==========
        title = name_without_ext
        
        # 移除字幕组
        title = re.sub(r'^\[[^\]]+\]\s*', '', title)
        
        # 移除集数相关信息
        title = re.sub(r'\s*[\-\_]\s*\d{1,3}.*', '', title)
        title = re.sub(r'\s*\[.*?\]\s*', ' ', title)
        title = re.sub(r'\bS\d{1,2}E\d{1,3}\b.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\bEP?\d{1,3}\b.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'第\d{1,3}[话集].*', '', title)
        
        # 移除技术信息
        title = re.sub(r'\b(19|20)\d{2}\b', '', title)
        title = re.sub(r'\b(\d{3,4}[pP])\b', '', title)
        title = re.sub(r'\b(BluRay|BDRip|WEB-?DL|HDTV|DVDRip|x264|x265|HEVC|AVC|H\.?264|H\.?265)\b', '', title, flags=re.IGNORECASE)
        
        # 清理空格和特殊字符
        title = re.sub(r'[\s\.\_]+', ' ', title)
        title = title.strip()
        
        info.title = title if title else name_without_ext
        
        # ========== 生成清理后的标题（用于搜索） ==========
        clean_title = info.title
        # 移除季度信息（用于搜索主系列）
        clean_title = re.sub(r'第[一二三四五六七八九十\d]+季', '', clean_title)
        clean_title = re.sub(r'Season\s*\d+', '', clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r'\d+期', '', clean_title)
        # 移除特殊类型
        clean_title = re.sub(r'\b(OVA|OAD|ONA|SP|Special|特别篇|剧场版|电影版|Movie|番外|Extra|总集篇|Recap)\b', '', clean_title, flags=re.IGNORECASE)
        clean_title = re.sub(r'\s+', ' ', clean_title).strip()
        
        info.clean_title = clean_title if clean_title else info.title
        
        print(f"  提取标题: {info.title}")
        if info.clean_title != info.title:
            print(f"  清理标题: {info.clean_title} (用于搜索)")

        patternlive = r'[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffa-zA-Z0-9]'
        info.name_other = re.sub(patternlive, '', name_without_ext0)

        return info
    
    @staticmethod
    def generate_alternative_titles(filename: str) -> List[str]:
        """生成多个可能的标题变体（用于重试匹配）
        
        当第一次匹配失败时，尝试不同的分割方式提取标题
        """
        name_without_ext = Path(filename).stem
        alternatives = []
        
        # 移除字幕组
        text = re.sub(r'^\[[^\]]+\]\s*', '', name_without_ext)
        
        # 方法1: 按常见分隔符分割（空格、点、下划线、连字符）
        # 尝试不同的分割点
        separators = [' ', '.', '_', '-', '【', '】', '[', ']']
        
        for sep in separators:
            if sep in text:
                parts = text.split(sep)
                # 尝试前N个部分的组合
                for i in range(1, min(len(parts) + 1, 4)):  # 最多尝试前3个部分
                    title_candidate = sep.join(parts[:i]).strip()
                    # 清理标题
                    title_candidate = VideoFileParser._clean_title_for_search(title_candidate)
                    if title_candidate and len(title_candidate) >= 2:
                        alternatives.append(title_candidate)
        
        # 方法2: 按数字分割（集数前的内容）
        # 匹配第一个数字前的内容
        # match = re.match(r'^(.+?)[\s\-_]*\d', text)
        # if match:
        #     title_candidate = match.group(1).strip()
        #     title_candidate = VideoFileParser._clean_title_for_search(title_candidate)
        #     if title_candidate and len(title_candidate) >= 2:
        #         alternatives.append(title_candidate)
        
        # 方法3: 按括号分割
        # 提取第一个括号前的内容
        match = re.match(r'^([^\[\(（【]+)', text)
        if match:
            title_candidate = match.group(1).strip()
            title_candidate = VideoFileParser._clean_title_for_search(title_candidate)
            if title_candidate and len(title_candidate) >= 2:
                alternatives.append(title_candidate)
        
        # 方法4: 移除所有特殊字符后的内容
        title_candidate = re.sub(r'[\[\]()（）【】\-_\.]', ' ', text)
        title_candidate = re.sub(r'\s+', ' ', title_candidate).strip()
        # 取前几个词
        words = title_candidate.split()

        if len(words) >= 2:
            for candidate in words:
                # candidate = ' '.join(words[i])
                candidate = VideoFileParser._clean_title_for_search(candidate)
                if candidate and len(candidate) >= 2:
                    alternatives.append(candidate)
        
        # 去重并保持顺序
        seen = set()
        unique_alternatives = []
        for alt in alternatives:
            if alt not in seen and alt:
                seen.add(alt)
                unique_alternatives.append(alt)
        
        return unique_alternatives
    
    @staticmethod
    def _clean_title_for_search(title: str) -> str:
        """清理标题用于搜索
        
        移除所有可能干扰搜索的信息：
        - 技术信息（分辨率、编码、来源等）
        - 季度信息
        - 特殊类型标记
        - 多余的标点符号
        
        Args:
            title: 原始标题
            
        Returns:
            清理后的标题
        """
        # 移除技术信息
        title = re.sub(r'\b(19|20)\d{2}\b', '', title)  # 年份
        title = re.sub(r'\b(\d{3,4}[pP])\b', '', title)  # 分辨率
        title = re.sub(r'(BluRay|18禁|無修正|DVD|BDRip|WEB-?DL|HDTV|DVDRip|x264|x265|HEVC|AVC|H\.?264|H\.?265|AAC|CHT|Baha)', '', title, flags=re.IGNORECASE)

        # 移除特殊类型
        title = re.sub(r'(OVA|OAD|ONA|SP|Special|特别篇|剧场版|电影版|Movie|番外|Extra|总集篇|Recap)', '', title, flags=re.IGNORECASE)



        title = re.sub(zm_pattern, '', title, flags=re.IGNORECASE)

        # 移除季度信息
        title = re.sub(r'第[一二三四五六七八九十\d]+季', '', title)
        title = re.sub(r'Season\s*\d+', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\d+期', '', title)
        
        # 移除集数信息
        title = re.sub(r'第\d+[话集]', '', title)
        title = re.sub(r'\bE\d+\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\bEP\d+\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\bS\d+E\d+\b', '', title, flags=re.IGNORECASE)
        
        # 清理标点符号
        title = re.sub(r'[\[\]()（）【】\-_]+$', '', title)  # 移除末尾的标点
        title = re.sub(r'^[\[\]()（）【】\-_]+', '', title)  # 移除开头的标点
        title = re.sub(r'[\[\]()（）【】]{2,}', '', title)  # 移除连续的括号
        title = re.sub(r'\.+$', '', title)  # 移除末尾的点号
        title = re.sub(r'\s+', ' ', title).strip()  # 规范化空格
        
        return title
        if year_match:
            info.year = int(year_match.group(0))
        
        # 提取季数
        season_match = re.search(r'\bS(\d{1,2})\b|第(\d+)季|Season\s*(\d+)', name_without_ext, re.IGNORECASE)
        if season_match:
            info.season = int(season_match.group(1) or season_match.group(2) or season_match.group(3))
        
        # 提取集数
        episode_patterns = [
            r'\bE(\d{1,3})\b',
            r'\bEP(\d{1,3})\b',
            r'第(\d{1,3})[话集]',
            r'[\s\-_]\[(\d{1,3})\]',
            r'[\s\-_](\d{2,3})(?:\s|\.|\[|$)',
        ]
        for pattern in episode_patterns:
            match = re.search(pattern, name_without_ext, re.IGNORECASE)
            if match:
                info.episode = int(match.group(1))
                break
        
        # 提取标题
        title = name_without_ext
        title = re.sub(zm_pattern, '', title)
        title = re.sub(r'^\[[^\]]+\]\s*', '', title)
        title = re.sub(r'\s*[\-\_]\s*\d{1,3}.*', '', title)
        title = re.sub(r'\s*\[.*?\]\s*', ' ', title)
        title = re.sub(r'\bS\d{1,2}E\d{1,3}\b.*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\b(19|20)\d{2}\b', '', title)
        title = re.sub(r'\b(\d{3,4}[pP])\b', '', title)
        title = re.sub(r'\b(BluRay|18禁|無修正|DVD|BDRip|WEB-?DL|HDTV|DVDRip|x264|x265|HEVC|AVC|H\.?264|H\.?265)\b', '', title, flags=re.IGNORECASE)
        title = re.sub(r'[\s\.\_]+', ' ', title)
        title = title.strip()
        
        info.title = title if title else name_without_ext
        
        return info
    
    @staticmethod
    def generate_new_filename(video_info: VideoInfo, anime_info: AnimeInfo, original_ext: str) -> str:
        """生成新文件名
        
        格式: 中文名[日文名/英文名] - 季度 - 集数 - 集数名称
        示例: 我推的孩子[推しの子] - S01 - E01 - 母与子
        
        v1.6改进：智能识别中文名称
        - 从所有名称中识别中文名称
        - 若没有中文名称，翻译日文/英文名称
        - 若翻译失败，使用提取的标题
        """
        # 智能选择中文标题和原名
        chinese_title = None
        japanese_title = None
        english_title = None
        
        # 如果有all_names，从中智能识别
        if hasattr(anime_info, 'all_names') and anime_info.all_names:
            all_names = anime_info.all_names
            
            print(f"\n  [命名] 开始选择标题...")
            print(f"  [命名] 可用名称: {list(all_names.keys())}")
            
            # 1. 优先查找"其他名称"（通常是中文）
            if 'other_name' in all_names:
                other_name = all_names['other_name']
                print(f"  [命名] 检查其他名称: {other_name}")
                if AniBKScraper._is_chinese_title(other_name):
                    chinese_title = other_name
                    print(f"  [命名] ✓ 使用其他名称作为中文标题: {chinese_title}")
            
            # 2. 其次查找明确标注的中文名
            if not chinese_title and 'chinese_name' in all_names:
                chinese_name = all_names['chinese_name']
                print(f"  [命名] 检查中文名称: {chinese_name}")
                if AniBKScraper._is_chinese_title(chinese_name):
                    chinese_title = chinese_name
                    print(f"  [命名] ✓ 使用中文名称: {chinese_title}")
            
            # 3. 如果没有明确的中文名，检查所有名称
            if not chinese_title:
                print(f"  [命名] 未找到明确的中文名称，检查所有名称...")
                for key, name in all_names.items():
                    print(f"  [命名] 检查 {key}: {name}")
                    if AniBKScraper._is_chinese_title(name):
                        chinese_title = name
                        print(f"  [命名] ✓ 识别为中文标题: {chinese_title} (来源: {key})")
                        break
                    else:
                        print(f"  [命名] ✗ 不是中文标题")
            
            # 4. 提取日文名和英文名
            if 'original_name' in all_names:
                japanese_title = all_names['original_name']
                print(f"  [命名] 原版名称: {japanese_title}")
            elif 'japanese_name' in all_names:
                japanese_title = all_names['japanese_name']
                print(f"  [命名] 日文名称: {japanese_title}")
            
            if 'english_name' in all_names:
                english_title = all_names['english_name']
                print(f"  [命名] 英文名称: {english_title}")
        
        # 5. 如果没有找到中文标题，尝试翻译
        # if not chinese_title:
        #     print(f"  [命名] 未找到中文标题，尝试翻译...")
        #     if japanese_title:
        #         print(f"  [命名] 翻译日文名: {japanese_title}")
        #         chinese_title = AniBKScraper._translate_to_chinese(japanese_title, 'ja')
        #         print(f"  [命名] 翻译结果: {chinese_title}")
        #     elif english_title:
        #         print(f"  [命名] 翻译英文名: {english_title}")
        #         chinese_title = AniBKScraper._translate_to_chinese(english_title, 'en')
        #         print(f"  [命名] 翻译结果: {chinese_title}")
        
        # 6. 如果还是没有，使用anime_info.title
        if not chinese_title:
            chinese_title = anime_info.title if anime_info.title else video_info.title
            print(f"  [命名] 使用备用标题: {chinese_title}")
        
        # 7. 如果没有找到日文/英文名，使用anime_info.original_title
        if not japanese_title and not english_title:
            if anime_info.original_title:
                # 判断original_title是日文还是英文
                if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', anime_info.original_title):
                    japanese_title = anime_info.original_title
                    print(f"  [命名] 使用original_title作为日文名: {japanese_title}")
                else:
                    english_title = anime_info.original_title
                    print(f"  [命名] 使用original_title作为英文名: {english_title}")
        
        if not chinese_title:
            print(f"  [命名] ❌ 无法确定中文标题")
            return ''
        
        print(f"  [命名] 最终选择:")
        print(f"  [命名]   中文标题: {chinese_title}")
        print(f"  [命名]   日文名: {japanese_title}")
        print(f"  [命名]   英文名: {english_title}")
        
        parts = []
        
        # 1. 标题部分：中文名[日文名/英文名]
        title_part = chinese_title
        original_name = japanese_title or english_title
        if original_name and original_name != chinese_title:
            title_part = f"{chinese_title}[{original_name}]"
        parts.append(title_part)
        
        # 2. 季度部分
        season = video_info.season or 1
        if season > 1:
            parts.append(f"S{season:02d}")
        
        # 3. 集数部分
        if video_info.episode:
            parts.append(f"E{video_info.episode:02d}")
        else:
            parts.append("EunKown")
        
        # 4. 集数名称部分（如果有）
        if video_info.episode_title:
            # video_info.episode_title = re.sub(r'[^\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]', '', video_info.episode_title)
            parts.append(video_info.episode_title)
        # 5. 分辨率（如果有）
        if video_info.resolution:
            parts.append(video_info.resolution)
        
        # 使用 - 连接各部分
        filename = ' - '.join(parts)
        filename = sanitize_filename(filename)
        print(f"  [命名] 生成的文件名: {filename}{original_ext}")
        
        # 添加扩展名
        return filename + original_ext



# ============================================================================
# AniBK刮削器
# ============================================================================

class AniBKScraper:
    """AniBK番组百科刮削器"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
    
    @staticmethod
    def _has_chinese(text: str) -> bool:
        """检查文本是否包含中文字符"""
        return bool(re.search(r'[\u4e00-\u9fa5]', text))
    
    @staticmethod
    def _is_chinese_title(text: str) -> bool:
        """判断是否为中文标题
        
        规则：
        1. 包含中文字符
        2. 可以夹杂英文、数字、符号
        3. 不能是纯日文（平假名、片假名）
        4. 日文假名数量不能超过中文字符的50%
        5. 如果同时包含汉字和假名，假名比例较高则认为是日文
        """
        if not text:
            return False
        
        # 检查是否包含中文
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)
        if not chinese_chars:
            return False
        
        # 检查是否包含日文假名
        hiragana = re.findall(r'[\u3040-\u309f]', text)  # 平假名
        katakana = re.findall(r'[\u30a0-\u30ff]', text)  # 片假名
        kana_count = len(hiragana) + len(katakana)
        chinese_count = len(chinese_chars)
        
        # 如果有假名，检查比例
        if kana_count > 0:
            # 假名数量超过中文字符的30%，认为是日文标题（更严格的判断）
            if kana_count > chinese_count * 0.3:
                return False
        
        # 额外检查：如果包含片假名，很可能是日文
        if len(katakana) > 0:
            # 如果片假名数量较多，认为是日文
            if len(katakana) >= 2:  # 至少2个片假名字符
                return False
        
        return True
    
    @staticmethod
    def _translate_to_chinese(text: str, source_lang: str = 'ja') -> str:
        """翻译为中文
        
        使用简单的在线翻译API（这里使用Google Translate的免费接口）
        
        Args:
            text: 要翻译的文本
            source_lang: 源语言（'ja'=日语, 'en'=英语）
        
        Returns:
            翻译后的中文文本，如果翻译失败则返回原文
        """
        try:
            # 使用Google Translate的免费接口
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                'client': 'gtx',
                'sl': source_lang,
                'tl': 'zh-CN',
                'dt': 't',
                'q': text
            }
            
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result and len(result) > 0 and len(result[0]) > 0:
                    translated = ''.join([item[0] for item in result[0] if item[0]])
                    return translated
        except Exception as e:
            print(f"  ⚠️  翻译失败: {e}")
        
        return text  # 翻译失败返回原文
    
    def search(self, keyword: str) -> List[Dict]:
        """搜索番剧"""
        try:
            search_url = f"{ANIBK_BASE_URL}/list/---------"
            params = {'order': '20', 'kw': keyword}
            
            print(f"  搜索关键词: {keyword}")
            response = self.session.get(search_url, params=params, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            result_items = soup.find_all('a', href=re.compile(r'/bk/\d+'))
            seen_ids = set()
            
            for item in result_items:
                href = item.get('href', '')
                if not href or '/bk/' not in href:
                    continue
                
                id_match = re.search(r'/bk/(\d+)', href)
                if not id_match:
                    continue
                
                anime_id = id_match.group(1)
                if anime_id in seen_ids:
                    continue
                seen_ids.add(anime_id)
                
                result = {'id': anime_id}
                
                if href.startswith('/'):
                    result['url'] = ANIBK_BASE_URL + href
                else:
                    result['url'] = href
                
                # 提取标题
                title = ''
                img = item.find('img')
                if img and img.get('alt'):
                    title = img['alt'].strip()
                if not title:
                    title = item.text.strip()
                if not title and item.get('title'):
                    title = item['title'].strip()
                
                if title:
                    title = title.replace('【', '').replace('】', '').strip()
                    result['name'] = title
                    result['name_cn'] = title
                    
                    # 尝试快速获取该番剧的所有名称（用于更精确的匹配）
                    # 注意：这会增加网络请求，但能提高匹配准确度
                    try:
                        detail_response = self.session.get(result['url'], timeout=10)
                        detail_response.encoding = 'utf-8'
                        
                        # 提取所有名称
                        all_names = [title]  # 包含主标题
                        
                        # 提取其他名称（修正正则表达式以匹配HTML结构）
                        other_name_match = re.search(r'其他名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', detail_response.text)
                        if other_name_match:
                            other_name = other_name_match.group(1).strip()
                            if other_name:
                                all_names.append(other_name)
                                result['other_name'] = other_name
                        
                        # 提取原版名称（日文）
                        original_name_match = re.search(r'原版名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', detail_response.text)
                        if original_name_match:
                            original_name = original_name_match.group(1).strip()
                            if original_name:
                                all_names.append(original_name)
                                result['original_name'] = original_name
                        
                        # 提取英文名称
                        english_name_match = re.search(r'英文名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', detail_response.text)
                        if english_name_match:
                            english_name = english_name_match.group(1).strip()
                            if english_name:
                                all_names.append(english_name)
                                result['english_name'] = english_name
                        
                        result['all_names'] = all_names
                        
                    except Exception as e:
                        # 如果获取详情失败，只使用主标题
                        result['all_names'] = [title]
                    
                    results.append(result)
                
                if len(results) >= 20:
                    break
            
            return results
            
        except Exception as e:
            print(f"  搜索失败: {e}")
            return []
    
    def scrape_from_url(self, url: str) -> Optional[AnimeInfo]:
        """从URL刮削信息"""
        try:
            print(f"  访问: {url}")
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            soup = BeautifulSoup(response.text, 'html.parser')
            info = AnimeInfo()
            
            # 提取ID
            id_match = re.search(r'/bk/(\d+)', url)
            if id_match:
                info.source_id = id_match.group(1)
            info.source_url = url
            
            # 收集所有可能的标题
            all_titles = {}
            
            # 1. 从页面标题提取
            page_title = soup.select_one('title')
            if page_title:
                title_text = page_title.text.strip()
                title_text = re.sub(r'\s*[-|]\s*(番组百科|动漫科|AniBK).*', '', title_text)
                title_text = title_text.replace('【', '').replace('】', '').strip()
                if title_text:
                    all_titles['page_title'] = title_text
            
            # 2. 从页面内容提取各种名称
            # AniBK网站使用HTML标签，需要处理<span>等标签
            name_patterns = [
                (r'中文名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'chinese_name'),
                (r'原版名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'original_name'),
                (r'英文名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'english_name'),
                (r'其他名称</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'other_name'),
                (r'日文名</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'japanese_name'),
                (r'罗马音</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'romaji_name'),
                (r'别名</span><span[^>]*>：</span><span[^>]*>([^<]+)</span>', 'alias_name'),
            ]
            
            for pattern, key in name_patterns:
                match = re.search(pattern, response.text)
                if match:
                    name = match.group(1).strip()
                    if name:
                        all_titles[key] = name
                        print(f"  ✓ 提取到 {key}: {name}")
                else:
                    print(f"  ✗ 未匹配到 {key}")
            
            print(f"  找到的标题: {all_titles}")
            
            # 保存所有名称到AnimeInfo对象
            info.all_names = all_titles.copy()
            
            # 3. 智能识别中文标题
            chinese_title = None
            japanese_title = None
            english_title = None
            
            # 优先查找"其他名称"（通常是中文）
            if 'other_name' in all_titles:
                other_name = all_titles['other_name']
                if self._is_chinese_title(other_name):
                    chinese_title = other_name
                    print(f"  ✓ 从其他名称找到中文名: {chinese_title}")
            
            # 其次查找明确标注的中文名
            if not chinese_title and 'chinese_name' in all_titles:
                chinese_title = all_titles['chinese_name']
                print(f"  ✓ 找到中文名: {chinese_title}")
            
            # 如果没有明确的中文名，检查所有标题
            if not chinese_title:
                for key, title in all_titles.items():
                    if self._is_chinese_title(title):
                        chinese_title = title
                        print(f"  ✓ 识别为中文标题: {chinese_title} (来源: {key})")
                        break
            
            # 提取日文名和英文名（用于翻译和作为原名）
            # 优先使用"原版名称"（通常是日文）
            if 'original_name' in all_titles:
                japanese_title = all_titles['original_name']
            elif 'japanese_name' in all_titles:
                japanese_title = all_titles['japanese_name']
            
            if 'english_name' in all_titles:
                english_title = all_titles['english_name']
            
            # 如果还是没有中文标题，尝试翻译
            if not chinese_title:
                if japanese_title:
                    print(f"  未找到中文名，尝试翻译日文名: {japanese_title}")
                    chinese_title = self._translate_to_chinese(japanese_title, 'ja')
                    print(f"  ✓ 翻译结果: {chinese_title}")
                elif english_title:
                    print(f"  未找到中文名和日文名，尝试翻译英文名: {english_title}")
                    chinese_title = self._translate_to_chinese(english_title, 'en')
                    print(f"  ✓ 翻译结果: {chinese_title}")
                elif 'page_title' in all_titles:
                    # 最后尝试翻译页面标题
                    page_title_text = all_titles['page_title']
                    if not self._is_chinese_title(page_title_text):
                        print(f"  尝试翻译页面标题: {page_title_text}")
                        chinese_title = self._translate_to_chinese(page_title_text, 'ja')
                        print(f"  ✓ 翻译结果: {chinese_title}")
                    else:
                        chinese_title = page_title_text
            
            # 设置标题
            info.title = chinese_title if chinese_title else all_titles.get('page_title', '')
            
            # 设置原名（优先日文，其次英文）
            if japanese_title and japanese_title != info.title:
                info.original_title = japanese_title
            elif english_title and english_title != info.title:
                info.original_title = english_title
            
            print(f"  最终标题: {info.title}")
            if info.original_title:
                print(f"  原名: {info.original_title}")
            
            # 提取简介
            plot_pattern = r'《.+?》\s*(.+?)(?=标签|PV剧集|正式剧集|$)'
            plot_match = re.search(plot_pattern, response.text, re.DOTALL)
            if plot_match:
                plot_text = plot_match.group(1).strip()
                plot_text = re.sub(r'<[^>]+>', '', plot_text)
                plot_text = re.sub(r'\s+', ' ', plot_text)
                if 10 < len(plot_text) < 1000:
                    info.plot = plot_text
            
            # 提取海报
            # 优先使用XPath指定的位置: /html/body/div[3]/div/div[1]/section/div/div[1]/div/div/a/img
            poster_img = None
            
            # 方法1: 尝试使用CSS选择器定位到指定位置的图片
            try:
                # 对应XPath的CSS选择器
                poster_img = soup.select_one('body > div:nth-of-type(3) > div > div:nth-of-type(1) section img')
                if not poster_img:
                    # 尝试更宽松的选择器
                    poster_img = soup.select_one('section img')
            except Exception:
                pass
            
            # 方法2: 如果上述方法失败，查找所有图片并筛选
            if not poster_img:
                images = soup.find_all('img')
                for img in images:
                    src = img.get('src') or img.get('data-src') or img.get('data-original')
                    if src and ('cover' in src.lower() or 'poster' in src.lower() or 'thumb' in src.lower()):
                        poster_img = img
                        break
                
                # 如果还是没找到，使用第一张图片（如果图片数量较少）
                if not poster_img and images and len(images) < 5:
                    poster_img = images[0]
            
            # 提取海报URL
            if poster_img:
                src = poster_img.get('src') or poster_img.get('data-src') or poster_img.get('data-original')
                if src:
                    if src.startswith('//'):
                        info.poster_url = 'https:' + src
                    elif src.startswith('/'):
                        info.poster_url = ANIBK_BASE_URL + src
                    elif src.startswith('http'):
                        info.poster_url = src
                    
                    if info.poster_url:
                        info.fanart_url = info.poster_url
                        print(f"  ✓ 找到海报: {info.poster_url}")
            
            # 提取集数
            episode_pattern = r'第(\d+)话'
            episodes = re.findall(episode_pattern, response.text)
            if episodes:
                info.episodes_total = max([int(ep) for ep in episodes])
            
            # 提取年份
            year_match = re.search(r'\b(20\d{2})\b', response.text)
            if year_match:
                info.year = int(year_match.group(1))
            
            # 提取标签
            tags_pattern = r'标签\s*(.+?)(?=PV剧集|正式剧集|扩展剧集|$)'
            tags_match = re.search(tags_pattern, response.text, re.DOTALL)
            if tags_match:
                tags_text = tags_match.group(1).strip()
                tags = re.findall(r'[\u4e00-\u9fa5]+', tags_text)
                if tags:
                    info.genres = tags[:5]
            
            return info
            
        except Exception as e:
            print(f"  刮削失败: {e}")
            return None
    
    def get_episode_title(self, url: str, episode_num: int) -> str:
        """获取特定集数的标题
        
        Args:
            url: 番剧URL
            episode_num: 集数
            
        Returns:
            集数标题，如果未找到则返回空字符串
        """
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            # 尝试匹配集数标题的多种格式
            patterns = [
                rf'第{episode_num}话[：:\s]+([^\n<]+)',
                rf'第{episode_num}集[：:\s]+([^\n<]+)',
                rf'EP{episode_num:02d}[：:\s]+([^\n<]+)',
                rf'E{episode_num:02d}[：:\s]+([^\n<]+)',
            ]
            soup = BeautifulSoup(response.text, 'html.parser')
            # 找到所有 <ul class="ep-list">
            ul_lists = soup.find_all('ul', class_='ep-list')

            for ul in ul_lists:
                # 找到所有 li
                for li in ul.find_all('li'):
                    # 找到 a 标签
                    a_tag = li.find('a', title=True)
                    if a_tag:
                        title = a_tag['title']
                        # 尝试匹配所有模式
                        for pattern in patterns:
                            match = re.search(pattern, title)
                            if match:
                                return title

            return ""

            # print(response.text)
            # for pattern in patterns:
            #     match = re.search(pattern, response.text)
            #     if match:
            #         title = match.group(1).strip()
            #         # 清理标题
            #         title = re.sub(r'<[^>]+>', '', title)
            #         title = re.sub(r'\s+', ' ', title)
            #         title = title.split('\n')[0].strip()
            #         if title and len(title) < 100:
            #             return title
            #
            # return ""
            
        except Exception as e:
            return ""


# ============================================================================
# 智能匹配器
# ============================================================================

class SmartMatcher:
    """智能匹配器
    
    核心功能：
    1. 语言检测：自动识别中文、日文文本
    2. 相似度计算：计算两个标题的相似度
    3. 跨语言匹配：当搜索关键词和结果语言不匹配时，自动查找对应语言的名称
    4. 假设匹配验证：语言不匹配时假设可能匹配，从详情页面验证
    
    v1.9.2 核心改进：
    - 搜索阶段访问详情页面，提取other_name、original_name、english_name
    - 匹配阶段检测语言，如果不匹配则从详情字段查找对应语言名称
    - 找到对应语言名称后，直接使用验证后的相似度（不受初始相似度影响）
    """
    
    # 匹配度阈值
    MIN_SIMILARITY_THRESHOLD = 0.3      # 最低匹配度50%
    GOOD_SIMILARITY_THRESHOLD = 0.7     # 良好匹配度70%
    EXCELLENT_SIMILARITY_THRESHOLD = 0.9 # 优秀匹配度90%
    
    @staticmethod
    def find_best_match(keyword: str, results: List[Dict], video_info: Optional['VideoInfo'] = None) -> Optional[Dict]:
        """找到最匹配的结果（核心匹配算法）
        
        工作流程：
        1. 遍历所有搜索结果，计算与关键词的相似度
        2. 检测关键词和结果的语言（中文/日文）
        3. 如果语言不匹配，从result的详情字段中查找对应语言的名称
        4. 使用对应语言的名称重新计算相似度（假设匹配验证逻辑）
        5. 根据视频信息调整匹配度（季度、特殊类型等）
        6. 返回相似度最高且超过阈值的结果
        
        Args:
            keyword: 搜索关键词
            results: 搜索结果列表（每个result包含name、other_name、original_name等字段）
            video_info: 视频信息（可选，用于更精确的匹配）
        
        Returns:
            包含最佳匹配结果、相似度和所有候选的字典，如果没有找到则返回None
            
        v1.9.2 核心改进：
        - 搜索阶段已经访问详情页面，result中包含other_name、original_name、english_name
        - 语言不匹配时，从这些字段中查找对应语言的名称
        - 找到后直接使用验证后的相似度，不受初始相似度影响
        """
        if not results:
            return None
        
        # 清理关键词并检测语言
        clean_keyword = SmartMatcher._clean_title(keyword)
        keyword_is_chinese = SmartMatcher._is_chinese_text(keyword)
        keyword_is_japanese = SmartMatcher._is_japanese_text(keyword)
        
        all_matches = []
        
        print(f"\n  匹配分析:")
        print(f"  搜索关键词: {keyword}")
        print(f"  清理后: {clean_keyword}")
        print(f"  关键词语言: {'中文' if keyword_is_chinese else '日文' if keyword_is_japanese else '其他'}")
        
        # ========== 遍历所有搜索结果 ==========
        for result in results:
            # 获取所有可能的名称
            all_names = result.get('all_names', [])
            if not all_names:
                # 如果没有all_names，使用传统方式
                name = result.get('name_cn') or result.get('name', '')
                if name:
                    all_names = [name]
            
            if not all_names:
                continue
            
            # ========== 计算初始相似度 ==========
            # 与所有名称比较，取最高值
            max_similarity = 0.0
            best_matching_name = all_names[0] if isinstance(all_names, list) else str(all_names)
            
            for name in all_names:
                clean_name = SmartMatcher._clean_title(name)
                similarity = SmartMatcher._calculate_similarity(clean_keyword, clean_name)
                
                if similarity > max_similarity:
                    max_similarity = similarity
                    best_matching_name = name
            
            # ========== 语言匹配验证（v1.9.2核心逻辑） ==========
            result_name_is_chinese = SmartMatcher._is_chinese_text(best_matching_name)
            result_name_is_japanese = SmartMatcher._is_japanese_text(best_matching_name)
            
            # 场景1：搜索用中文，结果是日文
            if keyword_is_chinese and not result_name_is_chinese:
                print(f"  [语言不匹配] 搜索用中文，结果是日文: {best_matching_name}")
                print(f"  [假设匹配] 从详情页面查找中文名称进行验证")
                
                # 从result的字段中查找中文名称
                chinese_name = None
                
                # 优先级：other_name > chinese_name > name_cn
                for field_name in ['other_name', 'chinese_name', 'name_cn']:
                    if field_name in result:
                        field_value = result[field_name]
                        if field_value and SmartMatcher._is_chinese_text(field_value):
                            chinese_name = field_value
                            print(f"  [找到中文名] 在 {field_name} 字段: {chinese_name}")
                            break
                
                # 如果还没找到，遍历all_names列表
                if not chinese_name and isinstance(all_names, list):
                    for name in all_names:
                        if isinstance(name, str) and SmartMatcher._is_chinese_text(name):
                            chinese_name = name
                            print(f"  [找到中文名] 在 all_names 列表: {chinese_name}")
                            break
                
                if chinese_name:
                    # 使用中文名称重新计算相似度
                    clean_chinese = SmartMatcher._clean_title(chinese_name)
                    chinese_similarity = SmartMatcher._calculate_similarity(clean_keyword, clean_chinese)
                    print(f"  [验证匹配] 中文名称相似度: {chinese_similarity:.1%}")
                    
                    # 直接使用验证后的相似度（不受初始相似度影响）
                    max_similarity = chinese_similarity
                    best_matching_name = chinese_name
                else:
                    print(f"  [未找到中文名] 无法验证匹配，保持原匹配度")
            
            # 场景2：搜索用日文，结果是中文
            elif keyword_is_japanese and not result_name_is_japanese:
                print(f"  [语言不匹配] 搜索用日文，结果是中文: {best_matching_name}")
                print(f"  [假设匹配] 从详情页面查找日文名称进行验证")
                
                # 从result的字段中查找日文名称
                japanese_name = None
                
                # 优先级：original_name > japanese_name
                for field_name in ['original_name', 'japanese_name']:
                    if field_name in result:
                        field_value = result[field_name]
                        if field_value and SmartMatcher._is_japanese_text(field_value):
                            japanese_name = field_value
                            print(f"  [找到日文名] 在 {field_name} 字段: {japanese_name}")
                            break
                
                # 如果还没找到，遍历all_names列表
                if not japanese_name and isinstance(all_names, list):
                    for name in all_names:
                        if isinstance(name, str) and SmartMatcher._is_japanese_text(name):
                            japanese_name = name
                            print(f"  [找到日文名] 在 all_names 列表: {japanese_name}")
                            break
                
                if japanese_name:
                    # 使用日文名称重新计算相似度
                    clean_japanese = SmartMatcher._clean_title(japanese_name)
                    japanese_similarity = SmartMatcher._calculate_similarity(clean_keyword, clean_japanese)
                    print(f"  [验证匹配] 日文名称相似度: {japanese_similarity:.1%}")
                    
                    # 直接使用验证后的相似度
                    max_similarity = japanese_similarity
                    best_matching_name = japanese_name
                else:
                    print(f"  [未找到日文名] 无法验证匹配，保持原匹配度")
            
            # 使用最终相似度
            similarity = max_similarity
            
            # ========== 根据视频信息调整匹配度 ==========
            is_derivative = SmartMatcher._is_derivative_work(best_matching_name, keyword)
            
            if video_info:
                # 如果视频是续集，但搜索结果是主系列，降低优先级
                if video_info.season and video_info.season > 1:
                    if not SmartMatcher._has_season_info(best_matching_name):
                        similarity *= 0.8
                
                # 如果视频是特殊类型（OVA等），优先匹配相同类型
                if video_info.special_type:
                    if SmartMatcher._has_special_type(best_matching_name, video_info.special_type):
                        similarity *= 1.1  # 提高匹配度
            
            # 降低衍生作品优先级（如果搜索关键词中不包含衍生词）
            if is_derivative:
                similarity *= 0.7
            
            all_matches.append({
                'result': result,
                'similarity': similarity,
                'is_derivative': is_derivative,
                'name': best_matching_name,
                'all_names': all_names
            })
        
        # ========== 排序并显示结果 ==========
        all_matches.sort(key=lambda x: x['similarity'], reverse=True)
        
        print(f"\n  匹配结果 (共{len(all_matches)}个):")
        for i, match in enumerate(all_matches[:5], 1):
            # 评价相似度
            if match['similarity'] >= SmartMatcher.EXCELLENT_SIMILARITY_THRESHOLD:
                status = "优秀"
            elif match['similarity'] >= SmartMatcher.GOOD_SIMILARITY_THRESHOLD:
                status = "良好"
            elif match['similarity'] >= SmartMatcher.MIN_SIMILARITY_THRESHOLD:
                status = "可接受"
            else:
                status = "较低"
            
            derivative_mark = " [衍生]" if match['is_derivative'] else ""
            print(f"    {i}. {match['name']}{derivative_mark}")
            
            # 显示其他名称
            if len(match['all_names']) > 1:
                other_names = ', '.join(str(n) for n in match['all_names'][1:3])  # 最多显示2个
                print(f"       其他名称: {other_names}")
            
            print(f"       相似度: {match['similarity']:.1%} ({status})")
        
        # ========== 返回最佳匹配 ==========
        best_match = all_matches[0] if all_matches else None
        
        if not best_match:
            return None
        
        # 检查匹配度是否达到最低阈值
        if best_match['similarity'] < SmartMatcher.MIN_SIMILARITY_THRESHOLD:
            print(f"\n  ❌ 匹配失败: 最高相似度 {best_match['similarity']:.1%} 低于阈值 {SmartMatcher.MIN_SIMILARITY_THRESHOLD:.1%}")
            print(f"  建议: 请检查文件名是否正确，或手动指定番剧URL")
            return None
        
        return {
            'result': best_match['result'],
            'similarity': best_match['similarity'],
            'all_matches': all_matches[:5]  # 返回前5个候选
        }
    
    @staticmethod
    def _is_chinese_text(text: str) -> bool:
        """检测文本是否为中文
        
        判断规则：
        1. 必须包含中文字符（汉字）
        2. 假名（平假名+片假名）数量不超过中文字符的30%
        3. 如果片假名数量>=2，认为是日文
        
        Args:
            text: 待检测的文本
            
        Returns:
            True表示中文，False表示非中文
            
        示例：
            "我推的孩子" -> True
            "推しの子" -> False (包含假名)
            "進撃の巨人" -> False (包含假名)
        """
        if not text:
            return False
        
        # 统计各类字符数量
        chinese_chars = re.findall(r'[\u4e00-\u9fa5]', text)  # 中文汉字
        hiragana = re.findall(r'[\u3040-\u309f]', text)       # 平假名
        katakana = re.findall(r'[\u30a0-\u30ff]', text)       # 片假名
        
        if not chinese_chars:
            return False
        
        # 检查假名比例
        kana_count = len(hiragana) + len(katakana)
        chinese_count = len(chinese_chars)
        
        # 假名数量不超过中文字符的30%
        if kana_count > 0 and kana_count > chinese_count * 0.3:
            return False
        
        return True
    
    @staticmethod
    def _is_japanese_text(text: str) -> bool:
        """检测文本是否为日文
        
        判断规则：
        包含假名（平假名或片假名）即认为是日文
        
        Args:
            text: 待检测的文本
            
        Returns:
            True表示日文，False表示非日文
            
        示例：
            "推しの子" -> True
            "我推的孩子" -> False
        """
        if not text:
            return False
        
        # 检查是否包含假名
        hiragana = re.findall(r'[\u3040-\u309f]', text)  # 平假名
        katakana = re.findall(r'[\u30a0-\u30ff]', text)  # 片假名
        
        # 如果包含假名，认为是日文
        if hiragana or katakana:
            return True
        
        return False
    
    @staticmethod
    def _find_chinese_name_from_all_names(all_names: List[str]) -> Optional[str]:
        """从所有名称中找到中文名称
        
        优先级：
        1. 明确标注为中文的名称
        2. 检测为中文的名称
        """
        if not all_names:
            return None
        
        # 如果all_names是字典（从result.get('all_names')获取）
        if isinstance(all_names, dict):
            # 优先查找明确标注的中文名
            if 'chinese_name' in all_names:
                return all_names['chinese_name']
            if 'other_name' in all_names:
                other_name = all_names['other_name']
                if SmartMatcher._is_chinese_text(other_name):
                    return other_name
            
            # 遍历所有名称，找中文
            for key, name in all_names.items():
                if SmartMatcher._is_chinese_text(name):
                    return name
        
        # 如果all_names是列表
        elif isinstance(all_names, list):
            for name in all_names:
                if SmartMatcher._is_chinese_text(name):
                    return name
        
        return None
    
    @staticmethod
    def _find_japanese_name_from_all_names(all_names: List[str]) -> Optional[str]:
        """从所有名称中找到日文名称
        
        优先级：
        1. 明确标注为日文的名称
        2. 明确标注为原版名称的
        3. 检测为日文的名称
        """
        if not all_names:
            return None
        
        # 如果all_names是字典
        if isinstance(all_names, dict):
            # 优先查找明确标注的日文名
            if 'japanese_name' in all_names:
                return all_names['japanese_name']
            if 'original_name' in all_names:
                original_name = all_names['original_name']
                if SmartMatcher._is_japanese_text(original_name):
                    return original_name
            
            # 遍历所有名称，找日文
            for key, name in all_names.items():
                if SmartMatcher._is_japanese_text(name):
                    return name
        
        # 如果all_names是列表
        elif isinstance(all_names, list):
            for name in all_names:
                if SmartMatcher._is_japanese_text(name):
                    return name
        
        return None
    
    @staticmethod
    def _clean_title(title: str) -> str:
        """清理标题"""
        title = re.sub(r'[【】\[\]()（）\s\-_・]', '', title)
        return title.lower()
    
    @staticmethod
    def _calculate_similarity(str1: str, str2: str) -> float:
        """计算相似度"""
        if not str1 or not str2:
            return 0.0
        
        if str1 == str2:
            return 1.0
        
        if str1 in str2:
            return 0.9
        if str2 in str1:
            return 0.85
        
        longer = str1 if len(str1) > len(str2) else str2
        shorter = str2 if len(str1) > len(str2) else str1
        
        max_common = 0
        for i in range(len(shorter)):
            for j in range(i + 1, len(shorter) + 1):
                substr = shorter[i:j]
                if substr in longer and len(substr) > max_common:
                    max_common = len(substr)
        
        return max_common / len(longer) if longer else 0
    
    @staticmethod
    def _is_derivative_work(title: str, keyword: str) -> bool:
        """判断是否为衍生作品"""
        derivative_keywords = [
            '第二季', '第三季', '第四季', '第五季', '第六季',
            '第2季', '第3季', '第4季', '第5季', '第6季',
            'season 2', 'season 3', 'season 4', 'season 5',
            '剧场版', '电影版', '总集篇', '特别篇',
            'ova', 'oad', 'ona', 'sp', 'special',
            '前篇', '后篇', '完结篇', '最终季', '最终章',
            '番外', 'extra'
        ]
        
        title_lower = title.lower()
        keyword_lower = keyword.lower()
        
        for dk in derivative_keywords:
            if dk in title_lower and dk not in keyword_lower:
                return True
        
        return False
    
    @staticmethod
    def _has_season_info(title: str) -> bool:
        """检查标题是否包含季度信息"""
        season_patterns = [
            r'第[二三四五六七八九十\d]+季',
            r'Season\s*[2-9]',
            r'[2-9]期',
        ]
        for pattern in season_patterns:
            if re.search(pattern, title, re.IGNORECASE):
                return True
        return False
    
    @staticmethod
    def _has_special_type(title: str, special_type: str) -> bool:
        """检查标题是否包含特殊类型"""
        type_map = {
            'OVA': r'\b(OVA|OAD|ONA)\b',
            'SP': r'\b(SP|Special|特别篇)\b',
            '剧场版': r'(剧场版|电影版|Movie)',
            '番外': r'(番外|Extra)',
            '总集篇': r'(总集篇|Recap)',
        }
        
        pattern = type_map.get(special_type)
        if pattern:
            return bool(re.search(pattern, title, re.IGNORECASE))
        return False


# ============================================================================
# NFO生成器
# ============================================================================
        for dk in derivative_keywords:
            if dk in title_lower and dk not in keyword_lower:
                return True
        
        return False


# ============================================================================
# NFO生成器
# ============================================================================

class NFOGenerator:
    """生成NFO文件"""
    
    @staticmethod
    def generate_tvshow_nfo(info: AnimeInfo) -> str:
        """生成剧集NFO"""
        root = ET.Element('tvshow')
        
        if info.title:
            ET.SubElement(root, 'title').text = info.title
        if info.original_title:
            ET.SubElement(root, 'originaltitle').text = info.original_title
        if info.plot:
            ET.SubElement(root, 'plot').text = info.plot
        if info.year:
            ET.SubElement(root, 'year').text = str(info.year)
        if info.premiered:
            ET.SubElement(root, 'premiered').text = info.premiered
        if info.rating:
            ratings = ET.SubElement(root, 'ratings')
            rating = ET.SubElement(ratings, 'rating', name='default', max='10', default='true')
            ET.SubElement(rating, 'value').text = str(info.rating)
        if info.studio:
            ET.SubElement(root, 'studio').text = info.studio
        
        for genre in info.genres:
            ET.SubElement(root, 'genre').text = genre
        
        for tag in info.tags:
            ET.SubElement(root, 'tag').text = tag
        
        if info.poster_url:
            thumb = ET.SubElement(root, 'thumb', aspect='poster')
            thumb.text = info.poster_url
        
        if info.fanart_url:
            fanart = ET.SubElement(root, 'fanart')
            thumb = ET.SubElement(fanart, 'thumb')
            thumb.text = info.fanart_url
        
        if info.source_url:
            uniqueid = ET.SubElement(root, 'uniqueid', type='anibk', default='true')
            uniqueid.text = info.source_id
        
        return NFOGenerator._prettify_xml(root)
    
    @staticmethod
    def generate_episode_nfo(info: AnimeInfo, episode: int, season: int = 1, source_file: str = None) -> str:
        """生成单集NFO
        
        Args:
            info: 番剧信息
            episode: 集数
            season: 季度
            source_file: 源文件路径（用于错误恢复）
        """
        root = ET.Element('episodedetails')
        
        ET.SubElement(root, 'title').text = f"{info.title} - 第{episode}集"
        ET.SubElement(root, 'showtitle').text = info.title
        ET.SubElement(root, 'season').text = str(season)
        ET.SubElement(root, 'episode').text = str(episode)
        
        if info.plot:
            ET.SubElement(root, 'plot').text = info.plot
        
        if info.premiered:
            ET.SubElement(root, 'aired').text = info.premiered
        
        if info.rating:
            ratings = ET.SubElement(root, 'ratings')
            rating = ET.SubElement(ratings, 'rating', name='default', max='10', default='true')
            ET.SubElement(rating, 'value').text = str(info.rating)
        
        if info.poster_url:
            thumb = ET.SubElement(root, 'thumb')
            thumb.text = info.poster_url
        
        # 添加源文件信息（用于错误恢复）
        if source_file:
            source_info = ET.SubElement(root, 'source_file_info')
            ET.SubElement(source_info, 'original_path').text = source_file
            ET.SubElement(source_info, 'original_filename').text = Path(source_file).name
        
        return NFOGenerator._prettify_xml(root)
    
    @staticmethod
    def _prettify_xml(elem: ET.Element) -> str:
        """格式化XML"""
        rough_string = ET.tostring(elem, encoding='utf-8')
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent='  ', encoding='utf-8').decode('utf-8')


# ============================================================================
# 主整理器
# ============================================================================

class AnimeAutoOrganizer:
    """番剧自动整理器"""
    
    def __init__(self, output_dir: str = "output", use_cache: bool = False, cache_dir: str = ".cache"):
        self.scraper = AniBKScraper()
        self.matcher = SmartMatcher()
        self.nfo_generator = NFOGenerator()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # 缓存设置
        self.use_cache = use_cache
        self.cache_dir = Path(cache_dir)
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.anime_cache_file = self.cache_dir / "anime_cache.json"
            self.episode_cache_file = self.cache_dir / "episode_cache.json"
            self.anime_cache = self._load_anime_cache()
            self.episode_cache = self._load_episode_cache()
            print(f"  ℹ️  缓存已启用:")
            print(f"      番剧缓存: {self.anime_cache_file}")
            print(f"      集数缓存: {self.episode_cache_file}")
        else:
            self.anime_cache = {}
            self.episode_cache = {}
            self.anime_cache_file = None
            self.episode_cache_file = None
    
    def _load_anime_cache(self) -> dict:
        """加载番剧缓存"""
        if self.anime_cache_file and self.anime_cache_file.exists():
            try:
                with open(self.anime_cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    print(f"  ✓ 加载番剧缓存: {len(cache)} 个番剧")
                    return cache
            except Exception as e:
                print(f"  ⚠️  加载番剧缓存失败: {e}")
                return {}
        return {}
    
    def _load_episode_cache(self) -> dict:
        """加载集数缓存"""
        if self.episode_cache_file and self.episode_cache_file.exists():
            try:
                with open(self.episode_cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    print(f"  ✓ 加载集数缓存: {len(cache)} 个集数")
                    return cache
            except Exception as e:
                print(f"  ⚠️  加载集数缓存失败: {e}")
                return {}
        return {}
    
    def _save_anime_cache(self):
        """保存番剧缓存"""
        if self.use_cache and self.anime_cache_file:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with open(self.anime_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.anime_cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"  ⚠️  保存番剧缓存失败: {e}")
    
    def _save_episode_cache(self):
        """保存集数缓存"""
        if self.use_cache and self.episode_cache_file:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                with open(self.episode_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(self.episode_cache, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"  ⚠️  保存集数缓存失败: {e}")
    
    def clear_cache(self):
        """清除缓存"""
        print(f"  正在清除缓存...")
        self.anime_cache = {}
        self.episode_cache = {}
        
        if self.anime_cache_file and self.anime_cache_file.exists():
            try:
                self.anime_cache_file.unlink()
                print(f"  ✓ 番剧缓存文件已删除: {self.anime_cache_file}")
            except Exception as e:
                print(f"  ⚠️  删除番剧缓存文件失败: {e}")
        
        if self.episode_cache_file and self.episode_cache_file.exists():
            try:
                self.episode_cache_file.unlink()
                print(f"  ✓ 集数缓存文件已删除: {self.episode_cache_file}")
            except Exception as e:
                print(f"  ⚠️  删除集数缓存文件失败: {e}")
        
        print(f"  ✓ 缓存已清除")
    
    def _get_anime_cache_key(self, search_title: str) -> str:
        """生成番剧缓存键"""
        # 清理标题作为键
        clean = re.sub(r'[【】\[\]()（）\s\-_・]', '', search_title).lower()
        return clean
    
    def _is_anime_cached(self, search_title: str) -> bool:
        """检查番剧是否已缓存"""
        if not self.use_cache:
            return False
        cache_key = self._get_anime_cache_key(search_title)
        return cache_key in self.anime_cache
    
    def _get_anime_from_cache(self, search_title: str) -> Optional[AnimeInfo]:
        """从缓存获取番剧信息"""
        if not self.use_cache:
            return None
        
        cache_key = self._get_anime_cache_key(search_title)
        cached_data = self.anime_cache.get(cache_key)
        
        if not cached_data:
            return None
        
        # 从缓存数据重建AnimeInfo对象
        anime_info = AnimeInfo()
        anime_info.title = cached_data.get('title', '')
        anime_info.original_title = cached_data.get('original_title', '')
        anime_info.year = cached_data.get('year')
        anime_info.plot = cached_data.get('plot', '')
        anime_info.rating = cached_data.get('rating')
        anime_info.genres = cached_data.get('genres', [])
        anime_info.studio = cached_data.get('studio', '')
        anime_info.premiered = cached_data.get('premiered', '')
        anime_info.episodes_total = cached_data.get('episodes_total')
        anime_info.poster_url = cached_data.get('poster_url', '')
        anime_info.fanart_url = cached_data.get('fanart_url', '')
        anime_info.tags = cached_data.get('tags', [])
        anime_info.source_url = cached_data.get('source_url', '')
        anime_info.source_id = cached_data.get('source_id', '')
        anime_info.all_names = cached_data.get('all_names', {})
        
        return anime_info
    
    def _add_anime_to_cache(self, search_title: str, anime_info: AnimeInfo):
        """添加番剧到缓存"""
        if not self.use_cache:
            return
        
        cache_key = self._get_anime_cache_key(search_title)
        
        # 将AnimeInfo对象转换为可序列化的字典
        import datetime
        cached_data = {
            'title': anime_info.title,
            'original_title': anime_info.original_title,
            'year': anime_info.year,
            'plot': anime_info.plot,
            'rating': anime_info.rating,
            'genres': anime_info.genres,
            'studio': anime_info.studio,
            'premiered': anime_info.premiered,
            'episodes_total': anime_info.episodes_total,
            'poster_url': anime_info.poster_url,
            'fanart_url': anime_info.fanart_url,
            'tags': anime_info.tags,
            'source_url': anime_info.source_url,
            'source_id': anime_info.source_id,
            'all_names': anime_info.all_names if hasattr(anime_info, 'all_names') else {},
            'cached_at': datetime.datetime.now().isoformat(),
            'search_title': search_title
        }
        
        self.anime_cache[cache_key] = cached_data
        self._save_anime_cache()
        print(f"  ✓ 已缓存番剧: {anime_info.title}")
    
    def _get_episode_cache_key(self, anime_id: str, episode: int) -> str:
        """生成集数缓存键"""
        return f"{anime_id}_E{episode:02d}"
    
    def _is_episode_cached(self, anime_id: str, episode: int) -> bool:
        """检查集数是否已缓存"""
        if not self.use_cache:
            return False
        cache_key = self._get_episode_cache_key(anime_id, episode)
        return cache_key in self.episode_cache
    
    def _add_episode_to_cache(self, anime_id: str, episode: int, episode_title: str = ""):
        """添加集数到缓存"""
        if not self.use_cache:
            return
        
        cache_key = self._get_episode_cache_key(anime_id, episode)
        import datetime
        self.episode_cache[cache_key] = {
            'anime_id': anime_id,
            'episode': episode,
            'episode_title': episode_title,
            'cached_at': datetime.datetime.now().isoformat()
        }
        self._save_episode_cache()
    
    def _get_episode_from_cache(self, anime_id: str, episode: int) -> dict:
        """从缓存获取集数信息"""
        if not self.use_cache:
            return {}
        cache_key = self._get_episode_cache_key(anime_id, episode)
        return self.episode_cache.get(cache_key, {})
    
    def process(self, input_path: str, generate_episode_nfo: bool = True, auto_group: bool = True) -> bool:
        """处理输入路径（文件夹或单个文件）"""
        input_path = Path(input_path)
        
        if not input_path.exists():
            print(f"❌ 路径不存在: {input_path}")
            return False
        
        print("\n" + "="*80)
        print("番剧自动整理工具 v1.9.3")
        print("="*80 + "\n")
        
        # 收集视频文件（递归扫描所有子文件夹）
        video_files = []
        if input_path.is_file():
            if input_path.suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(input_path)
            else:
                print(f"❌ 不支持的文件格式: {input_path.suffix}")
                return False
        else:
            # 递归扫描所有子文件夹
            print(f"📁 递归扫描文件夹: {input_path}")
            print(f"   正在查找所有视频文件...")
            
            for file_path in input_path.rglob('*'):
                if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS:
                    video_files.append(file_path)
            
            # 显示扫描结果
            if video_files:
                # 统计各个子文件夹的视频数量
                folder_stats = {}
                for video_file in video_files:
                    folder = video_file.parent
                    folder_name = folder.relative_to(input_path) if folder != input_path else Path('.')
                    folder_stats[str(folder_name)] = folder_stats.get(str(folder_name), 0) + 1
                
                print(f"\n   找到 {len(video_files)} 个视频文件，分布在 {len(folder_stats)} 个文件夹中:")
                for folder_name, count in sorted(folder_stats.items()):
                    print(f"     • {folder_name}: {count} 个文件")


        if not video_files:
            print("❌ 未找到视频文件")
            return False
        
        print(f"✓ 找到 {len(video_files)} 个视频文件\n")
        
        # 对每个视频文件进行刮削，按番剧分组
        print(f"� 开始刮削每个视频文件...")
        print("="*80)
        
        anime_groups = {}  # {anime_id: {'anime_info': AnimeInfo, 'videos': [(video_file, video_info)]}}
        failed_files = []
        folder_anime_cache = {}  # 缓存每个文件夹的100%匹配番剧信息 {folder_path: (anime_info, anime_id, similarity)}
        
        for idx, video_file in enumerate(sorted(video_files), 1):
            print(f"\n[{idx}/{len(video_files)}] 📹 处理文件: {video_file.name}")
            print("-"*80)
            
            # 获取当前文件所在的文件夹
            current_folder = video_file.parent
            
            # 检查当前文件夹是否已有100%匹配的番剧
            if current_folder in folder_anime_cache:
                cached_anime_info, cached_anime_id, cached_similarity = folder_anime_cache[current_folder]
                print(f"  ✓ 文件夹已有100%匹配番剧: {cached_anime_info.title}")
                print(f"    直接归入该番剧（匹配度: {cached_similarity:.1%}）")
                
                # 解析视频文件名（仅提取集数等信息）
                video_info = VideoFileParser.parse_filename(video_file.name)
                # video_info.episode_title = anime_info.name_other
                # 显示提取的信息
                print(f"  提取信息:")
                if video_info.episode:
                    print(f"    集数: 第{video_info.episode}集")
                
                # 直接归入缓存的番剧
                if cached_anime_id not in anime_groups:
                    anime_groups[cached_anime_id] = {
                        'anime_info': cached_anime_info,
                        'videos': []
                    }
                
                anime_groups[cached_anime_id]['videos'].append((video_file, video_info))
                continue
            
            # 解析视频文件名
            video_info = VideoFileParser.parse_filename(video_file.name)
            
            # 显示提取的信息
            print(f"  提取信息:")
            print(f"    标题: {video_info.title}")
            if video_info.clean_title != video_info.title:
                print(f"    搜索标题: {video_info.clean_title}")
            if video_info.season:
                print(f"    季度: 第{video_info.season}季")
            if video_info.episode:
                print(f"    集数: 第{video_info.episode}集")

            # 检查番剧缓存
            search_title = video_info.clean_title if video_info.clean_title else video_info.title
            anime_info = None
            match_similarity = 0.0
            print(f"===================={search_title}")
            if self._is_anime_cached(search_title):
                print(f"  ✓ 从缓存加载番剧信息")
                anime_info = self._get_anime_from_cache(search_title)
                if anime_info:
                    print(f"    番剧: {anime_info.title}")
                    # 从缓存加载的默认为100%匹配
                    match_similarity = 1.0
            
            # 如果缓存中没有，进行刮削
            if not anime_info:
                print(f"  🔍 刮削番剧信息...")
                resultsimilarity = self._search_and_scrape_with_similarity(search_title, video_info, video_file.name)
                if resultsimilarity is None:
                    print(f"  ❌ 刮削失败，跳过此文件")
                    # 处理失败情况，比如跳过或使用默认值
                    anime_info, match_similarity = None, 0.0
                    continue
                else:
                    anime_info, match_similarity = resultsimilarity
                    # 添加到缓存
                    self._add_anime_to_cache(search_title, anime_info)

                # if self._search_and_scrape_with_similarity(search_title, video_info, video_file.name) is None:
                #     print(f"  ❌ 刮削失败，跳过此文件")
                #     failed_files.append(video_file.name)
                #     continue
                # else:
                #     anime_info, match_similarity = self._search_and_scrape_with_similarity(search_title, video_info, video_file.name)
                #     # 添加到缓存
                #     self._add_anime_to_cache(search_title, anime_info)

            #     # if anime_info:
            #
            #
            # if not anime_info:

            
            # 使用番剧ID作为分组键
            anime_id = anime_info.source_id
            if not anime_id:
                # 如果没有ID，使用标题作为键
                anime_id = anime_info.title
            
            # 如果匹配度达到100%，缓存该文件夹的番剧信息
            if match_similarity >= 1.0:
                folder_anime_cache[current_folder] = (anime_info, anime_id, match_similarity)
                print(f"  ✓ 检测到100%匹配！该文件夹及子文件夹的所有文件将归入此番剧")
            
            # 添加到对应的番剧组
            if anime_id not in anime_groups:
                anime_groups[anime_id] = {
                    'anime_info': anime_info,
                    'videos': []
                }
                print(f"  ✓ 识别为新番剧: {anime_info.title}")
            else:
                print(f"  ✓ 归入已识别番剧: {anime_info.title}")
            
            anime_groups[anime_id]['videos'].append((video_file, video_info))
        
        # 显示分组结果
        print(f"\n" + "="*80)
        print(f"📊 分组结果:")
        print("="*80)
        print(f"  共识别 {len(anime_groups)} 个番剧")
        for anime_id, group in anime_groups.items():
            anime_info = group['anime_info']
            video_count = len(group['videos'])
            print(f"  • {anime_info.title}: {video_count} 个视频")
        
        if failed_files:
            print(f"\n  ⚠️  {len(failed_files)} 个文件刮削失败:")
            for filename in failed_files:
                print(f"    - {filename}")
        
        # 处理每个番剧组
        print(f"\n" + "="*80)
        print(f"📝 开始整理文件...")
        print("="*80)
        
        for anime_id, group in anime_groups.items():
            anime_info = group['anime_info']
            videos = group['videos']
            
            print(f"\n处理番剧: {anime_info.title} ({len(videos)} 个视频)")
            print("-"*80)
            
            # 创建番剧专属文件夹
            anime_folder_name = self._sanitize_folder_name(anime_info.title)
            anime_output_dir = self.output_dir / anime_folder_name
            anime_output_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"  输出目录: {anime_output_dir.name}")
            
            processed_files = []
            
            # 处理该番剧的所有视频
            for video_file, video_info in sorted(videos, key=lambda x: x[1].episode or 0):
                # 检查缓存并获取集数标题
                if anime_info.source_id:
                    if video_info.episode:
                        if self._is_episode_cached(anime_info.source_id, video_info.episode):
                            cached_data = self._get_episode_from_cache(anime_info.source_id, video_info.episode)
                            if cached_data.get('episode_title'):
                                video_info.episode_title = cached_data['episode_title'] + "-" + video_info.name_other
                                print(f"  ✓ 从缓存获取集数标题: 第{video_info.episode}集 - {video_info.episode_title}")
                        else:
                            # 尝试获取集数标题
                            if anime_info.source_url:
                                episode_title = self.scraper.get_episode_title(anime_info.source_url, video_info.episode)

                                if episode_title:
                                    video_info.episode_title = episode_title + "-" + video_info.name_other
                                    print(f"  ✓ 获取集数标题: 第{video_info.episode}集 - {episode_title}")
                                    # print(video_info.episode_title)
                                    self._add_episode_to_cache(anime_info.source_id, video_info.episode, episode_title)
                                else:
                                    video_info.episode_title = video_info.name_other
                                    print(f"  × 未获取集数标题, 直接用原文件标题: 第{video_info.episode}集 - {video_info.name_other}")
                                    print(video_info.episode_title)
                                    self._add_episode_to_cache(anime_info.source_id, video_info.episode, video_info.name_other)
                    else:
                        print(f"  未获取集数信息,直接用原文件标题:{video_info.name_other}")
                        video_info.episode_title = video_info.name_other
                        self._add_episode_to_cache(anime_info.source_id, video_info.name_other, video_info.name_other)
                # 生成新文件名
                new_filename = VideoFileParser.generate_new_filename(
                    video_info, anime_info, video_file.suffix
                )

                if new_filename:

                    new_path = anime_output_dir / new_filename
                    
                    # 复制文件到输出目录
                    import shutil
                    shutil.copy2(video_file, new_path)
                    
                    print(f"  ✓ {video_file.name}")
                    print(f"    → {new_filename}")
                    
                    processed_files.append({
                        'path': new_path,
                        'video_info': video_info,
                        'new_name': new_filename,
                        'source_file': str(video_file.absolute())  # 添加源文件绝对路径
                    })
            
            # 生成NFO文件
            print(f"\n  📄 生成NFO文件...")
            self._generate_nfo_files_for_group(anime_info, processed_files, generate_episode_nfo, anime_output_dir)
            
            # 下载海报
            print(f"\n  🖼️  处理海报...")
            if anime_info.poster_url:
                print(f"    尝试下载官方海报...")
                success = self._download_poster_for_group(anime_info.poster_url, [v[0] for v in videos], anime_output_dir)
                if not success:
                    print(f"    下载失败，尝试从视频提取...")
                    self._extract_poster_from_video_for_group(videos[0][0], anime_output_dir)
            else:
                print(f"    未找到官方海报，从视频提取...")
                self._extract_poster_from_video_for_group(videos[0][0], anime_output_dir)
            
            # 保存JSON信息
            self._save_json_for_group(anime_info, anime_output_dir, processed_files)
        
        print(f"\n" + "="*80)
        print(f"✅ 完成！输出目录: {self.output_dir.absolute()}")
        print(f"  共处理 {len(anime_groups)} 个番剧")
        print("="*80)
        return True
    
    def _sanitize_folder_name(self, name: str) -> str:
        """清理文件夹名称，移除非法字符"""
        # Windows不允许的字符
        illegal_chars = r'<>:"/\|?*'
        for char in illegal_chars:
            name = name.replace(char, '')
        # 移除前后空格和点号
        name = name.strip('. ')
        # 限制长度
        if len(name) > 200:
            name = name[:200]
        return name if name else 'Unknown'
    
    def _generate_nfo_files_for_group(self, anime_info: AnimeInfo, processed_files: List[Dict], 
                                      generate_episode_nfo: bool, output_dir: Path):
        """为特定番剧组生成NFO文件"""
        # 生成tvshow.nfo
        tvshow_nfo = self.nfo_generator.generate_tvshow_nfo(anime_info)
        tvshow_path = output_dir / 'tvshow.nfo'
        with open(tvshow_path, 'w', encoding='utf-8') as f:
            f.write(tvshow_nfo)
        print(f"    ✓ tvshow.nfo")
        
        # 生成单集NFO
        if generate_episode_nfo:
            for item in processed_files:
                video_info = item['video_info']
                source_file = item.get('source_file', '')  # 获取源文件路径
                if video_info.episode:
                    season = video_info.season or 1
                    episode_nfo = self.nfo_generator.generate_episode_nfo(
                        anime_info, video_info.episode, season, source_file
                    )
                    
                    nfo_path = item['path'].with_suffix('.nfo')
                    with open(nfo_path, 'w', encoding='utf-8') as f:
                        f.write(episode_nfo)
    
    def _download_poster_for_group(self, url: str, video_files: List[Path], output_dir: Path) -> bool:
        """为特定番剧组下载海报
        
        Args:
            url: 海报URL
            video_files: 视频文件列表（备用）
            output_dir: 输出目录
            
        Returns:
            bool: 下载是否成功
        """
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            
            ext = '.jpg'
            if '.png' in url.lower():
                ext = '.png'
            elif '.webp' in url.lower():
                ext = '.webp'
            
            poster_path = output_dir / f'poster{ext}'
            with open(poster_path, 'wb') as f:
                f.write(response.content)
            
            print(f"    ✓ 下载成功: poster{ext}")
            return True
            
        except Exception as e:
            print(f"    ✗ 下载失败: {e}")
            return False
    
    def _extract_poster_from_video_for_group(self, video_path: Path, output_dir: Path) -> bool:
        """为特定番剧组从视频中提取帧作为海报
        
        使用opencv-python库提取视频帧，无需ffmpeg
        
        Args:
            video_path: 视频文件路径
            output_dir: 输出目录
            
        Returns:
            bool: 提取是否成功
        """
        try:
            # 尝试导入opencv
            try:
                import cv2
            except ImportError:
                print(f"    ✗ opencv-python未安装")
                print(f"    提示: 运行 'pip install opencv-python' 安装")
                return False
            
            poster_path = output_dir / 'poster.jpg'
            
            # 打开视频文件
            video = cv2.VideoCapture(str(video_path))
            
            if not video.isOpened():
                print(f"    ✗ 无法打开视频文件")
                video.release()
                return False
            
            # 获取视频信息
            fps = video.get(cv2.CAP_PROP_FPS)
            frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            
            if fps > 0 and frame_count > 0:
                duration = frame_count / fps
                # 选择视频中间位置作为截图点（避开片头片尾）
                seek_time = min(max(duration * 0.3, 30), duration - 30)
                target_frame = int(seek_time * fps)
                print(f"    视频时长: {duration:.1f}秒，截取位置: {seek_time:.1f}秒")
            else:
                # 如果无法获取信息，使用默认帧数
                target_frame = 1800  # 约60秒（假设30fps）
                print(f"    无法获取视频信息，使用默认位置")
            
            # 定位到目标帧
            video.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            
            # 读取帧
            success, frame = video.read()
            
            if success and frame is not None:
                # 保存为jpg
                cv2.imwrite(str(poster_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                video.release()
                
                if poster_path.exists():
                    print(f"    ✓ 提取成功: poster.jpg")
                    return True
                else:
                    print(f"    ✗ 保存失败")
                    return False
            else:
                print(f"    ✗ 读取帧失败")
                video.release()
                return False
                
        except Exception as e:
            print(f"    ✗ 提取失败: {e}")
            return False
    
    def _save_json_for_group(self, anime_info: AnimeInfo, output_dir: Path, processed_files: List[Dict] = None):
        """为特定番剧组保存JSON信息
        
        Args:
            anime_info: 番剧信息
            output_dir: 输出目录
            processed_files: 处理后的文件列表（包含源文件信息）
        """
        import datetime
        
        json_data = {
            'title': anime_info.title,
            'original_title': anime_info.original_title,
            'year': anime_info.year,
            'plot': anime_info.plot,
            'rating': anime_info.rating,
            'genres': anime_info.genres,
            'studio': anime_info.studio,
            'premiered': anime_info.premiered,
            'episodes_total': anime_info.episodes_total,
            'poster_url': anime_info.poster_url,
            'tags': anime_info.tags,
            'source_url': anime_info.source_url,
            'source_id': anime_info.source_id,
            'processed_at': datetime.datetime.now().isoformat()
        }
        
        json_path = output_dir / 'anime_info.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        
        # 保存源文件映射信息（用于错误恢复）
        if processed_files:
            source_files_data = {
                'anime_title': anime_info.title,
                'anime_id': anime_info.source_id,
                'processed_at': datetime.datetime.now().isoformat(),
                'files': []
            }
            
            for item in processed_files:
                file_info = {
                    'new_filename': item['new_name'],
                    'new_path': str(item['path'].absolute()),
                    'source_filename': Path(item.get('source_file', '')).name if item.get('source_file') else '',
                    'source_path': item.get('source_file', ''),
                    'episode': item['video_info'].episode,
                    'season': item['video_info'].season or 1,
                    'episode_title': item['video_info'].episode_title if hasattr(item['video_info'], 'episode_title') else ''
                }
                source_files_data['files'].append(file_info)
            
            source_files_path = output_dir / 'source_files.json'
            with open(source_files_path, 'w', encoding='utf-8') as f:
                json.dump(source_files_data, f, ensure_ascii=False, indent=2)
            
            print(f"    ✓ source_files.json (源文件映射)")
    
    def _search_and_scrape(self, title: str, video_info: Optional[VideoInfo] = None, filename: str = None) -> Optional[AnimeInfo]:
        """搜索并刮削番剧信息（支持重试机制）
        
        Args:
            title: 搜索标题
            video_info: 视频信息（用于更精确的匹配）
            filename: 原始文件名（用于生成备选标题）
        """
        result = self._search_and_scrape_with_similarity(title, video_info, filename)
        if result:
            return result[0]  # 只返回anime_info，忽略similarity
        return None
    
    def _search_and_scrape_with_similarity(self, title: str, video_info: Optional[VideoInfo] = None, filename: str = None) -> Optional[Tuple[AnimeInfo, float]]:
        """搜索并刮削番剧信息（支持重试机制），返回匹配度
        
        Args:
            title: 搜索标题
            video_info: 视频信息（用于更精确的匹配）
            filename: 原始文件名（用于生成备选标题）
            
        Returns:
            (AnimeInfo, similarity) 元组，如果失败则返回None
        """
        # 第一次尝试：使用提取的标题
        print(f"  尝试1: 使用提取的标题")
        result = self._try_search_and_match_with_similarity(title, video_info)
        
        if result:
            return result
        
        # 如果第一次失败，尝试使用备选标题
        if filename:
            print(f"\n  ⚠️  第一次匹配失败，尝试使用备选标题...")
            print(f"  分析文件名的不同分割方式...")
            
            alternative_titles = VideoFileParser.generate_alternative_titles(filename)
            
            if alternative_titles:
                print(f"  生成了 {len(alternative_titles)} 个备选标题:")
                for i, alt_title in enumerate(alternative_titles[:5], 1):
                    print(f"    {i}. {alt_title}")
                
                # 尝试每个备选标题
                for i, alt_title in enumerate(alternative_titles, 1):
                    if alt_title == title:
                        continue  # 跳过已经尝试过的标题
                    
                    print(f"\n  尝试{i+1}: 使用备选标题 \"{alt_title}\"")
                    result = self._try_search_and_match_with_similarity(alt_title, video_info)
                    
                    if result:
                        print(f"  ✓ 使用备选标题匹配成功！")
                        return result
        
        # 所有尝试都失败
        print(f"\n  ❌ 所有匹配尝试都失败")
        return None
    
    def _try_search_and_match(self, title: str, video_info: Optional[VideoInfo] = None) -> Optional[AnimeInfo]:
        """尝试搜索和匹配（单次尝试）
        
        Args:
            title: 搜索标题
            video_info: 视频信息
            
        Returns:
            AnimeInfo对象，如果匹配失败则返回None
        """
        result = self._try_search_and_match_with_similarity(title, video_info)
        if result:
            return result[0]  # 只返回anime_info，忽略similarity
        return None
    
    def _try_search_and_match_with_similarity(self, title: str, video_info: Optional[VideoInfo] = None) -> Optional[Tuple[AnimeInfo, float]]:
        """尝试搜索和匹配（单次尝试），返回匹配度
        
        Args:
            title: 搜索标题
            video_info: 视频信息
            
        Returns:
            (AnimeInfo, similarity) 元组，如果匹配失败则返回None
        """
        # 搜索
        results = self.scraper.search(title)
        
        if not results:
            print("    ❌ 未找到搜索结果")
            return None
        
        print(f"    ✓ 找到 {len(results)} 个结果")
        if len(results) >10:
            print("    ❌ 当前标题索引结果过多，怀疑标题有误")
            return None
        # 智能匹配
        best_match = self.matcher.find_best_match(title, results, video_info)
        
        if not best_match:
            print("    ❌ 匹配度过低")
            return None
        
        selected = best_match['result']
        similarity = best_match['similarity']
        
        # 显示匹配结果
        print(f"\n  ✓ 自动选择最佳匹配:")
        print(f"    番剧: {selected.get('name', 'N/A')}")
        print(f"    ID: {selected.get('id', 'N/A')}")
        print(f"    相似度: {similarity:.1%}")
        
        # 根据相似度给出评价
        if similarity >= SmartMatcher.EXCELLENT_SIMILARITY_THRESHOLD:
            print(f"    评价: ✓ 优秀匹配")
        elif similarity >= SmartMatcher.GOOD_SIMILARITY_THRESHOLD:
            print(f"    评价: ✓ 良好匹配")
        elif similarity >= SmartMatcher.MIN_SIMILARITY_THRESHOLD:
            print(f"    评价: ⚠ 可接受匹配（建议人工确认）")
        
        # 显示其他候选（如果有）
        if 'all_matches' in best_match and len(best_match['all_matches']) > 1:
            print(f"\n  其他候选:")
            for i, match in enumerate(best_match['all_matches'][1:4], 2):
                print(f"    {i}. {match['name']} (相似度: {match['similarity']:.1%})")
        
        # 刮削详细信息
        print(f"\n  📥 获取详细信息...")
        anime_info = self.scraper.scrape_from_url(selected['url'])
        anime_info.name_other = video_info.name_other
        if anime_info:
            print(f"  ✓ 刮削成功")
            return (anime_info, similarity)
        else:
            print(f"  ❌ 刮削失败")
            return None
        similarity = best_match['similarity']
        
        print(f"\n  ✓ 自动选择 (相似度: {similarity:.1%}):")
        print(f"    {selected.get('name', 'N/A')} (ID: {selected.get('id', 'N/A')})")
        
        # 显示其他候选
        if len(results) > 1:
            print(f"\n  其他候选:")
            count = 0
            for item in results[:5]:
                if item != selected:
                    print(f"    • {item.get('name', 'N/A')}")
                    count += 1
                    if count >= 3:
                        break
        
        # 刮削详细信息
        print(f"\n  📥 获取详细信息...")
        anime_info = self.scraper.scrape_from_url(selected['url'])
        anime_info.name_other = video_info.name_other
        if anime_info:
            print(f"  ✓ 刮削成功")
        
        return anime_info



# ============================================================================
# 命令行接口
# ============================================================================

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='番剧自动整理工具 v1.9.3 - 自动提取、刮削、重命名、生成NFO，支持多番剧自动分组',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法（自动识别并分组不同番剧，递归扫描所有子文件夹）
  python anime_organizer.py "D:\\Anime\\混合文件夹"
  
  # 指定所有参数
  python anime_organizer.py "D:\\Anime\\混合文件夹" --output "D:\\Output" --no-episode-nfo
  
  # 使用缓存（避免重复刮削）
  python anime_organizer.py "D:\\Anime\\混合文件夹" --use-cache
  
  # 清除缓存
  python anime_organizer.py "D:\\Anime\\混合文件夹" --clear-cache

新功能 v1.9.3:
  - 文件夹级别100%匹配加速：同一文件夹的文件自动归入100%匹配的番剧
  - 源文件追踪：所有产出文件记录源文件信息，便于错误恢复
  - source_files.json：完整的源文件映射关系
  - NFO文件包含源文件路径

v1.9.2 功能:
  - 智能语言匹配：自动检测搜索关键词和结果的语言
  - 语言不匹配时自动使用对应语言的名称进行匹配
  - 大幅提高中日文混合环境下的匹配准确度

v1.9.1 功能:
  - 改进海报提取逻辑，更精确定位官方海报
  - 智能视频帧提取，自动选择最佳截取位置（避开片头片尾）
  - 海报下载失败自动从视频提取备用
  - 支持更多图片格式（jpg/png/webp）
  - 递归扫描所有子文件夹中的视频文件
        """
    )
    
    # 必需参数
    parser.add_argument('input', nargs='?', default=None,
                       help='输入路径（文件夹或视频文件）')
    
    # 可选参数
    parser.add_argument('--output', '-o', default='output', 
                       help='输出目录（默认: output）')
    parser.add_argument('--no-episode_nfo', action='store_true', default= False,
                       help='不生成单集NFO文件')
    parser.add_argument('--no_auto_group', action='store_true', default= False,
                       help='禁用自动分组（将所有文件视为同一番剧）')
    parser.add_argument('--use_cache', action='store_true',
                       help='使用缓存，避免重复刮削已处理的集数')
    parser.add_argument('--clear_cache', action='store_true',
                       help='清除缓存后再处理')
    parser.add_argument('--cache_dir', default='.cache',
                       help='缓存目录（默认: .cache）')
    
    args = parser.parse_args()
    
    # 如果没有提供输入路径，提示用户
    if not args.input:
        print("请输入要处理的路径（文件夹或视频文件）:")
        args.input = input().strip().strip('"')
        if not args.input:
            print("❌ 错误: 必须提供输入路径")
            return 1
    
    try:
        organizer = AnimeAutoOrganizer(
            output_dir=args.output,
            use_cache=args.use_cache,
            cache_dir=args.cache_dir
        )
        
        # 清除缓存
        if args.clear_cache:
            organizer.clear_cache()
            print("✓ 缓存已清除")
        
        success = organizer.process(
            args.input, 
            generate_episode_nfo=not args.no_episode_nfo,
            auto_group= not args.no_auto_group,
        )
        
        return 0 if success else 1
    
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        return 1
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())

