#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import requests
import re
import mysql.connector
from mysql.connector import Error

# GitHub API 配置
GITHUB_API_URL = "https://api.github.com"
REPO_OWNER = "xorbitsai"
REPO_NAME = "inference"
IMAGE_PREFIX = "xprobe/xinference:"

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
    """获取最新的两个tag"""
    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/tags"
    headers = get_github_headers()
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    tags = response.json()
    
    if len(tags) < 2:
        print("未找到足够的tag")
        sys.exit(1)
    
    return tags[0]['name'], tags[1]['name']

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
    
    # 检查是否有新tag
    if latest_tag == previous_tag:
        print("没有新的tag")
        with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as f:
            f.write("has_new_images=false\n")
        return
    
    # 构建镜像名称
    image_name = f"{IMAGE_PREFIX}{latest_tag}"
    print(f"新镜像名称: {image_name}")
    
    # 解析镜像信息
    registry_url = "docker.io"
    namespace = "xprobe"
    image_tag = f"xinference:{latest_tag}"
    
    # 将镜像添加到数据库
    has_new_images = insert_image_to_db(registry_url, namespace, image_tag)
    
    # 设置GitHub Actions输出变量
    with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as f:
        f.write(f"has_new_images={str(has_new_images).lower()}\n")
    
    if has_new_images:
        print("发现新镜像，将触发Docker Image Sync工作流")
    else:
        print("未发现新镜像或镜像已存在")

if __name__ == "__main__":
    main()
