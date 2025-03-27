#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import requests
import yaml
import re
import mysql.connector
from mysql.connector import Error

# GitHub API 配置
GITHUB_API_URL = "https://api.github.com"
REPO_OWNER = "langgenius"
REPO_NAME = "dify"
DOCKER_COMPOSE_PATH = "docker/docker-compose.yaml"

def get_github_headers():
    """获取GitHub API请求头"""
    token = os.environ.get("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    if token:
        headers["Authorization"] = f"token {token}"
    return headers

def get_latest_tags():
    """获取最新的两个不带v前缀的tag"""
    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/tags"
    headers = get_github_headers()
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    tags = response.json()
    # 过滤出不带v前缀的tag
    numeric_tags = [tag for tag in tags if re.match(r'^[0-9]+\.[0-9]+\.[0-9]+', tag['name'])]
    
    if len(numeric_tags) < 2:
        print("未找到足够的数字版本tag")
        sys.exit(1)
    
    return numeric_tags[0]['name'], numeric_tags[1]['name']

def get_file_content(tag, path):
    """获取指定tag中文件的内容"""
    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path}?ref={tag}"
    headers = get_github_headers()
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    content = response.json()
    if 'content' in content:
        import base64
        return base64.b64decode(content['content']).decode('utf-8')
    else:
        print(f"无法获取文件内容: {path} 在 {tag}")
        return None

def extract_images_from_yaml(yaml_content):
    """从YAML内容中提取所有镜像标签"""
    if not yaml_content:
        return []
    
    try:
        docker_compose = yaml.safe_load(yaml_content)
        images = []
        
        # 遍历所有服务
        for service_name, service_config in docker_compose.get('services', {}).items():
            if 'image' in service_config:
                image = service_config['image']
                images.append(image)
        
        return images
    except Exception as e:
        print(f"解析YAML时出错: {e}")
        return []

def parse_image_info(image):
    """解析镜像信息，返回(registry_url, namespace, name:tag)"""
    # 默认registry为docker.io
    registry_url = "docker.io"
    
    # 检查是否包含自定义registry
    if '/' in image:
        parts = image.split('/')
        # 如果第一部分包含点或冒号，则认为是自定义registry
        if '.' in parts[0] or ':' in parts[0]:
            registry_url = parts[0]
            image = '/'.join(parts[1:])
    
    # 解析namespace和name:tag
    if '/' in image:
        namespace, name_tag = image.split('/', 1)
    else:
        # 对于没有命名空间的镜像，如果是docker.io，则默认命名空间为library
        namespace = "library" if registry_url == "docker.io" else ""
        name_tag = image
    
    return registry_url, namespace, name_tag

def get_db_connection():
    """获取数据库连接"""
    try:
        connection = mysql.connector.connect(
            host=os.environ.get('MYSQL_HOST'),
            port=os.environ.get('MYSQL_PORT'),
            user=os.environ.get('MYSQL_USER'),
            password=os.environ.get('MYSQL_PASSWORD'),
            database=os.environ.get('MYSQL_DB')
        )
        return connection
    except Error as e:
        print(f"数据库连接错误: {e}")
        sys.exit(1)

def insert_image_to_db(registry_url, namespace, image_name, platform="linux/amd64"):
    """将镜像信息插入数据库"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # 首先检查pushed_images表中是否已存在相同的镜像（忽略push_status值）
        cursor.execute("""
        SELECT COUNT(*) FROM pushed_images 
        WHERE source_registry_url = %s AND orig_name_space = %s AND orig_image_name = %s
        """, (registry_url, namespace, image_name))
        
        count_pushed = cursor.fetchone()[0]
        if count_pushed > 0:
            print(f"镜像已在pushed_images表中存在: {registry_url}/{namespace}/{image_name}，跳过")
            return False
        
        # 检查images_for_push表中是否已存在相同的镜像
        cursor.execute("""
        SELECT id, push_status FROM images_for_push 
        WHERE source_registry_url = %s AND orig_name_space = %s AND orig_image_name = %s
        """, (registry_url, namespace, image_name))
        
        result = cursor.fetchone()
        if result:
            image_id, push_status = result
            if push_status == 1:  # 如果状态为已推送，重置为未推送
                cursor.execute("""
                UPDATE images_for_push SET push_status = 0
                WHERE id = %s
                """, (image_id,))
                connection.commit()
                print(f"已重置镜像状态: {registry_url}/{namespace}/{image_name}")
                return True
            else:
                print(f"镜像已存在且未推送: {registry_url}/{namespace}/{image_name}")
                return False
        else:
            # 插入新镜像
            cursor.execute("""
            INSERT INTO images_for_push 
            (source_registry_url, orig_name_space, orig_image_name, platform, push_status)
            VALUES (%s, %s, %s, %s, 0)
            """, (registry_url, namespace, image_name, platform))
            connection.commit()
            print(f"已添加新镜像: {registry_url}/{namespace}/{image_name}")
            return True
    except Error as e:
        print(f"数据库操作错误: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def main():
    # 获取最新的两个tag
    latest_tag, previous_tag = get_latest_tags()
    print(f"最新tag: {latest_tag}, 前一个tag: {previous_tag}")
    
    # 获取两个tag中的docker-compose.yaml内容
    latest_content = get_file_content(latest_tag, DOCKER_COMPOSE_PATH)
    previous_content = get_file_content(previous_tag, DOCKER_COMPOSE_PATH)
    
    # 提取镜像标签
    latest_images = extract_images_from_yaml(latest_content)
    previous_images = extract_images_from_yaml(previous_content)
    
    # 找出新增或更改的镜像
    new_or_changed_images = set(latest_images) - set(previous_images)
    
    has_new_images = False
    
    # 将新镜像添加到数据库
    for image in new_or_changed_images:
        registry_url, namespace, image_name = parse_image_info(image)
        if insert_image_to_db(registry_url, namespace, image_name):
            has_new_images = True
    
    # 设置GitHub Actions输出变量
    with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as f:
        f.write(f"has_new_images={str(has_new_images).lower()}\n")
    
    if has_new_images:
        print("发现新镜像，将触发Docker Image Sync工作流")
    else:
        print("未发现新镜像")

if __name__ == "__main__":
    main()
