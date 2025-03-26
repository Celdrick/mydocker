#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import subprocess
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import re
import json

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

def get_images_to_push():
    """从数据库获取需要推送的镜像列表"""
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    
    try:
        # 初始化数据库和表
        from init_db import init_database
        init_database()
        
        # 获取待推送的镜像
        cursor.execute("""
        SELECT id, source_registry_url, orig_name_space, orig_image_name, platform
        FROM images_for_push
        WHERE push_status = 0
        """)
        images = cursor.fetchall()
        return images
    except Error as e:
        print(f"查询数据库错误: {e}")
        return []
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def is_image_pushed(orig_image_name, target_registry_url):
    """检查镜像是否已经推送到目标仓库"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        cursor.execute("""
        SELECT COUNT(*) FROM pushed_images 
        WHERE orig_image_name = %s AND target_registry_url = %s
        """, (orig_image_name, target_registry_url))
        
        count = cursor.fetchone()[0]
        return count > 0
    except Error as e:
        print(f"查询已推送镜像错误: {e}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def format_registry_image_name(source_registry_url, orig_name_space, orig_image_name, target_registry_url, targ_name_space):
    """格式化目标仓库中的镜像名称"""
    # 提取镜像名和标签
    if ':' in orig_image_name:
        image_name, tag = orig_image_name.split(':', 1)
    else:
        image_name = orig_image_name
        tag = 'latest'
    
    # 处理复杂的镜像名
    if '/' in image_name:
        # 对于类似 kube-state-metrics/kube-state-metrics 的情况，只保留最后一部分
        image_name = image_name.split('/')[-1]
    
    # 构建完整的目标镜像名
    registry_image_name = f"{target_registry_url}/{targ_name_space}/{image_name}:{tag}"
    
    return registry_image_name

def get_image_info(image_name):
    """获取镜像大小和摘要信息"""
    try:
        # 获取镜像大小
        size_cmd = f"docker image inspect {image_name} --format='{{{{.Size}}}}'"
        size_output = subprocess.check_output(size_cmd, shell=True).decode('utf-8').strip()
        # 转换为浮点数，单位为MB
        size_mb = float(size_output) / (1024 * 1024)
        
        # 获取镜像摘要
        digest_cmd = f"docker image inspect {image_name} --format='{{{{.RepoDigests}}}}'"
        digest_output = subprocess.check_output(digest_cmd, shell=True).decode('utf-8').strip()
        # 提取摘要部分
        digest_match = re.search(r'sha256:[a-f0-9]+', digest_output)
        digest = digest_match.group(0) if digest_match else ""
        
        return size_mb, digest
    except subprocess.CalledProcessError as e:
        print(f"获取镜像信息错误: {e}")
        return 0.0, "未知"

def record_pushed_image(source_registry_url, target_registry_url, orig_name_space, 
                        orig_image_name, targ_name_space, registry_image_name, 
                        image_size, digest, platform):
    """记录已推送的镜像信息"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        cursor.execute("""
        INSERT INTO pushed_images 
        (source_registry_url, target_registry_url, orig_name_space, orig_image_name, 
         targ_name_space, registry_image_name, push_status, image_size, digest, platform)
        VALUES (%s, %s, %s, %s, %s, %s, 1, %s, %s, %s)
        """, (
            source_registry_url, target_registry_url, orig_name_space, orig_image_name,
            targ_name_space, registry_image_name, image_size, digest, platform
        ))
        connection.commit()
    except Error as e:
        print(f"记录已推送镜像错误: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def update_push_status(image_id):
    """更新images_for_push表中的推送状态"""
    connection = get_db_connection()
    cursor = connection.cursor()
    
    try:
        cursor.execute("""
        UPDATE images_for_push SET push_status = 1
        WHERE id = %s
        """, (image_id,))
        connection.commit()
    except Error as e:
        print(f"更新推送状态错误: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def pull_and_push_image(image, target):
    """拉取并推送镜像"""
    source_registry_url = image['source_registry_url']
    orig_name_space = image['orig_name_space']
    orig_image_name = image['orig_image_name']
    platform = image['platform']
    
    # 构建完整的源镜像名
    if source_registry_url == 'docker.io':
        source_image = f"{orig_name_space}/{orig_image_name}" if orig_name_space else orig_image_name
    else:
        source_image = f"{source_registry_url}/{orig_name_space}/{orig_image_name}"
    
    print(f"处理镜像: {source_image}, 平台: {platform}")
    
    # 设置目标仓库信息
    if target == 'aliyun':
        target_registry_url = os.environ.get('ALIYUN_REGISTRY')
        registry_user = os.environ.get('ALIYUN_REGISTRY_USER')
        registry_password = os.environ.get('ALIYUN_REGISTRY_PASSWORD')
        targ_name_space = os.environ.get('ALIYUN_NAME_SPACE')
    else:  # private
        target_registry_url = os.environ.get('MY_REGISTRY')
        registry_user = os.environ.get('MY_REGISTRY_USER')
        registry_password = os.environ.get('MY_REGISTRY_PASSWORD')
        targ_name_space = orig_name_space
    
    # 移除URL中的协议部分
    target_registry_url = re.sub(r'^https?://', '', target_registry_url)
    
    # 检查镜像是否已推送
    if is_image_pushed(orig_image_name, target_registry_url):
        print(f"镜像 {orig_image_name} 已经推送到 {target_registry_url}，跳过")
        return
    
    try:
        # 拉取镜像
        pull_cmd = f"docker pull --platform={platform} {source_image}"
        print(f"拉取镜像: {pull_cmd}")
        subprocess.run(pull_cmd, shell=True, check=True)
        
        # 登录目标仓库
        login_cmd = f"docker login {target_registry_url} -u {registry_user} -p {registry_password}"
        print(f"登录仓库: {target_registry_url}")
        subprocess.run(login_cmd, shell=True, check=True)
        
        # 格式化目标镜像名
        registry_image_name = format_registry_image_name(
            source_registry_url, orig_name_space, orig_image_name, 
            target_registry_url, targ_name_space
        )
        
        # 标记镜像
        tag_cmd = f"docker tag {source_image} {registry_image_name}"
        print(f"标记镜像: {tag_cmd}")
        subprocess.run(tag_cmd, shell=True, check=True)
        
        # 推送镜像
        push_cmd = f"docker push {registry_image_name}"
        print(f"推送镜像: {push_cmd}")
        subprocess.run(push_cmd, shell=True, check=True)
        
        # 获取镜像信息 - 这里image_size现在是浮点数
        image_size, digest = get_image_info(registry_image_name)
        
        # 记录已推送的镜像
        record_pushed_image(
            source_registry_url, target_registry_url, orig_name_space,
            orig_image_name, targ_name_space, registry_image_name,
            image_size, digest, platform
        )
        
        # 移除对 update_push_status 的调用
        
        print(f"镜像 {source_image} 成功推送到 {registry_image_name}，大小: {image_size:.2f}MB")
        
        # 清理本地镜像
        subprocess.run(f"docker rmi {source_image} {registry_image_name}", shell=True)
        
    except subprocess.CalledProcessError as e:
        print(f"处理镜像 {source_image} 时出错: {e}")

def main():
    parser = argparse.ArgumentParser(description='Docker镜像同步工具')
    parser.add_argument('--target', choices=['aliyun', 'private'], required=True, help='目标仓库类型')
    args = parser.parse_args()
    
    # 获取需要推送的镜像列表
    images = get_images_to_push()
    
    if not images:
        print("没有找到需要推送的镜像")
        return
    
    print(f"找到 {len(images)} 个需要推送的镜像")
    
    # 处理每个镜像
    for image in images:
        pull_and_push_image(image, args.target)

if __name__ == "__main__":
    main()
