#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import mysql.connector
from mysql.connector import Error

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

def insert_image_to_db(registry_url, namespace, image_name, platform="linux/amd64"):
    """将镜像信息插入数据库"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        # # 首先检查pushed_images表中是否已存在相同的镜像（忽略push_status值）
        # cursor.execute("""
        # SELECT COUNT(*) FROM pushed_images 
        # WHERE source_registry_url = %s AND orig_name_space = %s AND orig_image_name = %s
        # """, (registry_url, namespace, image_name))
        
        # count_pushed = cursor.fetchone()[0]
        # if count_pushed > 0:
        #     print(f"镜像已在pushed_images表中存在: {registry_url}/{namespace}/{image_name}，跳过")
        #     return False
        
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
                return True
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

def process_images(images_data):
    """处理多个镜像"""
    has_new_images = False
    
    print(f"接收到的原始数据: {images_data}")
    
    # 如果输入是字符串，尝试解析为JSON
    if isinstance(images_data, str):
        try:
            # 尝试直接解析
            images = json.loads(images_data)
            print(f"JSON解析后的数据: {images}")
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {e}")
            # 如果不是有效的JSON，则视为单个镜像
            images = [images_data]
    else:
        images = images_data
    
    # 确保images是列表
    if not isinstance(images, list):
        images = [images]
    
    print(f"最终处理的镜像列表: {images}")
    
    # 处理每个镜像
    for image in images:
        if image is None:
            print("警告: 发现空镜像，跳过")
            continue
            
        print(f"处理镜像: {image}")
        registry_url, namespace, image_name = parse_image_info(image)
        if insert_image_to_db(registry_url, namespace, image_name):
            has_new_images = True
    
    return has_new_images

def main():
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("错误: 缺少镜像参数")
        print("用法: python add_webhook_image.py <image_json_file>")
        sys.exit(1)
    
    # 获取镜像参数文件
    image_file = sys.argv[1]
    
    try:
        # 从文件读取JSON数据
        with open(image_file, 'r') as f:
            images_data = f.read().strip()
        
        # 处理镜像
        has_new_images = process_images(images_data)
        
        # 设置GitHub Actions输出变量
        with open(os.environ.get('GITHUB_OUTPUT', '/dev/null'), 'a') as f:
            f.write(f"has_new_images={str(has_new_images).lower()}\n")
        
        if has_new_images:
            print("发现新镜像，将触发Docker Image Sync工作流")
        else:
            print("未发现新镜像或镜像已存在")
    except Exception as e:
        print(f"处理镜像时发生错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
