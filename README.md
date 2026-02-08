# AstrBot 歌词接龙插件

一个为AstrBot开发的沉浸式歌词接龙插件，用户发送一句歌词，bot自动回复下一句，营造无缝对唱体验。

## 功能特性

### 🎵 核心功能
- **智能识别**：根据歌词片段自动识别歌曲
- **无缝对唱**：匹配成功后自动进入连唱模式
- **容错纠错**：支持模糊匹配，唱错自动纠正
- **跳句接龙**：支持跳过一句继续接唱
- **多用户支持**：每个用户独立会话，互不干扰

### 🎯 交互模式
- **纯文本输出**：只返回歌词，无任何提示或emoji
- **静默失败**：识别失败时不回复，不影响其他插件
- **会话管理**：60秒无活动自动重置会话
- **退出命令**：支持`退出接歌`、`结束接歌`、`quit`命令

## 安装部署

### 前置要求

1. **部署网易云音乐API服务**

   需要部署 [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi) 服务：

   ```bash
   # 使用Docker部署（推荐）
   docker run -d -p 3000:3000 --name netease_api binaryify/netease_cloud_music_api

   # 或使用npm
   git clone https://github.com/Binaryify/NeteaseCloudMusicApi.git
   cd NeteaseCloudMusicApi
   npm install
   npm start
   ```

2. **安装插件依赖**

   ```bash
   pip install -r requirements.txt
   ```

### 插件安装

将插件文件夹复制到AstrBot的插件目录：

```bash
# 通常位于 AstrBot/data/plugins/
cp -r lyric_game /path/to/astrbot/data/plugins/
```

重启AstrBot后，在WebUI中配置插件。

## 配置说明

在AstrBot WebUI中配置以下参数：

| 参数                | 说明         | 默认值                     |
|-------------------|------------|-------------------------|
| `enabled`         | 是否启用插件     | `true`                  |
| `netease_api`     | 网易云音乐API地址 | `http://localhost:3000` |
| `cache_dir`       | 歌词缓存目录     | `./data/lyrics_cache`   |
| `session_timeout` | 会话超时时间（秒）  | `60`                    |

## 使用示例

### 正常连唱
```
用户: 天空好想下雨
Bot: 我好想住你隔壁

用户: 我好想住你隔壁
Bot: 傻站在你家楼下

用户: 傻站在你家楼下
Bot: 抬起头数乌云
```

### 唱错了（自动纠正）
```
用户: 天空好想下雨
Bot: 我好想住你隔壁

用户: 错误的歌词
Bot: 傻站在你家楼下  # 自动纠正并继续
```

### 跳句接歌
```
用户: 天空好想下雨
Bot: 我好想住你隔壁

用户: 抬起头数乌云  # 跳过一句
Bot: 如果场景里出现一滴雨
```

### 退出游戏
```
用户: 退出接歌
Bot: 已退出连唱模式
```

## 技术实现

### 歌词匹配算法
- 使用Levenshtein编辑距离计算相似度
- 支持模糊匹配（默认阈值75%）
- 清理标点符号和空白字符
- 智能定位策略：
  1. 检查下一句（最常见）
  2. 检查下下句（用户跳句）
  3. 附近范围搜索（±3到+10句）
  4. 全局搜索（换位置或新开始）

### 歌词格式支持
- **YRC格式**：逐字歌词，带时间戳
  ```
  [16210,3460](16210,670,0)还(16880,410,0)没...
  ```
- **LRC格式**：普通歌词
  ```
  [00:16.21]还没好好的感受
  ```

### 缓存机制
- 使用AstrBot存储API缓存歌词
- 避免频繁调用外部API
- 提升响应速度和稳定性

## 文件结构

```
lyric_game/
├── __init__.py              # 插件入口
├── main.py                  # AstrBot插件主文件
├── _conf_schema.json        # 插件配置
├── requirements.txt         # 依赖列表
└── readme.md               # 说明文档
```

## 依赖库

- `aiohttp>=3.8.0` - 异步HTTP客户端

## 注意事项

1. **API服务**：确保NeteaseCloudMusicApi服务正常运行
2. **网络连接**：插件需要访问外部API服务
3. **歌词版权**：歌词内容版权归原作者所有
4. **匹配精度**：模糊匹配阈值可根据需求调整

## 故障排查

### 无法识别歌曲
- 检查NeteaseCloudMusicApi服务是否运行
- 确认API地址配置正确
- 查看AstrBot日志获取详细错误信息

### 匹配不准确
- 尝试输入更长的歌词片段
- 检查歌词是否有特殊字符或标点

### 插件未响应
- 确认插件已启用
- 检查是否有其他插件冲突
- 查看日志排查错误

## 更新日志

### v1.0.0
- ✨ 初始版本发布
- 🎵 支持歌词识别和接龙
- 🎯 实现智能匹配算法
- 🔄 支持会话管理和缓存

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

如有问题或建议，请通过GitHub Issues联系。
