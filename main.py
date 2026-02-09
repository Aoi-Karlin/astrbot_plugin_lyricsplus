"""
AstrBot 歌词接龙插件
用户发送一句歌词，bot自动回复下一句，营造无缝对唱体验
"""

import aiohttp
import re
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from astrbot.api import logger
from astrbot.api.star import Star, register, Context, StarTools
from astrbot.api.event import filter, AstrMessageEvent


class NeteaseAPI:
    """网易云音乐API封装"""
    
    def __init__(self, base_url: str = "http://localhost:3000", metadata_keywords: Optional[List[str]] = None):
        self.base_url = base_url.rstrip('/')
        self._session: Optional[aiohttp.ClientSession] = None
        
        # 元数据过滤关键词列表
        self.metadata_keywords = metadata_keywords or [
            '作词', '作曲', '编曲', '演唱', '歌手', '专辑',
            '制作', '监制', '混音', '母带', '录音', '和声',
            '吉他', '贝斯', '鼓', '键盘', '制作人', '出品',
            '发行', 'OP', 'SP', '词', '曲', '唱', '编',
            '音乐', '画师', '调校', '映像', '封面', 'PV',
            'Vocal', 'Arrange', 'Lyrics', 'Music', 'Mix',
            'Master', 'Producer', 'Guitar', 'Bass', 'Drum'
        ]
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def close(self):
        """关闭session"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("NeteaseAPI session已关闭")
    
    async def search_songs(self, keyword: str, limit: int = 5) -> Optional[List[Dict]]:
        """
        根据关键词搜索多个歌曲结果
        
        Args:
            keyword: 搜索关键词（歌名或歌词片段）
            limit: 返回结果数量
            
        Returns:
            歌曲信息列表或None
        """
        url = f"{self.base_url}/cloudsearch"
        params = {
            'keywords': keyword,
            'type': 1,  # 搜索单曲
            'limit': limit
        }
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.error(f"搜索API返回错误状态码: {resp.status}")
                    return None
                
                data = await resp.json()
                
                logger.debug(f"搜索API返回数据: {data}")
                
                if data.get('code') == 200 and data.get('result', {}).get('songs'):
                    songs = data['result']['songs']
                    results = []
                    for idx, song in enumerate(songs):
                        try:
                            # 安全地提取歌曲信息
                            song_id = str(song.get('id', ''))
                            song_name = song.get('name', '未知歌曲')
                            
                            # 提取歌手信息
                            artists = song.get('ar', [])
                            artist_name = '未知歌手'
                            if artists and len(artists) > 0:
                                artist_name = artists[0].get('name', '未知歌手')
                            
                            # 提取专辑信息
                            album = song.get('al', {})
                            album_name = album.get('name', '未知专辑') if album else '未知专辑'
                            
                            results.append({
                                'id': song_id,
                                'name': song_name,
                                'artist': artist_name,
                                'album': album_name
                            })
                            logger.debug(f"解析歌曲 {idx+1}: {song_name} - {artist_name}")
                        except (KeyError, TypeError, ValueError) as e:
                            logger.warning(f"解析歌曲信息时出错: {e}, song={song}")
                            continue
                    
                    logger.info(f"搜索成功，找到 {len(results)} 首歌曲")
                    return results
                else:
                    logger.warning(f"搜索API返回错误码或空结果: code={data.get('code')}")
                    return None
        
        except aiohttp.ClientError as e:
            logger.error(f"搜索API请求失败: {e}")
            return None
        except asyncio.TimeoutError:
            logger.error("搜索API请求超时")
            return None
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"解析搜索结果失败: {e}", exc_info=True)
            return None
    
    async def get_lyrics(self, song_id: str) -> Optional[List[Dict]]:
        """
        获取歌曲歌词
        
        Args:
            song_id: 歌曲ID
            
        Returns:
            歌词列表或None
        """
        url = f"{self.base_url}/lyric"
        params = {'id': song_id}
        
        try:
            session = await self._get_session()
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.error(f"歌词API返回错误状态码: {resp.status}")
                    return None
                
                data = await resp.json()
                
                if data.get('code') != 200:
                    logger.warning(f"获取歌词失败，歌曲ID: {song_id}")
                    return None
                
                # 优先使用逐字歌词 yrc
                if data.get('yrc', {}).get('lyric'):
                    return self._parse_yrc_lyrics(data['yrc']['lyric'])
                
                # 降级使用普通歌词 lrc
                if data.get('lrc', {}).get('lyric'):
                    return self._parse_lrc_lyrics(data['lrc']['lyric'])
                
                logger.warning(f"未找到歌词内容，歌曲ID: {song_id}")
                return None
        
        except aiohttp.ClientError as e:
            logger.error(f"歌词API请求失败: {e}")
            return None
        except asyncio.TimeoutError:
            logger.error("歌词API请求超时")
            return None
        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"解析歌词失败: {e}", exc_info=True)
            return None
    
    def _parse_yrc_lyrics(self, yrc_content: str) -> List[Dict]:
        """
        解析YRC逐字歌词格式
        
        格式: [16210,3460](16210,670,0)还(16880,410,0)没...
        - [开始时间,总时长](时间,时长,0)字(...)
        
        Args:
            yrc_content: YRC歌词内容
            
        Returns:
            解析后的歌词列表
        """
        lyrics = []
        
        if not yrc_content:
            return lyrics
        
        lines = yrc_content.strip().split('\n')
        
        for line in lines:
            # 跳过元数据行（JSON格式）
            if line.startswith('{'):
                continue
            
            # 提取时间戳和歌词文本
            match = re.match(r'\[(\d+),\d+\](.+)', line)
            if match:
                timestamp = int(match.group(1))
                
                # 提取纯文本（去除时间标记）
                text_part = match.group(2)
                # 移除所有(时间,时长,0)标记
                text = re.sub(r'\(\d+,\d+,\d+\)', '', text_part)
                
                cleaned_text = text.strip()
                if cleaned_text:
                    is_meta = self._is_metadata_line(cleaned_text)
                    if is_meta:
                        logger.debug(f"过滤元数据行: '{cleaned_text}'")
                    else:
                        lyrics.append({
                            'time': timestamp,
                            'text': cleaned_text
                        })

        logger.debug(f"YRC歌词解析完成，保留 {len(lyrics)} 行")
        return lyrics
    
    def _parse_lrc_lyrics(self, lrc_content: str) -> List[Dict]:
        """
        解析LRC普通歌词格式
        
        格式: [00:16.21]还没好好的感受
        
        Args:
            lrc_content: LRC歌词内容
            
        Returns:
            解析后的歌词列表
        """
        lyrics = []
        
        if not lrc_content:
            return lyrics
        
        lines = lrc_content.strip().split('\n')
        
        for line in lines:
            # 匹配 [mm:ss.xx]歌词 或 [mm:ss.xxx]歌词
            matches = re.findall(r'\[(\d+):(\d+)\.(\d+)\]([^\[]+)', line)
            
            for match in matches:
                minutes = int(match[0])
                seconds = int(match[1])
                # 处理毫秒（可能是2位或3位）
                ms_str = match[2]
                milliseconds = int(ms_str) * (10 if len(ms_str) == 2 else 1)
                text = match[3].strip()
                
                if text:
                    is_meta = self._is_metadata_line(text)
                    if is_meta:
                        logger.debug(f"过滤元数据行: '{text}'")
                    else:
                        timestamp = (minutes * 60 + seconds) * 1000 + milliseconds
                        lyrics.append({
                            'time': timestamp,
                            'text': text
                        })
        
        # 按时间戳排序
        lyrics.sort(key=lambda x: x['time'])
        
        logger.debug(f"LRC歌词解析完成，保留 {len(lyrics)} 行")
        return lyrics

    def _is_metadata_line(self, text: str) -> bool:
        """
        判断是否为元数据行 - 最终增强版
        """
        if not text:
            return False

        # 1. 剥离可能残留的时间轴
        text_content = re.sub(r'^\[.*?\]', '', text)
        if not text_content.strip():
            return False

        # 2. 预处理：统一全角冒号，移除所有空白，转小写
        # 兼容 ASCII冒号(:), 全角冒号(：)
        normalized = text_content.replace('：', ':')
        cleaned = re.sub(r'\s+', '', normalized).lower()

        # 3. 匹配关键词
        for keyword in self.metadata_keywords:
            # 同样清洗关键词
            clean_kw = re.sub(r'\s+', '', keyword).lower()

            # 检查是否以 "关键词:" 开头
            if cleaned.startswith(f"{clean_kw}:"):
                return True

        return False

    
class LyricGameSession:
    """歌词游戏会话"""
    
    def __init__(self):
        self.song_id: Optional[str] = None
        self.lyrics: List[Dict] = []
        self.position: int = 0
        self.in_song: bool = False
        self.last_time: float = 0.0
        self.last_active: datetime = datetime.now()  # 用于会话清理
        self.song_info: Optional[Dict] = None
        self.selecting_song: bool = False  # 是否正在选择歌曲
        self.song_candidates: List[Dict] = []  # 候选歌曲列表
        self.start_lyric_keyword: Optional[str] = None  # 起始歌词关键词（用于从中间开始）


class LyricGame:
    """歌词接龙游戏核心逻辑"""
    
    def __init__(self, plugin, netease_api: str, cache_dir: str, session_timeout: int = 60, match_threshold: int = 75, search_limit: int = 5, config: Optional[Dict] = None):
        self.plugin = plugin
        self.config = config or {}
        
        # 从配置读取元数据过滤关键词
        metadata_keywords = self.config.get('metadata_filter_keywords', None)
        
        self.api = NeteaseAPI(netease_api, metadata_keywords=metadata_keywords)
        self.sessions: Dict[str, LyricGameSession] = {}
        self.session_timeout = session_timeout
        self.match_threshold = match_threshold
        self.search_limit = search_limit
        self.cache_dir = cache_dir
        self._cleanup_task: Optional[asyncio.Task] = None
        
        logger.info(f"歌词接龙游戏初始化完成，会话超时: {session_timeout}秒，匹配阈值: {match_threshold}，搜索数量: {search_limit}，缓存目录: {self.cache_dir}")
    
    async def start_cleanup_task(self):
        """启动会话清理任务"""
        self._cleanup_task = asyncio.create_task(self._cleanup_sessions())
        logger.info("会话清理任务已启动")
    
    async def _cleanup_sessions(self):
        """定期清理超时会话"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                now = datetime.now()
                expired_users = []
                
                for user_id, session in self.sessions.items():
                    # 清理超过2倍超时时间且未在游戏中的会话
                    if now - session.last_active > timedelta(seconds=self.session_timeout * 2):
                        if not session.in_song:
                            expired_users.append(user_id)
                
                for user_id in expired_users:
                    del self.sessions[user_id]
                    logger.info(f"清理过期会话: {user_id}")
                
                if expired_users:
                    logger.info(f"本次清理了 {len(expired_users)} 个过期会话")
            except asyncio.CancelledError:
                logger.info("会话清理任务已取消")
                break
            except Exception as e:
                logger.error(f"会话清理任务出错: {e}", exc_info=True)
    
    async def stop_cleanup_task(self):
        """停止清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("会话清理任务已停止")
    
    def get_session(self, user_id: str) -> LyricGameSession:
        """获取用户会话"""
        if user_id not in self.sessions:
            self.sessions[user_id] = LyricGameSession()
        else:
            # 更新最后活跃时间
            self.sessions[user_id].last_active = datetime.now()
        return self.sessions[user_id]
    
    def clean_text(self, text: str) -> str:
        """
        清理文本：去除标点、空格，转小写
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        if not text:
            return ""
        
        # 去除标点符号
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', '', text)
        # 去除所有空白字符
        text = re.sub(r'\s+', '', text)
        # 转小写
        return text.lower()
    
    def calculate_similarity(self, text1: str, text2: str) -> int:
        """
        计算两个文本的相似度分数
        
        Args:
            text1: 第一个文本
            text2: 第二个文本
            
        Returns:
            相似度分数 (0-100)
        """
        if not text1 or not text2:
            return 0
        
        # 清理文本
        clean1 = self.clean_text(text1)
        clean2 = self.clean_text(text2)
        
        if not clean1 or not clean2:
            return 0
        
        # 精确匹配
        if clean1 == clean2:
            return 100
        
        # 包含匹配
        if clean1 in clean2 or clean2 in clean1:
            return 90
        
        # 计算编辑距离相似度
        max_len = max(len(clean1), len(clean2))
        if max_len == 0:
            return 0
        
        # 计算Levenshtein距离
        distance = self._levenshtein_distance(clean1, clean2)
        similarity = int((1 - distance / max_len) * 100)
        
        return max(0, similarity)
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """
        计算Levenshtein编辑距离
        
        Args:
            s1: 第一个字符串
            s2: 第二个字符串
            
        Returns:
            编辑距离
        """
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                
                current_row.append(min(insertions, deletions, substitutions))
            
            previous_row = current_row
        
        return previous_row[-1]
    
    def is_match(self, user_input: str, expected: str) -> bool:
        """
        判断用户输入是否匹配预期歌词
        
        Args:
            user_input: 用户输入
            expected: 预期歌词
            
        Returns:
            是否匹配
        """
        similarity = self.calculate_similarity(user_input, expected)
        return similarity >= self.match_threshold
    
    async def find_position(self, user_input: str, lyrics: List[Dict], session: LyricGameSession) -> int:
        """
        智能定位：支持跳句和重复歌词
        
        Args:
            user_input: 用户输入
            lyrics: 歌词列表
            session: 当前会话
            
        Returns:
            匹配的歌词索引，-1表示未找到
        """
        if not lyrics:
            return -1
        
        # 策略1：检查下一句（如果正在连唱中）
        if session.in_song and session.position < len(lyrics):
            if self.is_match(user_input, lyrics[session.position]['text']):
                logger.debug(f"匹配到下一句，位置: {session.position}")
                return session.position
        
        # 策略2：检查下下句（用户可能跳了一句）
        if session.in_song and session.position + 1 < len(lyrics):
            if self.is_match(user_input, lyrics[session.position + 1]['text']):
                logger.debug(f"匹配到下下句，位置: {session.position + 1}")
                return session.position + 1
        
        # 策略3：附近范围搜索
        if session.in_song:
            start = max(0, session.position - 3)
            end = min(len(lyrics), session.position + 10)
            
            for i in range(start, end):
                if self.is_match(user_input, lyrics[i]['text']):
                    logger.debug(f"匹配到附近歌词，位置: {i}")
                    return i
        
        # 策略4：全局搜索
        for i in range(len(lyrics)):
            if self.is_match(user_input, lyrics[i]['text']):
                logger.debug(f"匹配到全局歌词，位置: {i}")
                return i
        
        logger.debug("未找到匹配的歌词")
        return -1
    
    async def get_lyrics(self, song_id: str) -> Optional[List[Dict]]:
        """
        获取歌词，优先从缓存读取
        
        Args:
            song_id: 歌曲ID
            
        Returns:
            歌词列表或None
        """
        # 从AstrBot存储读取缓存
        cached = await self.plugin.get_kv_data(f"lyrics_{song_id}", None)
        if cached:
            logger.debug(f"从缓存读取歌词，歌曲ID: {song_id}")
            return cached
        
        # 调用API获取
        lyrics = await self.api.get_lyrics(song_id)
        
        if lyrics:
            # 缓存到AstrBot存储
            await self.plugin.put_kv_data(f"lyrics_{song_id}", lyrics)
            logger.info(f"缓存歌词成功，歌曲ID: {song_id}")
        
        return lyrics
    
    async def handle(self, user_id: str, user_input: str) -> Optional[str]:
        """
        主处理函数：用户一句，返回下一句
        
        Args:
            user_id: 用户ID
            user_input: 用户输入
            
        Returns:
            下一句歌词或None
        """
        session = self.get_session(user_id)
        current_time = time.time()
        
        # 超时重置
        if current_time - session.last_time > self.session_timeout:
            if session.in_song:
                logger.info(f"用户 {user_id} 会话超时，重置连唱状态")
                session.in_song = False
        
        session.last_time = current_time
        
        # 检查是否在游戏中
        if not session.in_song:
            logger.debug(f"用户 {user_id} 不在游戏中，不处理")
            return None
        
        # 对唱逻辑：
        # position指向用户需要输入的歌词
        # 用户输入 position 句，验证通过后 bot 回复 position+1 句
        # position 更新为 position+2（跳过bot回复的那句，指向用户下次要输入的句子）
        
        # 检查是否还有足够的歌词
        if session.position >= len(session.lyrics):
            logger.info(f"用户 {user_id} 歌曲已唱完，position={session.position}, 歌词总数={len(session.lyrics)}")
            session.in_song = False
            return self.config.get('msg_song_completed', '🎉 歌曲已唱完！')
        
        # 用户应该输入的歌词（position句）
        expected = session.lyrics[session.position]['text']
        logger.debug(f"用户 {user_id} position={session.position}, 用户应输入第{session.position}句='{expected}', user_input='{user_input}'")
        
        if self.is_match(user_input, expected):
            # 匹配成功，返回 position+1 句
            logger.info(f"用户 {user_id} 对唱匹配成功")
            
            if session.position + 1 < len(session.lyrics):
                next_line = session.lyrics[session.position + 1]['text']
                old_position = session.position
                session.position += 2  # 跳过bot回复的句子，指向用户下次要输入的句子
                logger.debug(f"用户 {user_id} 验证通过，position从{old_position}更新为{session.position}, 返回第{old_position + 1}句='{next_line}'")
                
                # 检查下次是否还有歌词（避免用户再发一条消息才看到"歌曲已唱完"）
                if session.position >= len(session.lyrics):
                    logger.info(f"用户 {user_id} 这是最后一轮，歌曲即将唱完，设置 in_song=False")
                    session.in_song = False
                    msg_template = self.config.get('msg_song_completed_with_last_line', '{last_line}\n\n🎉 歌曲已唱完！')
                    return msg_template.format(last_line=next_line)
                
                return next_line
            else:
                # 没有下一句了，歌曲唱完
                logger.info(f"用户 {user_id} 歌曲已唱完（无下一句），设置 in_song=False")
                session.in_song = False
                return self.config.get('msg_song_completed', '🎉 歌曲已唱完！')
        else:
            # 匹配失败，保持在当前位置，提示用户重试
            similarity = self.calculate_similarity(user_input, expected)
            logger.info(f"用户 {user_id} 对唱匹配失败，相似度: {similarity}%，保持在当前位置")
            logger.debug(f"用户 {user_id} 匹配失败，position={session.position}, expected='{expected}', user_input='{user_input}'")
            msg_template = self.config.get('msg_match_failed', '不匹配（相似度: {similarity}%），请重试！\n你输入: {user_input}\n正确歌词: {expected}\n提示：发送\'退出接歌\'可退出游戏')
            return msg_template.format(similarity=similarity, user_input=user_input, expected=expected)
    
    async def _output_next(self, session: LyricGameSession) -> Optional[str]:
        """
        输出当前position指向的歌词
        
        Args:
            session: 游戏会话
            
        Returns:
            当前歌词或None
        """
        if session.position >= len(session.lyrics):
            # 唱完了
            logger.info("歌曲已唱完，结束连唱")
            session.in_song = False
            return None
        
        next_line = session.lyrics[session.position]['text']
        return next_line
    
    async def exit_session(self, user_id: str) -> Optional[str]:
        """
        退出游戏会话
        
        Args:
            user_id: 用户ID
            
        Returns:
            退出消息或None
        """
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"用户 {user_id} 已退出游戏")
            return self.config.get('msg_exit_game', '已退出连唱模式')
        
        return None


@register("lyric_game", "歌词接龙游戏", "1.0.0", "AstrBot")
class LyricGamePlugin(Star):
    def __init__(self, context: Context, config: Optional[Dict] = None):
        super().__init__(context)
        self.name = "lyric_game"  # 插件名称
        self.game = None
        self.active_sessions = set()  # 记录正在接歌词的用户
        self.config = config or {}
        
    async def initialize(self):
        """插件初始化"""
        logger.info("歌词接龙插件初始化...")
        
        # 使用框架推荐的方法获取插件数据目录
        plugin_data_path = StarTools.get_data_dir(self.name)
        cache_dir = str(plugin_data_path)
        
        # 创建缓存目录
        plugin_data_path.mkdir(parents=True, exist_ok=True)
        
        self.game = LyricGame(
            plugin=self,
            netease_api=self.config.get('netease_api', 'http://localhost:3000'),
            cache_dir=cache_dir,
            session_timeout=self.config.get('session_timeout', 60),
            match_threshold=self.config.get('match_threshold', 75),
            search_limit=self.config.get('search_limit', 5),
            config=self.config
        )
        
        # 启动会话清理任务
        await self.game.start_cleanup_task()
        
        logger.info(f"歌词接龙插件初始化完成，插件名称: {self.name}，缓存目录: {cache_dir}")
    
    async def terminate(self):
        """插件清理"""
        logger.info("歌词接龙插件正在清理...")
        
        # 停止会话清理任务
        if self.game:
            await self.game.stop_cleanup_task()
            # 关闭API session
            if self.game.api:
                await self.game.api.close()
        
        # 清理活跃会话
        self.active_sessions.clear()
        logger.info("歌词接龙插件清理完成")
    
    @filter.command_group("接歌词")
    def lyric_game_group(self):
        """歌词接龙游戏指令组"""
        pass
    
    @lyric_game_group.command("search")
    async def handle_lyric_search(self, event: AstrMessageEvent, keyword: str = ""):
        """搜索歌曲并从第一句开始
        
        用法：/接歌词 search 歌曲名
        例如：/接歌词 search 晴天
        """
        user_id = event.unified_msg_origin
        message = keyword.strip()
        
        logger.debug(f"收到搜索指令，关键词: '{message}', 用户: {user_id}")
        
        if not message:
            yield event.plain_result(self.config.get('msg_empty_keyword', '请提供歌曲名或歌词片段，例如：/接歌词 search 晴天'))
            return
        
        logger.info(f"搜索关键词: '{message}'")
        
        # 搜索歌曲
        try:
            session = self.game.get_session(user_id)
            logger.debug(f"调用API搜索，关键词: '{message}', 限制: {self.game.search_limit}")
            songs = await self.game.api.search_songs(message, limit=self.game.search_limit)
            
            if not songs:
                yield event.plain_result(self.config.get('msg_no_songs_found', '未找到相关歌曲，请尝试其他关键词'))
                return
            
            # 存储候选歌曲
            session.selecting_song = True
            session.song_candidates = songs
            self.active_sessions.add(user_id)  # 标记用户在选择歌曲状态
            
            logger.info(f"用户 {user_id} 被添加到 active_sessions，当前活跃会话: {self.active_sessions}")
            
            # 显示搜索结果
            prefix = self.config.get('msg_song_selection_prefix', '找到以下歌曲，请发送数字选择：')
            result = prefix + "\n"
            for idx, song in enumerate(songs, 1):
                result += f"{idx}. {song['name']} - {song['artist']}\n"
            
            yield event.plain_result(result.strip())
            
        except aiohttp.ClientError as e:
            logger.error(f"搜索歌曲API失败: {e}")
            yield event.plain_result(self.config.get('msg_search_failed', '搜索失败，请重试'))
        except Exception as e:
            logger.error(f"搜索歌曲时出错: {e}", exc_info=True)
            yield event.plain_result(self.config.get('msg_search_failed', '搜索失败，请重试'))
    
    @lyric_game_group.command("from")
    async def handle_lyric_start_from(self, event: AstrMessageEvent, song_keyword: str = "", lyric_keyword: str = ""):
        """从指定歌词开始游戏
        
        用法：/接歌词 from 歌曲名 歌词关键词
        例如：/接歌词 from 晴天 从前从前
        """
        user_id = event.unified_msg_origin
        
        logger.debug(f"收到from指令，歌曲: '{song_keyword}', 歌词: '{lyric_keyword}', 用户: {user_id}")
        
        if not song_keyword or not lyric_keyword:
            yield event.plain_result("请提供歌曲名和歌词关键词，例如：/接歌词 from 晴天 从前从前")
            return
        
        logger.info(f"搜索歌曲: '{song_keyword}', 歌词关键词: '{lyric_keyword}'")
        
        try:
            session = self.game.get_session(user_id)
            
            # 搜索歌曲
            songs = await self.game.api.search_songs(song_keyword, limit=self.game.search_limit)
            
            if not songs:
                yield event.plain_result(self.config.get('msg_no_songs_found', '未找到相关歌曲，请尝试其他关键词'))
                return
            
            # 存储候选歌曲和歌词关键词
            session.selecting_song = True
            session.song_candidates = songs
            session.start_lyric_keyword = lyric_keyword  # 保存歌词关键词
            self.active_sessions.add(user_id)
            
            logger.info(f"用户 {user_id} 被添加到 active_sessions（from模式），歌词关键词: {lyric_keyword}")
            
            # 显示搜索结果
            prefix = self.config.get('msg_song_selection_prefix', '找到以下歌曲，请发送数字选择：')
            result = prefix + "\n"
            for idx, song in enumerate(songs, 1):
                result += f"{idx}. {song['name']} - {song['artist']}\n"
            
            yield event.plain_result(result.strip())
            
        except aiohttp.ClientError as e:
            logger.error(f"搜索歌曲API失败: {e}")
            yield event.plain_result(self.config.get('msg_search_failed', '搜索失败，请重试'))
        except Exception as e:
            logger.error(f"搜索歌曲时出错: {e}", exc_info=True)
            yield event.plain_result(self.config.get('msg_search_failed', '搜索失败，请重试'))
    
    @filter.regex(r"^\d+$", priority=1000)
    async def handle_number_selection(self, event: AstrMessageEvent):
        """专门处理数字选择，高优先级"""
        user_id = event.unified_msg_origin
        
        logger.info(f"数字选择处理器被调用，用户: {user_id}, active_sessions: {self.active_sessions}")
        
        # 只处理处于活跃状态的用户
        if user_id not in self.active_sessions:
            logger.debug(f"用户 {user_id} 不在活跃会话中，数字选择处理器跳过")
            return
        
        message = event.message_str.strip()
        logger.info(f"用户 {user_id} 发送数字: '{message}'")
        
        session = self.game.get_session(user_id)
        
        # 检查是否正在选择歌曲
        if not session.selecting_song or not session.song_candidates:
            logger.debug(f"用户 {user_id} 不在选择歌曲状态，跳过数字选择处理器")
            return
        
        try:
            # 解析用户输入的数字
            choice = int(message)
            logger.info(f"用户 {user_id} 解析数字: {choice}, 候选歌曲数量: {len(session.song_candidates)}")
            
            if 1 <= choice <= len(session.song_candidates):
                # 选择歌曲
                selected_song = session.song_candidates[choice - 1]
                session.selecting_song = False
                session.song_candidates = []
                
                logger.info(f"用户 {user_id} 选择歌曲: {selected_song['name']} (ID: {selected_song['id']})")
                
                # 获取歌词
                logger.info(f"用户 {user_id} 开始获取歌词...")
                lyrics = await self.game.get_lyrics(selected_song['id'])
                
                if not lyrics:
                    logger.warning(f"用户 {user_id} 获取歌词失败，歌曲ID: {selected_song['id']}")
                    yield event.plain_result(self.config.get('msg_no_lyrics', '未获取到歌词，请尝试其他歌曲'))
                    self.active_sessions.discard(user_id)
                    return
                
                logger.info(f"用户 {user_id} 成功获取歌词，数量: {len(lyrics)}")
                
                # 检查是否需要从指定歌词开始
                start_position = 0
                start_lyric_keyword = session.start_lyric_keyword
                
                if start_lyric_keyword:
                    # 搜索匹配的歌词位置
                    logger.info(f"用户 {user_id} 尝试从歌词 '{start_lyric_keyword}' 开始")
                    found_position = -1
                    
                    for idx, lyric in enumerate(lyrics):
                        if self.game.is_match(start_lyric_keyword, lyric['text']):
                            found_position = idx
                            logger.info(f"找到匹配歌词，位置: {idx}, 歌词: {lyric['text']}")
                            break
                    
                    if found_position == -1:
                        # 未找到匹配的歌词
                        logger.warning(f"用户 {user_id} 未找到匹配歌词: {start_lyric_keyword}")
                        session.start_lyric_keyword = None  # 清除关键词
                        msg_template = self.config.get('msg_line_not_found', '未在《{song_name}》中找到歌词：{keyword}\n请尝试其他关键词或使用/接歌词选择从第一句开始')
                        yield event.plain_result(msg_template.format(song_name=selected_song['name'], keyword=start_lyric_keyword))
                        self.active_sessions.discard(user_id)
                        return
                    
                    start_position = found_position
                    session.start_lyric_keyword = None  # 清除关键词
                
                # 初始化会话
                session.song_id = selected_song['id']
                session.song_info = selected_song
                session.lyrics = lyrics
                session.position = start_position  # 从指定位置开始
                session.in_song = True
                session.last_time = time.time()  # 设置当前时间，避免超时检查误判
                
                logger.info(f"用户 {user_id} 成功初始化歌曲会话，起始位置: {start_position}")
                
                # bot先给出起始句，让用户确认
                first_line = lyrics[start_position]['text']
                
                if start_position > 0:
                    # 从中间开始，使用特殊提示
                    msg_template = self.config.get('msg_start_from_line', '已选择《{song_name}》\n从第{line_number}句开始：{first_line}\n提示：歌词匹配阈值当前为{threshold}%')
                    message = msg_template.format(
                        song_name=selected_song['name'], 
                        line_number=start_position + 1,
                        first_line=first_line, 
                        threshold=self.game.match_threshold
                    )
                else:
                    # 从头开始，使用默认提示
                    msg_template = self.config.get('msg_game_start', '已选择《{song_name}》\n请接歌词：{first_line}\n提示：歌词匹配阈值当前为{threshold}%，可在插件配置中调整（建议60-70）')
                    message = msg_template.format(song_name=selected_song['name'], first_line=first_line, threshold=self.game.match_threshold)
                
                # 重要：阻止后续处理器（handle_all_messages）继续处理这条消息
                event.stop_event()
                
                yield event.plain_result(message)
            else:
                logger.warning(f"用户 {user_id} 输入无效数字: {choice}, 有效范围: 1-{len(session.song_candidates)}")
                msg_template = self.config.get('msg_invalid_number', '请输入1-{count}之间的数字')
                yield event.plain_result(msg_template.format(count=len(session.song_candidates)))
        except ValueError as e:
            logger.warning(f"用户 {user_id} 输入非数字: '{message}', 错误: {e}")
            # 不是数字，让其他处理器处理
            return
        except Exception as e:
            logger.error(f"用户 {user_id} 选择歌曲时出错: {e}", exc_info=True)
            yield event.plain_result(self.config.get('msg_selection_error', '选择歌曲时出错，请重试'))
            self.active_sessions.discard(user_id)
    
    @filter.regex(r".*", priority=999)
    async def handle_all_messages(self, event: AstrMessageEvent):
        """监听所有消息，处理歌词接龙"""
        user_id = event.unified_msg_origin
        
        logger.debug(f"通用消息处理器被调用，用户: {user_id}, active_sessions: {self.active_sessions}")
        
        # 只处理处于活跃状态的用户（接歌词）
        if user_id not in self.active_sessions:
            logger.debug(f"用户 {user_id} 不在活跃会话中，通用处理器跳过")
            return
        
        message = event.message_str.strip()
        logger.debug(f"处理用户 {user_id} 的消息: '{message}'")
        
        if not message:
            logger.debug(f"用户 {user_id} 发送空消息，跳过处理")
            return
        
        # 跳过纯数字消息，避免与数字选择处理器冲突
        if message.isdigit():
            logger.debug(f"用户 {user_id} 发送纯数字消息，跳过通用处理器")
            return
        
        # 处理退出命令
        if message in ['退出接歌', '结束接歌', 'quit', 'q']:
            logger.info(f"用户 {user_id} 退出接歌词模式")
            self.active_sessions.discard(user_id)
            response = await self.game.exit_session(user_id)
            if response:
                event.stop_event()  # 阻止LLM回复
                yield event.plain_result(response)
            return
        
        session = self.game.get_session(user_id)
        
        # 如果在选择歌曲状态，让数字选择处理器处理
        if session.selecting_song:
            logger.debug(f"用户 {user_id} 正在选择歌曲，通用处理器跳过")
            return
        
        # 处理歌词接龙
        try:
            logger.info(f"用户 {user_id} 正在接歌词，输入: '{message}'")
            response = await self.game.handle(user_id, message)
            
            if response:
                # 匹配成功或失败，发送回复
                logger.info(f"用户 {user_id} 接歌词返回: '{response}', in_song={session.in_song}")
                event.stop_event()  # 阻止LLM回复
                yield event.plain_result(response)
                
                # 如果游戏已结束（in_song为False），清理active_sessions
                if not session.in_song:
                    logger.info(f"用户 {user_id} 游戏已结束，清理active_sessions")
                    self.active_sessions.discard(user_id)
            else:
                # response为None，说明不在游戏中或出现意外情况
                logger.warning(f"用户 {user_id} 接歌词返回None，可能不在游戏中")
                event.stop_event()  # 阻止LLM回复
                yield event.plain_result("游戏状态异常，请重新开始")
                self.active_sessions.discard(user_id)
            
        except Exception as e:
            logger.error(f"处理歌词接龙时出错: {e}", exc_info=True)
            event.stop_event()  # 阻止LLM回复
            yield event.plain_result("处理出错，已退出接歌词模式")
            # 发生错误时退出接歌词模式
            self.active_sessions.discard(user_id)
