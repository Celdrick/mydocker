# Docker 镜像同步工具

这个仓库包含多个 GitHub Actions 工作流，用于从 Docker Hub 拉取镜像并推送到阿里云仓库和私有仓库。

## 功能概述

- **镜像同步**：从 Docker Hub 拉取镜像并推送到目标仓库
- **多仓库支持**：支持推送到阿里云容器镜像服务和私有 Docker 仓库
- **多平台支持**：支持多种平台的镜像 (linux/amd64, linux/arm64)
- **自动化获取**：自动获取 Dify 和 Xinference 项目的最新镜像
- **Webhook 集成**：支持通过 Webhook 添加自定义镜像
- **数据持久化**：自动记录已推送的镜像信息到数据库
- **智能处理**：支持复杂镜像名称的格式化处理

## 工作流说明

### 1. Docker Image Sync 工作流

**功能**：将数据库中标记的镜像同步到目标仓库。

**触发方式**：
- 定时触发：每3小时自动运行一次
- 代码推送触发：当代码推送到 main 分支时
- 手动触发：通过 repository dispatch event

**工作流程**：
1. 从数据库获取待推送的镜像列表
2. 拉取源镜像
3. 重新标记镜像
4. 推送到目标仓库
5. 更新数据库记录

### 2. Fetch Dify Images 工作流

**功能**：自动获取 Dify 项目最新版本的镜像变更并更新到数据库。

**触发方式**：
- 定时触发：每天自动运行一次
- 手动触发：通过 workflow_dispatch

**工作流程**：
1. 获取 Dify 仓库最新的两个数字版本 tag（如 1.1.3 和 1.1.2）
2. 对比两个版本的 docker-compose.yaml 文件，提取新增或更改的镜像
3. 检查镜像是否已存在于数据库中
4. 将新镜像信息添加到数据库或更新现有镜像状态
5. 当发现新镜像时，自动触发 Docker Image Sync 工作流进行同步

### 3. Fetch Xinference Tags 工作流

**功能**：自动获取 Xinference 项目最新版本的 tag 并更新到数据库。

**触发方式**：
- 定时触发：每天自动运行一次
- 手动触发：通过 workflow_dispatch

**工作流程**：
1. 获取 xorbitsai/inference 仓库的最新 tag（如 v1.4.0）
2. 将最新 tag 转换为镜像名称（如 xprobe/xinference:v1.4.0）
3. 检查镜像是否已存在于数据库中
4. 将新镜像信息添加到数据库或更新现有镜像状态
5. 当发现新镜像时，自动触发 Docker Image Sync 工作流进行同步

### 4. Webhook Image Sync 工作流

**功能**：接收外部 Webhook 请求，添加指定的镜像到同步队列。

**触发方式**：
- Webhook：通过 repository_dispatch 事件，类型为 add-image

**工作流程**：
1. 接收 Webhook 中传入的镜像参数
2. 解析镜像信息（registry、namespace、name:tag）
3. 检查镜像是否已存在于数据库中
4. 将新镜像信息添加到数据库或更新现有镜像状态
5. 当成功添加新镜像时，自动触发 Docker Image Sync 工作流进行同步

**使用方法**：
发送 POST 请求到 GitHub API：

## 配置

在 GitHub 仓库的 Secrets 中配置以下变量：

### 数据库配置
- `MYSQL_HOST`: MySQL 主机地址
- `MYSQL_PORT`: MySQL 端口
- `MYSQL_DB`: 数据库名称
- `MYSQL_USER`: 数据库用户名
- `MYSQL_PASSWORD`: 数据库密码

### 阿里云仓库配置
- `ALIYUN_REGISTRY`: 阿里云仓库地址
- `ALIYUN_NAME_SPACE`: 阿里云命名空间
- `ALIYUN_REGISTRY_USER`: 阿里云仓库用户名
- `ALIYUN_REGISTRY_PASSWORD`: 阿里云仓库密码

### 私有仓库配置
- `MY_REGISTRY`: 私有仓库地址
- `MY_REGISTRY_USER`: 私有仓库用户名
- `MY_REGISTRY_PASSWORD`: 私有仓库密码

### GitHub 配置
- `GITHUB_TOKEN`: GitHub API 访问令牌（用于获取仓库内容）

## 数据库表结构

### images_for_push 表
存储需要推送的镜像信息

```sql
CREATE TABLE IF NOT EXISTS images_for_push (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_registry_url VARCHAR(255) DEFAULT 'docker.io',
    orig_name_space VARCHAR(255),
    orig_image_name VARCHAR(255),
    add_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    platform VARCHAR(50) DEFAULT 'linux/amd64',
    push_status TINYINT DEFAULT 0,
    INDEX idx_push_status (push_status),
    INDEX idx_orig_image_name (orig_image_name)
)
```

### pushed_images 表
存储已推送的镜像信息
