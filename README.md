# WebAuthn & 声纹身份认证系统

一个基于 WebAuthn（设备生物识别）和声纹特征的无密码身份认证 Web 应用系统。

## 系统架构

```
a21/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── core/       # 核心配置（安全、配置
│   │   ├── routers/    # API 路由
│   │   ├── services/  # 业务服务（声纹、WebAuthn）
│   │   ├── database.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   └── main.py
│   ├── sql/init.sql  # 数据库初始化
│   ├── init_db.py
│   └── requirements.txt
└── frontend/         # React + TypeScript 前端
    └── src/
        ├── components/   # UI 组件
        ├── contexts/     # React Context
        ├── hooks/        # 自定义 Hooks
        ├── pages/        # 页面
        ├── services/   # API 服务
        ├── types/      # TypeScript 类型
        └── utils/      # 工具函数
```

## 核心功能

- 🔐 **WebAuthn 设备绑定/登录**
  - 支持指纹、面容、Windows Hello 等设备生物识别
  - 支持一台设备绑定多个账户
  - 一个账户可绑定多台设备

- 🎤 **声纹认证**
  - 使用 librosa 提取 MFCC 声纹特征向量（40维 MFCC + delta + delta2，共200维）
  - 使用余弦相似度进行声纹比对
  - 动态随机数字验证（防录音攻击）
  - 一个账户可录入多条声纹样本

- 👤 **用户管理**
  - 用户资料管理
  - 设备绑定/解绑
  - 声纹录入/删除

## 技术栈

### 后端
- **FastAPI** - 现代 Python Web 框架
- **PostgreSQL + pgvector** - 关系数据库 + 向量存储
- **WebAuthn (py_webauthn)** - WebAuthn 协议实现
- **librosa** - 音频特征提取
- **SQLAlchemy** - ORM
- **JWT** - 访问令牌

### 前端
- **React 18 + TypeScript**
- **Vite** - 构建工具
- **TailwindCSS** - 样式
- **@simplewebauthn/browser** - WebAuthn 浏览器端
- **MediaRecorder API** - 音频录制
- **React Router** - 路由

## 快速开始

### 1. 数据库准备

确保已安装 PostgreSQL，并安装 pgvector 扩展：

```bash
# 创建数据库
createdb webauthn_voiceprint

# 启用 pgvector 扩展（在 psql 中执行）
CREATE EXTENSION vector;
```

或使用提供的 SQL 脚本：
```bash
psql -d webauthn_voiceprint -f backend/sql/init.sql
```

### 2. 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv

# 激活虚拟环境 (Windows)
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
copy .env.example .env
# 编辑 .env 文件，配置数据库连接等

# 初始化数据库
python init_db.py

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端 API 文档: http://localhost:8000/docs

### 3. 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端地址: http://localhost:5173

## 使用流程

### 用户注册

1. 填写基本信息（用户名、邮箱）
2. **绑定设备** - 使用 WebAuthn 进行设备生物识别
3. **录入声纹** - 录制 3 秒语音（可跳过）
4. 完成注册

### 用户登录（两种方式二选一）

#### 方式一：WebAuthn 设备登录
- 点击"使用设备登录"
- 浏览器调用设备生物识别（指纹/面容等）
- 验证成功即可登录

#### 方式二：声纹验证登录
- 系统生成 4 位随机动态数字
- 用户对着麦克风读出该数字
- 后端提取声纹特征，与数据库中所有声纹向量比对
- 相似度达到阈值（默认 0.85）即验证通过

## API 端点

### 认证相关
- `POST /api/auth/webauthn/start` - 开始 WebAuthn 登录
- `POST /api/auth/webauthn/finish` - 完成 WebAuthn 登录
- `GET /api/auth/me` - 获取当前用户信息

### WebAuthn 注册
- `POST /api/webauthn/register/start` - 开始设备绑定
- `POST /api/webauthn/register/finish` - 完成设备绑定
- `GET /api/webauthn/credentials` - 获取绑定设备列表
- `DELETE /api/webauthn/credentials/{id}` - 删除设备

### 声纹相关
- `POST /api/voice/enroll` - 录入声纹
- `GET /api/voice/challenge` - 获取声纹验证挑战（动态数字）
- `POST /api/voice/verify` - 声纹验证（不登录）
- `POST /api/voice/verify-login` - 声纹验证并登录
- `GET /api/voice/voiceprints` - 获取声纹列表
- `DELETE /api/voice/voiceprints/{id}` - 删除声纹

## 声纹特征说明

系统使用 librosa 提取以下声学特征，拼接为 200 维向量：

| 特征 | 维度 |
|------|------|
| MFCC 均值 | 40 |
| MFCC 标准差 | 40 |
| Delta MFCC 均值 | 40 |
| Delta MFCC 标准差 | 40 |
| Delta2 MFCC 均值 | 40 |
| **总计** | **200 |

使用余弦相似度进行声纹比对，阈值默认 0.85，可在 `.env` 中调整。

## 安全说明

- WebAuthn 使用标准 FIDO2 协议，公钥私钥对存储在设备本地
- 声纹验证使用动态随机数字，防止录音重放攻击
- 所有音频特征向量使用 pgvector 存储并支持高效向量检索
- JWT 令牌用于会话管理

## 浏览器兼容性

WebAuthn 支持的浏览器/平台：
- Chrome 67+
- Edge 18+
- Safari 13+
- Firefox 60+
- 移动端 Safari / Chrome Android

## License

MIT
